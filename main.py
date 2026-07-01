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
from view.hud_widget import HudWidget
from view.miss_detector_widget import MissDetectorWidget
from view.result_widget import ResultWidget
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
    hud = HudWidget()
    miss_detector = MissDetectorWidget()
    result_widget = ResultWidget()

    # 5. 创建控制层
    scheduler = Scheduler()
    controller = GameController(config, stats, scheduler, target)
    six_controller = SixTargetController(
        config, six_stats,
        hud=hud, miss_detector=miss_detector, result_widget=result_widget,
    )

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
    # 六目标轮次结束 -> 刷新统计（结算页由 controller._on_round_finished 内部弹出）
    six_controller.sig_round_finished.connect(lambda _r: tray.refresh_six_stats())
    # HUD 实时刷新：controller 每 100ms emit (hits, misses, remaining_ms)
    six_controller.sig_stats_updated.connect(hud.update_stats)
    # 结算页关闭：回到 IDLE，允许后续 start（controller 仍在 FINISHED，
    # 调 request_quit 回 IDLE 干净状态）
    result_widget.sig_closed.connect(six_controller.request_quit)

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

    # 难度设置对话框（Task 13）：配置六目标难度参数，下一局开始时生效
    def show_settings_dialog():
        from PySide6.QtWidgets import (
            QDialog, QFormLayout, QSpinBox, QDialogButtonBox, QMessageBox,
        )
        dlg = QDialog()
        dlg.setWindowTitle("六目标难度设置")
        form = QFormLayout(dlg)

        size_box = QSpinBox()
        size_box.setRange(20, 120)
        size_box.setValue(config.six_target_size_px)
        size_box.setSuffix(" px")

        duration_box = QSpinBox()
        duration_box.setRange(10, 300)
        duration_box.setValue(config.six_target_duration_ms // 1000)
        duration_box.setSuffix(" 秒")

        spacing_box = QSpinBox()
        spacing_box.setRange(0, 500)
        spacing_box.setValue(config.six_target_min_spacing_px)
        spacing_box.setSuffix(" px")

        form.addRow("球径:", size_box)
        form.addRow("单局时长:", duration_box)
        form.addRow("最小间距:", spacing_box)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        form.addRow(buttons)

        if dlg.exec() == QDialog.Accepted:
            config.set("six_target_size_px", size_box.value())
            config.set("six_target_duration_ms", duration_box.value() * 1000)
            config.set("six_target_min_spacing_px", spacing_box.value())
            QMessageBox.information(dlg, "已保存", "设置已保存，下一局开始时生效。")

    tray.sig_settings_clicked.connect(show_settings_dialog)

    # 7. 显示托盘并启动状态机
    tray.show()
    controller.start()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
