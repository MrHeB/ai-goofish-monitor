"""闲鱼扫码登录服务：通过 passport.goofish.com 接口生成二维码，手机扫码确认后
获取登录 Cookie，并转换为 Playwright storage_state JSON（与浏览器授权导出的格式一致），
可直接被爬虫作为 storage_state 加载。

实现参考 C:\\咸鱼助手\\xianyu-next\\utils\\qr_login.py（myfish 方案）。
"""
import asyncio
import calendar
import email.utils
import json
import os
import re
import time
import uuid
from http.cookies import SimpleCookie
from random import random
from typing import Any, Dict, Optional

import httpx
import qrcode
import qrcode.constants

# 登录成功后必然存在的关键 Cookie 名（与 scraper / browser_auth 对齐）
LOGIN_COOKIE_MARKERS = ("unb", "cookie2", "tracknick", "sgcookie")


def _generate_headers() -> dict:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
    }


# 请求 passport/goofish 登录接口时的统一客户端参数。
# trust_env=False：不走系统代理/环境变量代理，避免代理连接不稳定导致扫码登录失败。
_QR_CLIENT_KWARGS = {
    "follow_redirects": True,
    "trust_env": False,
    "timeout": httpx.Timeout(20.0),
}


def _new_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(**_QR_CLIENT_KWARGS)


def _parse_set_cookie(headers, default_domain: str) -> list[dict]:
    """解析 Set-Cookie 响应头为 storage_state 兼容的 cookie 字典。"""
    if not headers:
        return []
    parsed = SimpleCookie()
    try:
        parsed.load(";".join(headers))
    except Exception:  # noqa: BLE001 - 单个坏 cookie 不影响整体
        return []

    records = []
    now = int(time.time())
    for key, morsel in parsed.items():
        expires = -1
        max_age = morsel.get("max-age")
        if max_age not in (None, ""):
            try:
                expires = now + int(max_age)
            except (TypeError, ValueError):
                expires = -1
        else:
            raw_expires = morsel.get("expires")
            if raw_expires:
                try:
                    dt = email.utils.parsedate_to_datetime(raw_expires)
                    expires = calendar.timegm(dt.utctimetuple())
                except (TypeError, ValueError, OverflowError):
                    expires = -1

        domain = morsel.get("domain") or default_domain
        same_site = (morsel.get("samesite") or "Lax").capitalize()
        records.append({
            "name": key,
            "value": morsel.value,
            "domain": domain,
            "path": morsel.get("path") or "/",
            "expires": expires,
            "httpOnly": bool(morsel.get("httponly")),
            "secure": bool(morsel.get("secure")),
            "sameSite": same_site if same_site in ("Lax", "Strict", "None") else "Lax",
        })
    return records


class GetLoginParamsError(Exception):
    """获取登录参数错误"""


class GetLoginQRCodeError(Exception):
    """获取登录二维码失败"""


class QRLoginSession:
    """一次扫码登录会话"""

    def __init__(self, session_id: str, account_name: str, target_path: str):
        self.session_id = session_id
        self.account_name = account_name
        self.target_path = target_path
        self.status = "waiting"  # waiting / scanned / success / expired / cancelled / verification_required
        self.qr_code_url: Optional[str] = None
        self.qr_content: Optional[str] = None
        self.cookies: Dict[str, str] = {}  # name -> value（用于后续请求带上）
        self.cookie_records: Dict[str, dict] = {}  # name -> storage_state cookie（含 domain 等属性）
        self.unb: Optional[str] = None
        self.created_time = time.time()
        self.expire_time = 300  # 5 分钟过期
        self.params: Dict[str, Any] = {}
        self.verification_url: Optional[str] = None
        self.message: Optional[str] = None

    def is_expired(self) -> bool:
        return time.time() - self.created_time > self.expire_time

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "account_name": self.account_name,
            "status": self.status,
            "qr_code_url": self.qr_code_url,
            "created_time": self.created_time,
            "is_expired": self.is_expired(),
        }


class QRLoginManager:
    """闲鱼扫码登录管理器（内存会话 + 后台轮询）"""

    def __init__(self):
        self.sessions: Dict[str, QRLoginSession] = {}
        self.headers = _generate_headers()
        self.host = "https://passport.goofish.com"
        self.api_mini_login = f"{self.host}/mini_login.htm"
        self.api_generate_qr = f"{self.host}/newlogin/qrcode/generate.do"
        self.api_scan_status = f"{self.host}/newlogin/qrcode/query.do"
        self.api_h5_tk = "https://h5api.m.goofish.com/h5/mtop.gaia.nodejs.gaia.idle.data.gw.v2.index.get/1.0/"

    # ---------- 内部请求 ----------

    async def _get_mh5tk(self, session: QRLoginSession) -> None:
        params = {
            "jsv": "2.7.2",
            "appKey": "34839810",
            "t": int(time.time()),
            "sign": "",
            "v": "1.0",
            "type": "originaljson",
            "accountSite": "xianyu",
            "dataType": "json",
            "timeout": 20000,
            "api": "mtop.gaia.nodejs.gaia.idle.data.gw.v2.index.get",
            "sessionOption": "AutoLoginOnly",
            "spm_cnt": "a21ybx.home.0.0",
        }
        async with _new_client() as client:
            resp = await client.post(self.api_h5_tk, params=params, headers=self.headers)
            self._absorb_cookies(session, resp)

    async def _get_login_params(self, session: QRLoginSession) -> dict:
        params = {
            "lang": "zh_cn",
            "appName": "xianyu",
            "appEntrance": "web",
            "styleType": "vertical",
            "bizParams": "",
            "notLoadSsoView": False,
            "notKeepLogin": False,
            "isMobile": False,
            "qrCodeFirst": False,
            "stie": 77,
            "rnd": random(),
        }
        async with _new_client() as client:
            resp = await client.get(
                self.api_mini_login,
                params=params,
                cookies=session.cookies,
                headers=self.headers,
            )
            self._absorb_cookies(session, resp)
            pattern = r"window\.viewData\s*=\s*(\{.*?\});"
            match = re.search(pattern, resp.text)
            if match:
                view_data = json.loads(match.group(1))
                data = view_data.get("loginFormData")
                if data:
                    data["umidTag"] = "SERVER"
                    session.params.update(data)
                    return data
            raise GetLoginParamsError("获取登录参数失败")

    async def _poll_qrcode_status(self, session: QRLoginSession) -> httpx.Response:
        async with _new_client() as client:
            resp = await client.post(
                self.api_scan_status,
                data=session.params,
                cookies=session.cookies,
                headers=self.headers,
            )
            self._absorb_cookies(session, resp)
            return resp

    @staticmethod
    def _absorb_cookies(session: QRLoginSession, resp: httpx.Response) -> None:
        """把本次响应的 cookie 吸收进会话（值用于后续请求，属性用于生成 storage_state）。"""
        default_domain = resp.url.host if resp.url else "passport.goofish.com"
        for record in _parse_set_cookie(resp.headers.get_list("set-cookie"), default_domain):
            session.cookie_records[record["name"]] = record
        for k, v in resp.cookies.items():
            session.cookies[k] = v
            session.cookie_records.setdefault(
                k,
                {
                    "name": k,
                    "value": v,
                    "domain": default_domain,
                    "path": "/",
                    "expires": -1,
                    "httpOnly": False,
                    "secure": False,
                    "sameSite": "Lax",
                },
            )

    # ---------- 对外接口 ----------

    async def create_session(self, account_name: str, target_path: str) -> dict:
        """生成二维码并启动后台状态监控。"""
        self.cleanup_expired_sessions()
        # 偶发的瞬时网络抖动/服务端限流会导致单次失败，最多重试 3 次
        last_error: Optional[Exception] = None
        for attempt in range(3):
            session_id = str(uuid.uuid4())
            session = QRLoginSession(session_id, account_name, target_path)
            try:
                # 1. 获取 m_h5_tk
                await self._get_mh5tk(session)
                # 2. 获取登录参数
                login_params = await self._get_login_params(session)
                # 3. 生成二维码
                async with _new_client() as client:
                    resp = await client.get(
                        self.api_generate_qr,
                        params=login_params,
                        headers=self.headers,
                    )
                    self._absorb_cookies(session, resp)
                    results = resp.json()
                content = results.get("content") or {}
                if content.get("success") is True:
                    data = content.get("data") or {}
                    session.params.update({
                        "t": data.get("t"),
                        "ck": data.get("ck"),
                    })
                    session.qr_content = data.get("codeContent")
                    if not session.qr_content:
                        raise GetLoginQRCodeError("二维码内容为空")
                    session.qr_code_url = _render_qr_data_url(session.qr_content)
                    session.status = "waiting"
                    self.sessions[session_id] = session
                    asyncio.create_task(self._monitor_qr_status(session_id))
                    return {
                        "success": True,
                        "session_id": session_id,
                        "qr_code_url": session.qr_code_url,
                        "expires_in": session.expire_time,
                    }
                raise GetLoginQRCodeError("获取登录二维码失败")
            except Exception as e:  # noqa: BLE001 - 失败后短暂等待并重试
                last_error = e
                if attempt < 2:
                    await asyncio.sleep(1.0 + attempt)
        return {"success": False, "message": f"生成二维码失败: {last_error}"}

    def get_status(self, session_id: str) -> dict:
        session = self.sessions.get(session_id)
        if not session:
            return {"status": "not_found", "session_id": session_id}
        if session.is_expired() and session.status not in ("success", "verification_required"):
            session.status = "expired"
        result = {
            "status": session.status,
            "session_id": session_id,
            "account_name": session.account_name,
        }
        if session.status == "verification_required":
            result["message"] = "账号被风控，需要手机验证"
            if session.verification_url:
                result["verification_url"] = session.verification_url
        if session.status == "success":
            result["message"] = "登录成功，账号已保存"
            result["path"] = session.target_path
            result["cookies"] = len(session.cookie_records)
        if session.message:
            result["message"] = session.message
        return result

    def cleanup_expired_sessions(self) -> None:
        for sid in [sid for sid, s in self.sessions.items() if s.is_expired()]:
            del self.sessions[sid]

    # ---------- 后台监控 ----------

    async def _monitor_qr_status(self, session_id: str) -> None:
        session = self.sessions.get(session_id)
        if not session:
            return
        start_time = time.time()
        try:
            while time.time() - start_time < session.expire_time:
                if session_id not in self.sessions:
                    return
                try:
                    resp = await self._poll_qrcode_status(session)
                    data = (resp.json().get("content") or {}).get("data") or {}
                    qr_status = data.get("qrCodeStatus")

                    if qr_status == "CONFIRMED":
                        if data.get("iframeRedirect") is True:
                            session.status = "verification_required"
                            session.verification_url = data.get("iframeRedirectUrl")
                            session.message = "账号被风控，需要手机验证"
                            return
                        session.status = "success"
                        for k, v in resp.cookies.items():
                            if k == "unb":
                                session.unb = v
                        self._save_session_state(session)
                        return
                    if qr_status == "NEW":
                        pass  # 未被扫描，继续轮询
                    elif qr_status == "SCANED":
                        if session.status == "waiting":
                            session.status = "scanned"
                    elif qr_status == "EXPIRED":
                        session.status = "expired"
                        return
                    else:
                        session.status = "cancelled"
                        return
                except Exception as e:  # noqa: BLE001 - 网络抖动继续重试
                    session.message = f"查询扫码状态异常: {e}"
                    await asyncio.sleep(2)
                    continue
                await asyncio.sleep(0.8)
            if session.status not in ("success", "expired", "cancelled", "verification_required"):
                session.status = "expired"
                session.message = "二维码已过期"
        except Exception as e:  # noqa: BLE001
            session.status = "expired"
            session.message = f"监控扫码状态失败: {e}"

    def _save_session_state(self, session: QRLoginSession) -> None:
        """把会话 cookie 保存为 storage_state JSON 到账号文件。"""
        # 剔除会话 token 类 cookie：扫码时通过 HTTP 获取的 _m_h5_tk 与浏览器会话不匹配，
        # 浏览器加载页面后 mtop.js 会自动获取新 token。
        session_token_names = {
            "_m_h5_tk",
            "_m_h5_tk_enc",
            "mtop_partitioned_detect",
            "XSRF-TOKEN",
        }
        cookies = [
            c
            for c in session.cookie_records.values()
            if c.get("name") not in session_token_names
        ]
        storage = {"cookies": cookies, "origins": []}
        parent = os.path.dirname(os.path.abspath(session.target_path))
        os.makedirs(parent, exist_ok=True)
        with open(session.target_path, "w", encoding="utf-8") as f:
            json.dump(storage, f, ensure_ascii=False, indent=2)


def _render_qr_data_url(content: str) -> str:
    """把二维码内容渲染为 base64 data URL，供前端 <img> 直接展示。"""
    from io import BytesIO
    import base64

    qr = qrcode.QRCode(
        version=5,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=2,
    )
    qr.add_data(content)
    qr.make()
    img = qr.make_image()
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    return f"data:image/png;base64,{base64.b64encode(buffer.getvalue()).decode()}"


# 全局实例
qr_login_manager = QRLoginManager()
