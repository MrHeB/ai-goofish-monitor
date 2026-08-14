"""浏览器授权服务：打开真实浏览器窗口让用户登录闲鱼，导出登录态为 storage_state 文件。

导出文件格式与 Playwright `context.storage_state()` 一致（cookies + origins），
可直接被爬虫作为 `storage_state` 加载，无需再通过 Chrome 扩展手动提取 JSON。
"""
import asyncio
import json
import os

from playwright.async_api import async_playwright

from src.config import LOGIN_IS_EDGE, RUNNING_IN_DOCKER

# 与 scraper 对齐的反自动化检测启动参数
STEALTH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--disable-dev-shm-usage",
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-web-security",
    "--disable-features=IsolateOrigins,site-per-process",
]

IGNORE_DEFAULT_ARGS = ["--enable-automation"]

# 登录成功后闲鱼/淘宝域下必然存在的关键 Cookie 名（任一命中即视为已登录）
LOGIN_COOKIE_MARKERS = ("unb", "cookie2", "tracknick", "sgcookie")

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 6.0; Nexus 5 Build/MRA58N) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36"
)

GOOFISH_HOME = "https://www.goofish.com/"

STEALTH_INIT_SCRIPT = """
// 抹掉自动化指纹，降低风控概率
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
if (!window.chrome) {
    window.chrome = { runtime: {} };
}
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh', 'en-US', 'en'] });
"""


def _is_login_url(url: str) -> bool:
    lowered = (url or "").lower()
    return "passport" in lowered or "mini_login" in lowered or "/login" in lowered


class AccountAuthorizationError(Exception):
    """授权流程失败（超时、未登录等）"""


class BrowserAuthorizer:
    """浏览器授权器：单实例，内部锁保证同一时刻只运行一个授权流程。"""

    def __init__(self):
        self._lock = asyncio.Lock()

    async def authorize(self, target_path: str, timeout_sec: int = 300) -> dict:
        """打开有头浏览器等待用户登录，成功后导出 storage_state 到 target_path。"""
        if RUNNING_IN_DOCKER:
            raise AccountAuthorizationError(
                "Docker 环境无法弹出浏览器窗口，请在本地运行后通过 Web UI 添加账号。"
            )
        if timeout_sec <= 0:
            timeout_sec = 300
        async with self._lock:
            return await self._run(target_path, timeout_sec)

    async def _run(self, target_path: str, timeout_sec: int) -> dict:
        async with async_playwright() as p:
            browser = await self._launch_browser(p)
            context = await browser.new_context(
                user_agent=DEFAULT_USER_AGENT,
                viewport={"width": 412, "height": 915},
                device_scale_factor=2.625,
                is_mobile=True,
                has_touch=True,
                locale="zh-CN",
                timezone_id="Asia/Shanghai",
                color_scheme="light",
            )
            await context.add_init_script(STEALTH_INIT_SCRIPT)
            page = await context.new_page()
            try:
                await page.goto(GOOFISH_HOME, wait_until="domcontentloaded", timeout=60000)
                await self._wait_for_login(context, page, timeout_sec)
                storage = await context.storage_state()
                parent_dir = os.path.dirname(os.path.abspath(target_path))
                os.makedirs(parent_dir, exist_ok=True)
                with open(target_path, "w", encoding="utf-8") as f:
                    json.dump(storage, f, ensure_ascii=False, indent=2)
                return {
                    "path": target_path,
                    "cookies": len(storage.get("cookies", [])),
                }
            finally:
                try:
                    await context.close()
                except Exception:
                    pass
                try:
                    await browser.close()
                except Exception:
                    pass

    async def _launch_browser(self, p):
        """按候选通道依次尝试启动有头浏览器：配置通道 → 系统 Edge → 内置 Chromium。

        与 scraper 的通道回退保持一致：未配置时优先系统 Chrome，缺失时回退到
        Win10/11 自带的 Edge，最后才尝试 Playwright 内置浏览器。
        """
        channels = []
        if not RUNNING_IN_DOCKER:
            primary = "msedge" if LOGIN_IS_EDGE else "chrome"
            channels.append(primary)
            if primary == "chrome":
                channels.append("msedge")
        channels.append("chromium")

        last_error: Exception | None = None
        for channel in channels:
            kwargs = {
                "headless": False,
                "args": STEALTH_ARGS,
                "ignore_default_args": IGNORE_DEFAULT_ARGS,
            }
            if channel != "chromium":
                kwargs["channel"] = channel
            try:
                return await p.chromium.launch(**kwargs)
            except Exception as e:  # noqa: BLE001 - 逐个通道尝试
                last_error = e
        raise AccountAuthorizationError(f"无法启动浏览器: {last_error}")

    async def _wait_for_login(self, context, page, timeout_sec: int) -> None:
        """轮询等待用户在浏览器中完成登录。"""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_sec
        while True:
            if loop.time() >= deadline:
                raise AccountAuthorizationError(
                    f"等待登录超时（{timeout_sec} 秒），请重新授权。"
                )
            try:
                if page.is_closed():
                    # 用户关闭了浏览器窗口：以当前 cookie 判断是否已登录
                    if self._has_login_cookie(await context.cookies()):
                        return
                    raise AccountAuthorizationError(
                        "浏览器窗口已关闭但未检测到登录态，授权失败。"
                    )
                if not _is_login_url(page.url) and self._has_login_cookie(
                    await context.cookies()
                ):
                    return
            except AccountAuthorizationError:
                raise
            except Exception:
                # 页面导航中，继续等待
                pass
            await asyncio.sleep(3)

    @staticmethod
    def _has_login_cookie(cookies: list[dict]) -> bool:
        names = {c.get("name", "") for c in cookies}
        return any(marker in names for marker in LOGIN_COOKIE_MARKERS)


# 全局实例
browser_authorizer = BrowserAuthorizer()
