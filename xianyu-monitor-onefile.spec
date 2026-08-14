# -*- mode: python ; coding: utf-8 -*-
"""
闲鱼智能监控机器人 - 单文件打包配置
打包命令（在项目根目录执行）:
    .venv-build\\Scripts\\pyinstaller.exe xianyu-monitor-onefile.spec --noconfirm --clean --distpath dist-onefile

说明:
  - onefile 模式：产物为单个 xianyu-monitor.exe，可直接发给他人使用。
  - 前端构建产物 dist/ 与 static/ 打进包内，运行期从解压目录读取（见 src/app.py 的 _resource_root）。
  - Playwright 浏览器体积过大不打包；运行时优先系统 Chrome，缺失时自动回退到系统 Edge
    （Win10/11 自带），若把 browsers/ 目录放到 exe 同级也可用内置浏览器。
  - 运行数据（jsonl/logs/images/data/state/prompts）由 desktop_launcher 在 exe 旁自动创建，
    prompts 参考文件首次启动时从包内复制到 exe 旁，src/app.py 启动时也会兜底补齐。
"""
from PyInstaller.utils.hooks import collect_all, collect_submodules

import os


def _add_tree_datas(root_dir: str, dest_prefix: str, exclude_dirs: tuple = ()) -> None:
    """把目录下的文件作为标准 datas (源文件, 目标目录) 追加。

    datas 的第二个元素是“目标目录”，打包时会把源文件的文件名自动追加到该目录下，
    因此需按文件所在子目录分别指定目标目录，以保留目录结构。
    """
    for cur, dirs, files in os.walk(root_dir):
        # 剪枝：不进入被排除的目录（如根 dist 下的打包输出目录，体积很大）
        dirs[:] = [d for d in dirs if os.path.join(cur, d) not in exclude_dirs and d not in exclude_dirs]
        rel_dir = os.path.relpath(cur, root_dir)
        dest = dest_prefix if rel_dir == "." else os.path.join(dest_prefix, rel_dir)
        for f in files:
            datas.append((os.path.join(cur, f), dest))

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

# 前端构建产物与旧静态资源打进包内（排除打包输出目录本身）
_add_tree_datas("dist", "dist", exclude_dirs=("xianyu-monitor",))
_add_tree_datas("static", "static")
# prompts 参考文件（如 macbook_criteria.txt）随包分发，首次启动时由 desktop_launcher 复制到 exe 旁
_add_tree_datas("prompts", "prompts")

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
    a.binaries,
    a.datas,
    [],
    name="xianyu-monitor",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # 无控制台窗口（GUI 形式启动）
    disable_windowed_traceback=False,
)
