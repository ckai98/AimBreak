"""办公室反应训练器 - 入口

启动流程：
    高 DPI 预设置 -> 单实例检测 -> QApplication -> 创建各模块 -> 连接信号 -> 启动状态机
"""
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

from core.game_controller import GameController
from core.scheduler import Scheduler
from core.six_target_controller import SixTargetController
from infra.config_manager import ConfigManager
from infra.six_target_stats_repository import SixTargetStatsRepository
from infra.stats_repository import StatsRepository
from infra.win_helper import WinHelper
from view.target_widget import TargetWidget
from view.tray_manager import TrayManager


def main() -> int:
    # 1. 高 DPI 缩放预设置（必须在创建 QApplication 之前）
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("OfficeAimTrainer")
    app.setOrganizationName("OfficeAimTrainer")
    app.setQuitOnLastWindowClosed(False)  # 托盘应用：关闭窗口不退出

    # 2. 单实例检测：已有实例运行则直接退出
    if not WinHelper.ensure_single_instance():
        print("已有实例运行，退出。")
        return 0

    # 3. 创建基础设施层
    config = ConfigManager()
    stats = StatsRepository()
    six_stats = SixTargetStatsRepository()

    # 4. 创建视图层
    target = TargetWidget()
    tray = TrayManager(stats, six_stats)

    # 5. 创建控制层
    scheduler = Scheduler()
    controller = GameController(config, stats, scheduler, target)
    six_controller = SixTargetController(config, six_stats)

    # 6. 连接信号
    # 托盘菜单 -> 控制器状态切换
    tray.sig_pause_clicked.connect(controller.pause)
    tray.sig_resume_clicked.connect(controller.resume)
    tray.sig_quit_clicked.connect(controller.request_quit)
    tray.sig_quit_clicked.connect(six_controller.request_quit)
    tray.sig_quit_clicked.connect(app.quit)

    # 控制器状态变更 -> 托盘刷新菜单可用性与当日统计文本
    # （RESULT 为瞬态，记录发生在进入 RESULT 时；状态变更后刷新统计可读到最新数据）
    controller.sig_state_changed.connect(tray.refresh_state)
    controller.sig_state_changed.connect(lambda _state: tray.refresh_today_stats())

    # 六目标状态变更 -> 托盘刷新菜单 + 统计
    six_controller.sig_state_changed.connect(tray.refresh_state)
    six_controller.sig_state_changed.connect(lambda _s: tray.refresh_six_stats())
    # 六目标轮次结束 -> 刷新统计
    six_controller.sig_round_finished.connect(lambda _r: tray.refresh_six_stats())

    # 模式切换：用列表包裹便于闭包修改
    _active_mode = ["classic"]

    def on_mode_switch(mode: str):
        if mode == _active_mode[0]:
            return
        # 停旧模式：request_quit 清场后回 IDLE（两种控制器均如此），任意状态可停
        if _active_mode[0] == "classic":
            controller.request_quit()
        else:
            six_controller.request_quit()
        _active_mode[0] = mode
        # 启动新模式
        if mode == "classic":
            controller.start()  # IDLE 状态可启动
        else:
            six_controller.start()  # IDLE 状态可启动
        # 切换后刷新托盘菜单可用性 + 统计
        if mode == "classic":
            tray.refresh_state(controller.state)
            tray.refresh_today_stats()
        else:
            tray.refresh_state(six_controller.state)
            tray.refresh_six_stats()

    tray.sig_mode_switch.connect(on_mode_switch)

    # 7. 显示托盘并启动状态机
    tray.show()
    controller.start()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
