# -*- mode: python ; coding: utf-8 -*-
"""
闲鱼智能监控机器人 - PyInstaller 打包配置
打包命令（在项目根目录执行）:
    .venv-build\\Scripts\\pyinstaller.exe xianyu-monitor.spec --noconfirm --clean

说明:
  - 使用 onedir 模式，输出到 dist/xianyu-monitor/，整个目录即为分发包。
  - 前端产物 dist/ 与 static/ 不打包进 _internal，而是在构建后复制到 exe 同级目录
    （desktop_launcher 运行时会 chdir 到 exe 所在目录，运行数据也落在那里）。
  - Playwright 浏览器不在包内，目标机器需已存在浏览器缓存
    （首次运行可用 `playwright install chromium` 或设置 PLAYWRIGHT_BROWSERS_PATH）。
"""
from PyInstaller.utils.hooks import collect_all, collect_submodules

datas = []
binaries = []
hiddenimports = []

# 对存在动态/插件式导入的包做全量收集
for pkg in ("playwright", "uvicorn", "fastapi", "apscheduler", "openai"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# 补充动态导入/扩展模块
for pkg in (
    "websockets",
    "httptools",
    "watchfiles",
    "python_socks",
    "anyio",
    "h11",
    "sniffio",
    "httpx",
    "httpcore",
    "pydantic",
    "pydantic_settings",
    "email_validator",
):
    hiddenimports += collect_submodules(pkg)

a = Analysis(
    ["desktop_launcher.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "pytest_asyncio", "coverage", "tests", "tkinter"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="xianyu-monitor",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # 无控制台窗口（GUI 形式启动）
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="xianyu-monitor",
)
