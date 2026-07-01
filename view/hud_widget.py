"""HudWidget —— 六目标训练模式局内 HUD 悬浮层
================================================

职责：
    1. 全屏透明覆盖层，实时显示倒计时 / 命中 / 失误 / 准确率
    2. 鼠标穿透：点击事件不影响下层目标球（WindowTransparentForInput）
    3. 仅由 SixTargetController 在 RUNNING 状态下显示

技术原理：
    - WA_TranslucentBackground：让整个窗口视觉透明（含 alpha 通道）
    - WindowTransparentForInput：让鼠标事件完全穿透到下层窗口，
      与 TargetWidget 的 QRegion 蒙版方案互补——
      TargetWidget 是"局部可命中、区域外穿透"，HudWidget 是"全局不接收"。
    - availableGeometry：覆盖主屏幕可用区（排除任务栏），避免遮挡。
    - Tool 类型：不显示在任务栏。

本模块仅负责显示，业务逻辑由 SixTargetController 处理。
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QWidget, QLabel, QHBoxLayout, QVBoxLayout


class HudWidget(QWidget):
    """局内 HUD 悬浮层：全屏透明、鼠标穿透、顶部显示实时统计。"""

    def __init__(self, parent=None):
        super().__init__(parent)

        # 1. 无边框 + 置顶 + Tool（不显示在任务栏）+ 鼠标穿透
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.WindowTransparentForInput
        )

        # 2. 全窗口透明（视觉透明由 QLabel 自带样式背景决定）
        self.setAttribute(Qt.WA_TranslucentBackground)

        # 3. 四个统计标签
        self._label_timer = QLabel("60.0")
        self._label_hits = QLabel("命中: 0")
        self._label_misses = QLabel("失误: 0")
        self._label_acc = QLabel("准确: -")
        for lbl in (self._label_timer, self._label_hits, self._label_misses, self._label_acc):
            lbl.setStyleSheet(
                "color: white; background: rgba(0,0,0,140);"
                "padding: 6px 14px; border-radius: 8px;"
                "font-size: 22px; font-weight: bold;"
            )

        # 4. 横向排列四标签，右侧 addStretch 避免标签被拉伸
        row = QHBoxLayout()
        row.addWidget(self._label_timer)
        row.addWidget(self._label_hits)
        row.addWidget(self._label_misses)
        row.addWidget(self._label_acc)
        row.addStretch()

        # 5. 顶部布局：内容置顶，下方 addStretch 占满剩余空间
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 0)
        outer.addLayout(row)
        outer.addStretch()

        self._resize_to_screen()

        # 注意：不在构造函数里 show()，显示由 show_hud 触发

    def _resize_to_screen(self):
        """覆盖主屏幕 availableGeometry（排除任务栏区域）。"""
        screen = QGuiApplication.primaryScreen().availableGeometry()
        self.setGeometry(screen)

    def update_stats(self, hits: int, misses: int, remaining_ms: int):
        """刷新 HUD 文本。

        Args:
            hits: 本局命中数
            misses: 本局失误数
            remaining_ms: 本局剩余毫秒数（倒计时）
        """
        total = hits + misses
        acc = f"{hits / total * 100:.1f}%" if total > 0 else "-"
        self._label_timer.setText(f"{remaining_ms / 1000:.1f}")
        self._label_hits.setText(f"命中: {hits}")
        self._label_misses.setText(f"失误: {misses}")
        self._label_acc.setText(f"准确: {acc}")

    def show_hud(self):
        """显示 HUD：重新对齐屏幕尺寸后 show。

        show 前重新 resize 是为多显示器/分辨率变更场景兜底。
        """
        self._resize_to_screen()
        self.show()

    def hide_hud(self):
        """隐藏 HUD。"""
        self.hide()
