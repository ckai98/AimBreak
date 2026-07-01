"""系统托盘视图入口：管理托盘图标与右键菜单。

严格职责：仅作为视图层入口，不持有任何业务逻辑。
点击菜单只发信号，由 GameController 接收并处理状态切换。
"""
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QIcon, QPixmap, QColor, QPainter, QAction
from PySide6.QtWidgets import QSystemTrayIcon, QMenu


class TrayManager(QObject):
    """系统托盘视图入口：仅管理托盘图标与菜单，点击菜单仅发信号，不持有业务逻辑。"""

    # 菜单信号（由 GameController 接收处理）
    sig_pause_clicked = Signal()
    sig_resume_clicked = Signal()
    sig_quit_clicked = Signal()
    sig_mode_switch = Signal(str)   # "classic" | "six_target"
    sig_settings_clicked = Signal()  # 难度设置入口，由 main.py 监听后弹出对话框

    def __init__(self, stats_repo, six_stats_repo=None, parent=None):
        """
        Args:
            stats_repo: StatsRepository 实例，用于读取当日统计。
            six_stats_repo: SixTargetStatsRepository 实例，用于读取六目标当日统计（可选）。
            parent: 父 QObject。
        """
        super().__init__(parent)
        self._stats = stats_repo
        self._six_stats = six_stats_repo
        self._current_mode = "classic"

        self._tray = QSystemTrayIcon(self._make_default_icon(), parent)
        self._tray.setToolTip("办公室反应训练器")

        self._menu = QMenu()
        self._build_menu()
        self._tray.setContextMenu(self._menu)

    # ---------- 对外接口 ----------

    def show(self):
        """显示托盘图标。"""
        self._tray.show()

    def refresh_state(self, state):
        """根据当前游戏状态刷新菜单项的可用性。

        不 import GameState 以避免循环依赖，采用 state.name 字符串比较。

        Args:
            state: GameState 枚举值；传入 None 时按“非暂停”处理。
        """
        # 暂停在 IDLE/WAITING 可用；恢复在 PAUSED 可用
        is_paused = (state is not None and getattr(state, "name", None) == "PAUSED")
        self._act_pause.setEnabled(not is_paused)
        self._act_resume.setEnabled(is_paused)

    def refresh_today_stats(self):
        """刷新菜单底部的当日统计文本。

        无记录或零射击时显示“暂无”；否则显示 命中数/总数 与平均反应时间。
        """
        stats = self._stats.get_today_stats()
        if stats is None or stats.get("total_shots", 0) == 0:
            text = "今日: 暂无"
        else:
            text = (
                f"今日: 命中 {stats['hits']}/{stats['total_shots']}"
                f"，平均 {stats['avg_reaction_ms']}ms"
            )
        self._act_stats.setText(text)

    def refresh_six_stats(self):
        """刷新六目标当日统计文本。

        无记录或零射击时显示“暂无”；否则显示 命中数/总数、平均反应时间与最高分。
        跨日全局历史最高分通过 self._six_stats.get_best_score() 获取。
        """
        if self._six_stats is None:
            return
        stats = self._six_stats.get_today_stats()
        best = self._six_stats.get_best_score()
        if stats is None or stats.get("total_shots", 0) == 0:
            text = "六目标今日: 暂无"
            if best > 0:
                text = f"六目标今日: 暂无（最高 {best}）"
        else:
            text = (
                f"六目标今日: 命中 {stats['hits']}/{stats['total_shots']}"
                f"，平均 {stats['avg_reaction_ms']}ms，最高 {best}"
            )
        self._act_six_stats.setText(text)

    # ---------- 内部实现 ----------

    def _build_menu(self):
        """构建右键菜单：暂停 / 恢复 / 分隔 / 今日统计 / 六目标统计 / 分隔 / 训练模式 / 难度设置... / 分隔 / 退出。"""
        self._act_pause = QAction("暂停", self._menu)
        self._act_resume = QAction("恢复", self._menu)
        self._act_quit = QAction("退出", self._menu)
        self._act_stats = QAction("今日: 暂无", self._menu)
        self._act_stats.setEnabled(False)  # 统计项仅展示，不可点击
        self._act_six_stats = QAction("六目标今日: 暂无", self._menu)
        self._act_six_stats.setEnabled(False)  # 统计项仅展示，不可点击
        self._act_settings = QAction("难度设置...", self._menu)

        # 菜单点击仅发信号，业务逻辑由 GameController 处理
        self._act_pause.triggered.connect(self.sig_pause_clicked.emit)
        self._act_resume.triggered.connect(self.sig_resume_clicked.emit)
        self._act_quit.triggered.connect(self.sig_quit_clicked.emit)
        self._act_settings.triggered.connect(self.sig_settings_clicked.emit)

        self._menu.addAction(self._act_pause)
        self._menu.addAction(self._act_resume)
        self._menu.addSeparator()
        self._menu.addAction(self._act_stats)
        self._menu.addAction(self._act_six_stats)
        self._menu.addSeparator()
        mode_menu = self._menu.addMenu("训练模式")
        self._act_mode_classic = QAction("✓ 普通模式", mode_menu)
        self._act_mode_six = QAction("  六目标模式", mode_menu)
        self._act_mode_classic.triggered.connect(lambda: self._switch_mode("classic"))
        self._act_mode_six.triggered.connect(lambda: self._switch_mode("six_target"))
        mode_menu.addAction(self._act_mode_classic)
        mode_menu.addAction(self._act_mode_six)
        self._menu.addAction(self._act_settings)
        self._menu.addSeparator()
        self._menu.addAction(self._act_quit)

        # 初始刷新统计
        self.refresh_today_stats()
        self.refresh_six_stats()

    def _switch_mode(self, mode: str):
        """切换训练模式，更新菜单勾选文本并发送信号。"""
        self._current_mode = mode
        self._act_mode_classic.setText("✓ 普通模式" if mode == "classic" else "  普通模式")
        self._act_mode_six.setText("✓ 六目标模式" if mode == "six_target" else "  六目标模式")
        self.sig_mode_switch.emit(mode)

    def _make_default_icon(self) -> QIcon:
        """生成默认托盘图标（16x16 红色实心圆）。

        MVP 阶段不依赖外部图标文件，避免资源打包复杂度。
        后续 PyInstaller 打包阶段可替换为正式 .ico。
        """
        pix = QPixmap(16, 16)
        pix.fill(QColor(0, 0, 0, 0))  # 透明背景
        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(QColor("#FF3B30"))
        p.setPen(QColor(255, 255, 255))
        p.drawEllipse(1, 1, 14, 14)
        p.end()
        return QIcon(pix)
