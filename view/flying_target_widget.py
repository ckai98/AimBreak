"""
FlyingTargetWidget —— 静止目标小球（对齐 Aim Lab 六目标模式）
========================================

职责：
    1. 全屏高斯分布静态出生（不飞行）
    2. 复用 TargetWidget 的 QRegion 椭圆蒙版穿透方案
       （小球可点击、透明区穿透）
    3. 命中上报反应时间

技术原理：
    - WA_TranslucentBackground：让整个窗口视觉透明（含 alpha 通道）
    - setMask(QRegion.Ellipse)：用蒙版裁剪窗口的"可命中区域"，
      蒙版外的鼠标事件不会派发给本窗口，而是穿透到下层窗口。
    - 目标静止，无需逐帧 timer 推进

本模块仅负责绘制与事件捕获，业务逻辑由 GameController 处理。
"""

from PySide6.QtCore import Qt, Signal, QElapsedTimer
from PySide6.QtGui import QPainter, QColor, QRegion, QPen
from PySide6.QtWidgets import QWidget
from PySide6.QtGui import QGuiApplication
import random
import math


class FlyingTargetWidget(QWidget):
    """静止目标小球窗口：透明绘制 + 椭圆蒙版命中裁剪 + 全屏高斯出生。"""

    # 命中：上报 (target_id, reaction_ms)
    sig_hit = Signal(int, int)

    def __init__(self, target_id: int, size: int = 40, color_hex: str = "#FF3B30"):
        super().__init__()

        # 业务标识
        self._target_id = target_id

        # 视觉与尺寸参数
        self._size = size
        self._color = QColor(color_hex)

        # 浮点球心坐标（屏幕坐标系）；静止目标速度恒为 0
        self._cx: float = 0.0
        self._cy: float = 0.0
        self._vx: float = 0.0
        self._vy: float = 0.0

        # 反应时间计时器：从 spawn 起计时，命中时读取 elapsed
        self._elapsed = QElapsedTimer()

        # 防重入标志：命中后忽略后续点击，避免重复 emit
        self._hit: bool = False

        # 1. 无边框 + 置顶 + Tool 类型（不显示在任务栏）
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
        )

        # 2. 全窗口透明（视觉透明由 paintEvent 自绘内容决定）
        self.setAttribute(Qt.WA_TranslucentBackground)

        # 注意：不在构造函数里 show()，显示由 spawn 触发

    def spawn(self, speed_px_per_frame: float = 4.0):
        """全屏高斯分布静态出生（不飞行）。

        speed_px_per_frame 参数保留以兼容 Controller 调用签名，当前不使用。
        """
        screen = QGuiApplication.primaryScreen().availableGeometry()
        cx = screen.x() + screen.width() / 2
        cy = screen.y() + screen.height() / 2
        sigma_x = screen.width() * 0.28
        sigma_y = screen.height() * 0.28
        margin = self._size
        while True:
            x = random.gauss(cx, sigma_x)
            y = random.gauss(cy, sigma_y)
            if (screen.x() + margin < x < screen.right() - margin and
                    screen.y() + margin < y < screen.bottom() - margin):
                break
        self._cx, self._cy = x, y
        self._vx, self._vy = 0.0, 0.0   # 静止，不飞行
        self._hit = False
        self._place()
        self.show()
        self._elapsed.start()

    def spawn_at_safe_position(self, speed_px_per_frame: float, other_positions, min_dist: float):
        """带防重叠的最小间距出生。在高斯采样循环中加碰撞检查。

        Args:
            speed_px_per_frame: 保留兼容，不使用。
            other_positions: 其他目标的 [(cx, cy), ...] 列表。
            min_dist: 与其他目标的最小间距（像素）。
        """
        screen = QGuiApplication.primaryScreen().availableGeometry()
        cx = screen.x() + screen.width() / 2
        cy = screen.y() + screen.height() / 2
        sigma_x = screen.width() * 0.28
        sigma_y = screen.height() * 0.28
        margin = self._size
        max_attempts = 50
        # 兜底初始化为屏幕中心，避免循环内无合法候选时 best_x 为 None 导致崩溃
        best_x, best_y = cx, cy
        for attempt in range(max_attempts):
            x = random.gauss(cx, sigma_x)
            y = random.gauss(cy, sigma_y)
            if not (screen.x() + margin < x < screen.right() - margin and
                    screen.y() + margin < y < screen.bottom() - margin):
                continue
            # 碰撞检查：距所有 other_positions 均 >= min_dist
            ok = True
            for (ox, oy) in other_positions:
                if math.hypot(x - ox, y - oy) < min_dist:
                    ok = False
                    break
            if ok:
                best_x, best_y = x, y
                break
            # 记录第一个合法边界内的候选，作为兜底
            if best_x is None:
                best_x, best_y = x, y
        # 超限放宽约束：使用兜底候选（保证不死循环）
        self._cx, self._cy = best_x, best_y
        self._vx, self._vy = 0.0, 0.0
        self._hit = False
        self._place()
        self.show()
        self._elapsed.start()

    def despawn(self):
        """停止显示并隐藏（供 Controller 清场使用）。

        clearMask() 在 hide() 之后调用，确保透明区恢复穿透。
        """
        self.hide()
        self.clearMask()

    def _place(self):
        """根据浮点球心坐标放置窗口并刷新椭圆蒙版。"""
        x = int(self._cx - self._size / 2)
        y = int(self._cy - self._size / 2)
        self.setGeometry(x, y, self._size, self._size)
        self.setMask(QRegion(0, 0, self._size, self._size, QRegion.Ellipse))

    def move_to_render_pos(self, view_dx: float, view_dy: float):
        """按视角偏移把球重新定位到渲染位置（视角瞄准模式 v2）。

        渲染球心 = (self._cx + view_dx, self._cy + view_dy)。
        注意：本方法只负责渲染定位，绝不写入 self._cx / self._cy，
        逻辑坐标保持不变，由 ViewportController 每 tick 调用。
        """
        # 渲染球心 = 逻辑球心 + 视角偏移
        render_cx = self._cx + view_dx
        render_cy = self._cy + view_dy
        # 窗口左上角 = 渲染球心 - 半边长
        x = int(render_cx - self._size / 2)
        y = int(render_cy - self._size / 2)
        self.setGeometry(x, y, self._size, self._size)
        self.setMask(QRegion(0, 0, self._size, self._size, QRegion.Ellipse))

    def paintEvent(self, event):
        """绘制椭圆小球：配置颜色填充 + 白色描边。"""
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(self._color)
        p.setPen(QPen(QColor(255, 255, 255), 2))
        p.drawEllipse(0, 0, self._size, self._size)

    def mousePressEvent(self, event):
        """点击小球：防重入后计算反应时间并上报命中，然后隐藏。

        clearMask() 在 hide() 之后调用，确保透明区恢复穿透。
        """
        # 防重入：已命中则忽略后续点击
        if self._hit:
            return
        self._hit = True

        reaction_ms = int(self._elapsed.elapsed())
        self.hide()
        self.clearMask()
        self.sig_hit.emit(self._target_id, reaction_ms)
