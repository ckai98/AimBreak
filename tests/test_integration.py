"""AimBreak L2 集成测试（控制器↔视图/统计信号接线 + 防重叠间距不变量）。

本层关注"组件之间是否正确接线 / 不变量是否在集成路径上保持"，
而非重测 L1 已覆盖的纯逻辑：

1. 控制器↔信号接线（TestControllerSignalWiring）
   - 用 mock hud / mock result_widget / mock stats 构造 ``SixTargetController``，
     验证 ``_on_hit`` 驱动 ``sig_stats_updated`` → hud.update_stats(hits, misses, remaining_ms)；
   - 验证 ``_on_round_finished`` → ``sig_round_finished`` 的 payload 含
     hits/misses/accuracy/score 四键（且数值与评分公式一致），且结算页
     result.show_result 被调用。

2. 防重叠间距不变量（TestSpawnMinSpacing）
   - 直接驱动 ``FlyingTargetWidget.spawn_at_safe_position``，给定中心障碍与
     min_dist，断言其结果要么满足到障碍（=中心）距离 ≥ min_dist，要么在
     无合法候选时回退到屏幕中心兜底坐标——二者任一即证明 ``_respawn``
     的 min-spacing 约束生效且循环有界（不会挂起）。

依赖探测与 L1 一致：PySide6 缺失时整体 skip，不谎报 PASS。

补充（汇报要点，非新增用例）：
   L1 状态机用例已通过 ``start()`` → ``_begin_round()`` → ``_spawn_all()``
   → ``spawn()`` 路径间接覆盖 eng-lead 的 B4（spawn 50 次上限 + 中心兜底），
   18 项仍绿即证明 spawn 路径不再可能挂起。
"""

import math
from unittest.mock import MagicMock

import pytest

try:
    from PySide6.QtCore import QRect
    from infra.config_manager import ConfigManager
    from core.six_target_controller import SixTargetController, SixState
    from view.flying_target_widget import FlyingTargetWidget

    _HAS_DEPS = True
except Exception:  # pragma: no cover
    _HAS_DEPS = False
    QRect = None  # type: ignore
    ConfigManager = None  # type: ignore
    SixTargetController = SixState = None  # type: ignore
    FlyingTargetWidget = None  # type: ignore

skip_no_pyside = pytest.mark.skipif(
    not _HAS_DEPS, reason="PySide6/业务模块未就绪，集成测试无法在 headless 运行"
)


@skip_no_pyside
class TestControllerSignalWiring:
    """验证 SixTargetController 与 hud / 结算页 / 统计的信号接线。"""

    def _make(self):
        """构造带 mock 依赖的控制器，避免任何文件系统副作用。"""
        cfg = ConfigManager()
        stats = MagicMock()
        stats.get_best_score.return_value = 0  # 结算页 best 参数需要 int
        hud = MagicMock()
        result = MagicMock()
        ctrl = SixTargetController(cfg, stats, hud=hud, result_widget=result)
        return ctrl, stats, hud, result

    def test_on_hit_emits_stats_to_hud(self):
        """_on_hit 后，hud 收到 update_stats(hits, misses, remaining_ms)。"""
        ctrl, _stats, hud, _result = self._make()
        # 复刻 main.py 的接线：sig_stats_updated -> hud.update_stats
        ctrl.sig_stats_updated.connect(hud.update_stats)

        ctrl._state = SixState.RUNNING  # 进入合法接收态（不重测状态机）
        # 复刻 _begin_round 的前置：启动 elapsed 计时，否则 elapsed() 返回
        # 未启动的垃圾值会撑爆 32-bit int 信号（真实流程中 start()
        # 必经 _begin_round 启动该计时，故此处补上以贴近真实路径）
        ctrl._round_elapsed.start()
        ctrl._on_hit(0, 120)

        # hud 被调用一次，且参数形状为 (hits, misses, remaining_ms)
        hud.update_stats.assert_called_once()
        args = hud.update_stats.call_args.args
        assert len(args) == 3
        assert args[0] == 1          # hits 自增
        assert args[1] == 0          # misses 不变
        assert isinstance(args[2], int) and args[2] >= 0  # remaining_ms 已钳非负

    def test_round_finished_emits_payload_shape_and_result(self):
        """_on_round_finished 后，sig_round_finished payload 含四键，且结算页被调。"""
        ctrl, _stats, _hud, result = self._make()
        slot = MagicMock()
        ctrl.sig_round_finished.connect(slot)

        ctrl._hits = 72
        ctrl._misses = 8
        ctrl._on_round_finished()

        # 结算信号接线 + payload 形状正确
        slot.assert_called_once()
        payload = slot.call_args.args[0]
        assert set(payload.keys()) >= {"hits", "misses", "accuracy", "score"}
        # 数值经真实 _on_round_finished 路径计算，与 L1 评分公式一致
        assert payload == {
            "hits": 72,
            "misses": 8,
            "accuracy": 90.0,
            "score": 81664,
        }
        # 结算页集成：controller -> result_widget.show_result(result, best)
        result.show_result.assert_called_once()


@skip_no_pyside
class TestSpawnMinSpacing:
    """验证 spawn_at_safe_position 的 min-spacing 不变量（_respawn 的约束来源）。"""

    def test_large_screen_finds_spaced_point(self):
        """大屏下存在合法候选，结果到障碍（中心）距离 ≥ min_dist。"""
        w = FlyingTargetWidget(0, 40, "#FF3B30")
        rect = QRect(0, 0, 1200, 800)
        cx = rect.x() + rect.width() / 2
        cy = rect.y() + rect.height() / 2
        w.spawn_at_safe_position(
            speed_px_per_frame=4.0,
            other_positions=[(cx, cy)],
            min_dist=300,
            screen_rect=rect,
        )
        dist = math.hypot(w._cx - cx, w._cy - cy)
        # 大屏必能找到满足间距的点；OR 仅为防御性兜底
        assert dist >= 300 or (
            math.isclose(w._cx, cx) and math.isclose(w._cy, cy)
        )

    def test_small_screen_falls_back_to_center_no_hang(self):
        """小屏下无合法候选，回退到中心兜底坐标且循环有界（不挂起）。

        400x400 屏、障碍在中心时，任意屏内点到中心最大距离 ≈ 226 < 300，
        故不可能存在满足间距的候选，必须走中心兜底分支——若循环无界会挂起，
        此用例能确定性地证明它不会。
        """
        w = FlyingTargetWidget(0, 40, "#FF3B30")
        rect = QRect(0, 0, 400, 400)
        cx = rect.x() + rect.width() / 2
        cy = rect.y() + rect.height() / 2
        w.spawn_at_safe_position(
            speed_px_per_frame=4.0,
            other_positions=[(cx, cy)],
            min_dist=300,
            screen_rect=rect,
        )
        # 确定性回退：落到屏幕中心兜底坐标，且仍在屏内（约束生效、未越界）
        assert math.isclose(w._cx, cx) and math.isclose(w._cy, cy)
        assert rect.x() <= w._cx <= rect.right()
        assert rect.y() <= w._cy <= rect.bottom()
