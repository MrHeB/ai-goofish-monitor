"""
桌面启动入口
使用 PyInstaller 打包后作为单一可执行文件的入口，自动启动 FastAPI 服务并打开浏览器。
"""
import os
import shutil
import sys
import time
import webbrowser
from pathlib import Path

import uvicorn

# PyInstaller 打包后工作目录为 exe 所在目录（运行数据、静态资源都落在 exe 旁，便于查看）；
# 未打包时则为当前文件所在目录。
if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent


def _prepare_environment() -> None:
    """确保工作目录和模块路径正确，并指向随包分发的 Playwright 浏览器"""
    os.chdir(BASE_DIR)
    if str(BASE_DIR) not in sys.path:
        sys.path.insert(0, str(BASE_DIR))
    # 开箱即用：优先使用随 exe 一起分发的 browsers/ 目录，
    # 避免目标机器缺少 Playwright 浏览器缓存导致爬虫无法启动。
    _browsers = BASE_DIR / "browsers"
    if _browsers.is_dir():
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(_browsers)

    # 自动创建运行数据目录（新机器首次启动即可用）
    for _d in ("jsonl", "logs", "images", "data", "state"):
        try:
            (BASE_DIR / _d).mkdir(exist_ok=True)
        except OSError:
            pass

    _ensure_prompts_dir()


def _ensure_prompts_dir() -> None:
    """确保 exe 旁存在 prompts/ 目录（含 AI 分析标准参考文件）。

    prompts 参考文件（macbook_criteria.txt 等）随包分发到只读的 _MEIPASS，
    首次启动时复制到 exe 旁，保证任务生成（读取参考文件）与写入新生成的
    criteria 文件都能正常进行。
    """
    target_dir = BASE_DIR / "prompts"
    if (target_dir / "macbook_criteria.txt").is_file():
        return
    # 未打包（源码运行）时直接从项目目录读取
    source_dir = Path(__file__).resolve().parent / "prompts"
    if getattr(sys, "frozen", False):
        _meipass = getattr(sys, "_MEIPASS", "")
        if _meipass:
            bundled = Path(_meipass) / "prompts"
            if bundled.is_dir():
                source_dir = bundled
    if not source_dir.is_dir():
        return
    try:
        target_dir.mkdir(exist_ok=True)
        for _f in source_dir.iterdir():
            if _f.is_file() and not (target_dir / _f.name).exists():
                shutil.copy2(_f, target_dir / _f.name)
    except OSError:
        pass


def _is_spider_worker() -> bool:
    """判断当前进程是否为爬虫工作进程（打包后由 ProcessService 以 exe 子进程方式拉起）。

    ProcessService 用 [sys.executable, "-u", "spider_v2.py", "--task-name", name] 启动子进程，
    打包后 sys.executable 即为本 exe，因此需要根据参数识别出"爬虫工作进程"模式。
    """
    return any(arg.endswith("spider_v2.py") for arg in sys.argv[1:])


def _spider_worker_entry() -> None:
    """爬虫工作进程入口：剔除解释器参数与脚本名后，直接执行 spider_v2 的逻辑。"""
    _prepare_environment()
    _redirect_stdio_if_needed("spider")

    args = [a for a in sys.argv[1:] if a not in ("-u", "-U", "-m") and not a.endswith("spider_v2.py")]
    sys.argv = [sys.argv[0]] + args

    import asyncio

    from spider_v2 import main as spider_main

    asyncio.run(spider_main())


def _stream_is_valid(stream) -> bool:
    """判断标准流是否有效（windowed 模式下句柄无效，fileno 会抛异常）。"""
    try:
        return stream is not None and stream.fileno() >= 0
    except (OSError, ValueError, AttributeError):
        return False


def _redirect_stdio_if_needed(tag: str) -> None:
    """windowed 模式下 stdout/stderr 为无效句柄，写入会抛 OSError。

    仅在 frozen（打包）环境下把无效的标准流重定向到日志文件；
    爬虫子进程由 ProcessService 拉起时 stdout/stderr 已指向任务日志文件，
    保持有效，不会被覆盖。
    """
    if not getattr(sys, "frozen", False):
        return
    stdout_ok, stderr_ok = _stream_is_valid(sys.stdout), _stream_is_valid(sys.stderr)
    if stdout_ok and stderr_ok and _stream_is_valid(sys.stdin):
        return
    os.makedirs("logs", exist_ok=True)
    _log_stream = open(os.path.join("logs", f"{tag}.log"), "a", encoding="utf-8", buffering=1)
    if not stdout_ok:
        sys.stdout = _log_stream
    if not stderr_ok:
        sys.stderr = _log_stream
    if not _stream_is_valid(sys.stdin):
        sys.stdin = open(os.devnull, "r")


def run_app() -> None:
    """启动 FastAPI 应用并自动打开浏览器"""
    _prepare_environment()
    _redirect_stdio_if_needed("uvicorn")

    from src.app import app
    from src.infrastructure.config.settings import settings

    # 先尝试打开浏览器，稍等服务起来
    url = f"http://127.0.0.1:{settings.server_port}"
    webbrowser.open(url)
    time.sleep(0.5)

    uvicorn.run(
        app,
        host="127.0.0.1",
        port=settings.server_port,
        log_level="info",
        reload=False,
    )


if __name__ == "__main__":
    if _is_spider_worker():
        _spider_worker_entry()
    else:
        run_app()
