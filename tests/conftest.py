"""AimBreak 测试框架脚手架 (pytest)。

关键设计：
1. 必须在导入任何 PySide6 模块 *之前* 设置 ``QT_QPA_PLATFORM=offscreen``，
   使所有 GUI 组件在无显示器环境下也能构造（不真正渲染）。
2. 将项目根目录加入 ``sys.path``，使 ``from infra...`` / ``from core...`` /
   ``from view...`` 的绝对导入可用。
3. 提供进程级唯一的 ``QApplication``（session 级 autouse fixture），供所有
   测试共享；PySide6 缺失时优雅降级（fixture 直接 yield，测试通过 skip 跳过）。
4. 配置持久化隔离：将 ``QSettings`` 默认格式改为 IniFormat 并落地到临时目录，
   避免 ConfigManager 的写入污染真实注册表、且避免跨用例/跨运行串扰。
"""

import os
import sys
from pathlib import Path

# ---- 1. 必须在任何 PySide6 导入前设置无头平台 ----
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# ---- 2. 项目根目录加入 sys.path ----
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest

# ---- 3. PySide6 可用性探测（缺失时整套逻辑测试优雅 skip，不报 FAIL）----
try:
    from PySide6.QtWidgets import QApplication  # noqa: F401
    _HAS_PYSIDE = True
except Exception:  # pragma: no cover - 依赖缺失分支
    _HAS_PYSIDE = False


@pytest.fixture(scope="session", autouse=True)
def qapp(tmp_path_factory):
    """进程级唯一的 QApplication（offscreen 平台），供所有测试共享。

    PySide6 缺失时直接 yield None，逻辑测试（依赖 PySide6 的部分）由
    ``skipif`` 跳过，不影响其余可运行项的收口判定。

    同时把 ``QSettings`` 默认格式重定向到本次运行的临时 INI 文件，
    避免 ConfigManager 的持久化写入污染真实注册表，也避免跨用例/
    跨运行串扰默认值断言。
    """
    if not _HAS_PYSIDE:  # pragma: no cover
        yield None
        return
    app = QApplication.instance()
    if app is None:
        # sys.argv[:1] 避免把 pytest 的命令行参数透传给 Qt
        app = QApplication(sys.argv[:1])
        app.setApplicationName("AimBreakTest")
        app.setOrganizationName("AimBreakTest")
    # 在构造任何 QSettings 之前，将默认格式改为 IniFormat 并落地到临时目录
    from PySide6.QtCore import QSettings
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    settings_dir = tmp_path_factory.mktemp("qsettings")
    QSettings.setPath(
        QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(settings_dir)
    )
    yield app
