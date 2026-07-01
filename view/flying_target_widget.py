"""
FlyingTargetWidget —— 带飞行动画的目标小球
========================================

职责：
    1. 从屏幕边缘随机出生，朝屏幕中心匀速飞行
    2. 复用 TargetWidget 的 QRegion 椭圆蒙版穿透方案
       （小球可点击、透明区穿透）
    3. 命中上报反应时间；飞抵中心点上报 arrived

技术原理：
    - WA_TranslucentBackground：让整个窗口视觉透明（含 alpha 通道）
    - setMask(QRegion.Ellipse)：用蒙版裁剪窗口的"可命中区域"，
      蒙版外的鼠标事件不会派发给本窗口，而是穿透到下层窗口。
    - QTimer 周期触发 _tick，按 _vx/_vy 推进 _cx/_cy

本模块仅负责绘制与事件捕获，业务逻辑由 GameController 处理。
"""

from PySide6.QtCore import Qt, Signal, QTimer, QElapsedTimer
from PySide6.QtGui import QPainter, QColor, QRegion, QPen
from PySide6.QtWidgets import QWidget
from PySide6.QtGui import QGuiApplication
import random
import math

# 距中心多少像素算"到达"
ARRIVAL_RADIUS_PX = 25
# 每帧间隔（~60fps）
FRAME_MS = 16


class FlyingTargetWidget(QWidget):
    """飞行目标小球窗口：透明绘制 + 椭圆蒙版命中裁剪 + 逐帧位移。"""

    # 命中：上报 (target_id, reaction_ms)
    sig_hit = Signal(int, int)
    # 到达中心：上报 (target_id,)
    sig_arrived = Signal(int)

    def __init__(self, target_id: int, size: int = 40, color_hex: str = "#FF3B30"):
        super().__init__()

        # 业务标识
        self._target_id = target_id

        # 视觉与尺寸参数
        self._size = size
        self._color = QColor(color_hex)

        # 浮点球心坐标（屏幕坐标系）与每帧速度
        self._cx: float = 0.0
        self._cy: float = 0.0
        self._vx: float = 0.0
        self._vy: float = 0.0

        # 反应时间计时器：从 spawn 起计时，命中时读取 elapsed
        self._elapsed = QElapsedTimer()

        # 防重入标志：命中后忽略后续点击，避免重复 emit
        self._hit: bool = False

        # 缓存屏幕中心点（_tick 中不再每帧查询 primaryScreen）
        self._screen_cx: int = 0
        self._screen_cy: int = 0

        # 1. 无边框 + 置顶 + Tool 类型（不显示在任务栏）
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
        )

        # 2. 全窗口透明（视觉透明由 paintEvent 自绘内容决定）
        self.setAttribute(Qt.WA_TranslucentBackground)

        # 3. 逐帧推进计时器
        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(FRAME_MS)
        self._tick_timer.timeout.connect(self._tick)

        # 注意：不在构造函数里 show()，显示由 spawn 触发

    def spawn(self, speed_px_per_frame: float = 4.0):
        """从屏幕边缘随机出生，朝屏幕中心方向飞行。

        Args:
            speed_px_per_frame: 每帧位移像素数（约等于 px/16ms）
        """
        screen = QGuiApplication.primaryScreen().availableGeometry()

        # 缓存屏幕中心点，供 _tick 使用
        self._screen_cx = int(screen.x() + screen.width() / 2)
        self._screen_cy = int(screen.y() + screen.height() / 2)

        # 随机选一条边出生
        edge = random.randint(0, 3)
        if edge == 0:
            # 上边
            self._cx = float(random.uniform(screen.x(), screen.right()))
            self._cy = float(screen.y())
        elif edge == 1:
            # 下边
            self._cx = float(random.uniform(screen.x(), screen.right()))
            self._cy = float(screen.bottom())
        elif edge == 2:
            # 左边
            self._cx = float(screen.x())
            self._cy = float(random.uniform(screen.y(), screen.bottom()))
        else:
            # 右边
            self._cx = float(screen.right())
            self._cy = float(random.uniform(screen.y(), screen.bottom()))

        # 朝中心方向单位向量
        dx = self._screen_cx - self._cx
        dy = self._screen_cy - self._cy
        dist = math.hypot(dx, dy) or 1.0
        self._vx = dx / dist * speed_px_per_frame
        self._vy = dy / dist * speed_px_per_frame

        # 重置防重入标志
        self._hit = False

        self._place()
        self.show()
        self._elapsed.start()
        self._tick_timer.start()

    def despawn(self):
        """停止飞行并隐藏（供 Controller 清场使用）。

        clearMask() 在 hide() 之后调用，确保透明区恢复穿透。
        """
        self._tick_timer.stop()
        self.hide()
        self.clearMask()

    def _tick(self):
        """逐帧推进球心坐标，检测是否到达中心点。

        使用缓存的 self._screen_cx / _screen_cy，避免每帧查询 primaryScreen。
        """
        self._cx += self._vx
        self._cy += self._vy
        self._place()

        dist = math.hypot(
            self._cx - self._screen_cx,
            self._cy - self._screen_cy,
        )
        if dist < ARRIVAL_RADIUS_PX:
            # 到达中心：停 timer、隐藏、清蒙版、上报 arrived
            self._tick_timer.stop()
            self.hide()
            self.clearMask()
            self.sig_arrived.emit(self._target_id)

    def _place(self):
        """根据浮点球心坐标放置窗口并刷新椭圆蒙版。"""
        x = int(self._cx - self._size / 2)
        y = int(self._cy - self._size / 2)
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
        self._tick_timer.stop()
        self.hide()
        self.clearMask()
        self.sig_hit.emit(self._target_id, reaction_ms)
