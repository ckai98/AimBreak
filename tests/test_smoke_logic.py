"""AimBreak 垂直切片逻辑层冒烟测试。

覆盖四块可在无头/无显示器环境下验证的核心逻辑（无需真实 GUI 渲染）：

1. ConfigManager（infra/config_manager.py）
   - 10 个默认值齐全且类型正确
   - v3 六目标/多屏配置项（six_target_duration_ms / six_target_min_spacing_px /
     active_screen_index）可读写
2. StatsRepository（infra/stats_repository.py）
   - JSON 读写、命中/未命中聚合、平均反应时间（仅命中样本）、跨实例持久化
3. SixTargetStatsRepository（infra/six_target_stats_repository.py）
   - record_six 聚合、update_best_score / get_best_score（仅更高分覆盖）
4. SixTargetController 状态机（core/six_target_controller.py）
   - 合法转换 IDLE→RUNNING→PAUSED→RUNNING→(FINISHED)
   - 非法操作防护（非对应状态调用 pause/resume/start 静默不改变状态）
   - 评分公式：base=hits*1000, miss_penalty=misses*200,
     acc_mult=0.8+(acc/100)*0.4, score=max(0,(base-miss_penalty)*acc_mult)
     例：72 命中 / 8 未命中 = 90% 准确率 → (72000-1600)*1.16 = 81664

PySide6 缺失时，所有依赖 GUI 的用例（状态机/评分）自动 skip，
纯逻辑仓库用例同样需要 PySide6.QtCore，故整体 skip，不谎报 PASS。
"""

import pytest

# ---- 依赖探测：PySide6 / 业务模块不可用时整体 skip，避免收集错误 ----
try:
    from infra.config_manager import ConfigManager
    from infra.stats_repository import StatsRepository
    from infra.six_target_stats_repository import SixTargetStatsRepository
    from core.six_target_controller import SixTargetController, SixState
    from PySide6.QtCore import QSettings

    _HAS_DEPS = True
except Exception:  # pragma: no cover
    _HAS_DEPS = False
    ConfigManager = StatsRepository = None  # type: ignore
    SixTargetStatsRepository = SixTargetController = SixState = None  # type: ignore
    QSettings = None  # type: ignore

skip_no_pyside = pytest.mark.skipif(
    not _HAS_DEPS, reason="PySide6/业务模块未就绪，逻辑测试无法在 headless 运行"
)


def isolate_stats_repo(repo, tmp_path):
    """将统计仓库的读写路径重定向到临时目录，确保测试完全隔离。

    StatsRepository / SixTargetStatsRepository 在 __init__ 时即基于 QStandardPaths
    确定 ``_file_path``。测试构造实例后覆盖该实例属性，即可让后续 record / load /
    save 全部落在 tmp_path，不触碰真实 AppData。
    """
    repo._data_dir = str(tmp_path)
    repo._file_path = str(tmp_path / "stats.json")
    return repo


# ======================================================================
# 1. ConfigManager
# ======================================================================

@skip_no_pyside
class TestConfigManager:
    @pytest.fixture(autouse=True)
    def _clean_settings(self):
        """每个用例前清空 QSettings（临时 INI），防止写入串扰默认值断言。"""
        QSettings().clear()
        yield
        QSettings().clear()

    def test_defaults_complete_and_typed(self):
        """10 个默认值齐全，且 get() 返回与声明一致的强类型值。"""
        cfg = ConfigManager()
        expected = {
            "min_interval_ms": 5000,
            "max_interval_ms": 30000,
            "target_size_px": 30,
            "target_color_hex": "#FF3B30",
            "target_lifetime_ms": 2000,
            "six_target_speed": 4,
            "six_target_size_px": 50,
            "six_target_min_spacing_px": 150,
            "six_target_duration_ms": 60000,
            "active_screen_index": 0,
        }
        assert set(cfg._DEFAULTS.keys()) == set(expected.keys())
        for key, val in expected.items():
            assert cfg.get(key) == val, f"默认值不符: {key}"
            assert isinstance(cfg.get(key), type(val)), f"类型不符: {key}"

    def test_v3_six_target_config_readable(self):
        """v3 六目标配置项默认值可读（普通 get 与便捷属性双重校验）。"""
        cfg = ConfigManager()
        # 普通 get 接口
        assert cfg.get("six_target_duration_ms") == 60000
        assert cfg.get("six_target_min_spacing_px") == 150
        assert cfg.get("active_screen_index") == 0
        # 便捷只读属性
        assert cfg.six_target_duration_ms == 60000
        assert cfg.six_target_min_spacing_px == 150
        assert cfg.active_screen_index == 0

    def test_v3_config_writable(self):
        """v3 配置项可被 set 并回读（验证读写闭环）。"""
        cfg = ConfigManager()
        # 六目标时长：60s -> 120s
        cfg.set("six_target_duration_ms", 120000)
        assert cfg.get("six_target_duration_ms") == 120000
        assert cfg.six_target_duration_ms == 120000
        # 最小间距：150 -> 200
        cfg.set("six_target_min_spacing_px", 200)
        assert cfg.get("six_target_min_spacing_px") == 200
        assert cfg.six_target_min_spacing_px == 200
        # 多屏索引：0 -> 2（使用属性 setter）
        cfg.active_screen_index = 2
        assert cfg.active_screen_index == 2
        assert cfg.get("active_screen_index") == 2

    def test_basic_config_roundtrip(self):
        """普通配置项读写闭环（最小触发间隔）。"""
        cfg = ConfigManager()
        cfg.set("min_interval_ms", 1000)
        assert cfg.get("min_interval_ms") == 1000
        assert cfg.min_interval_ms == 1000


# ======================================================================
# 2. StatsRepository（普通模式）
# ======================================================================

@skip_no_pyside
class TestStatsRepository:
    def test_empty_then_record(self, tmp_path):
        """初始无记录返回 None；记录命中后聚合正确。"""
        repo = isolate_stats_repo(StatsRepository(), tmp_path)
        assert repo.get_today_stats() is None

        repo.record(hit=True, reaction_ms=500)
        s = repo.get_today_stats()
        assert s["total_shots"] == 1
        assert s["hits"] == 1
        assert s["misses"] == 0
        assert s["avg_reaction_ms"] == 500

    def test_avg_reaction_only_on_hits(self, tmp_path):
        """平均反应时间仅纳入命中样本，且为正确加权均值。"""
        repo = isolate_stats_repo(StatsRepository(), tmp_path)
        repo.record(hit=True, reaction_ms=500)
        repo.record(hit=True, reaction_ms=700)
        repo.record(hit=False, reaction_ms=0)  # 未命中不计入平均
        s = repo.get_today_stats()
        assert s["total_shots"] == 3
        assert s["hits"] == 2
        assert s["misses"] == 1
        assert s["avg_reaction_ms"] == 600  # (500+700)/2

    def test_persistence_across_instances(self, tmp_path):
        """JSON 落盘后，新实例能读回同一份当日聚合。"""
        repo = isolate_stats_repo(StatsRepository(), tmp_path)
        repo.record(hit=True, reaction_ms=500)
        repo.record(hit=True, reaction_ms=700)

        repo2 = isolate_stats_repo(StatsRepository(), tmp_path)
        s = repo2.get_today_stats()
        assert s is not None
        assert s["total_shots"] == 2
        assert s["avg_reaction_ms"] == 600


# ======================================================================
# 3. SixTargetStatsRepository（六目标模式）
# ======================================================================

@skip_no_pyside
class TestSixTargetStatsRepository:
    def test_record_six_aggregation(self, tmp_path):
        """record_six 命中/未命中聚合与平均反应时间正确。"""
        repo = isolate_stats_repo(SixTargetStatsRepository(), tmp_path)
        repo.record_six(hit=True, reaction_ms=400)
        repo.record_six(hit=True, reaction_ms=600)
        repo.record_six(hit=False, reaction_ms=0)
        s = repo.get_today_stats()
        assert s["total_shots"] == 3
        assert s["hits"] == 2
        assert s["misses"] == 1
        assert s["avg_reaction_ms"] == 500  # (400+600)/2

    def test_best_score_only_higher_overwrites(self, tmp_path):
        """历史最高分：仅当更高分时更新，低分忽略。"""
        repo = isolate_stats_repo(SixTargetStatsRepository(), tmp_path)
        assert repo.get_best_score() == 0  # 无记录返回 0
        repo.update_best_score(1000)
        assert repo.get_best_score() == 1000
        repo.update_best_score(500)   # 更低，忽略
        assert repo.get_best_score() == 1000
        repo.update_best_score(2000)  # 更高，覆盖
        assert repo.get_best_score() == 2000

    def test_best_score_persistence(self, tmp_path):
        """最高分落盘后新实例可读回。"""
        repo = isolate_stats_repo(SixTargetStatsRepository(), tmp_path)
        repo.update_best_score(1500)
        repo2 = isolate_stats_repo(SixTargetStatsRepository(), tmp_path)
        assert repo2.get_best_score() == 1500


# ======================================================================
# 4. SixTargetController 状态机 + 评分公式
# ======================================================================

@pytest.fixture
def six_controller(tmp_path):
    """构造一个六目标控制器，统计落盘隔离到 tmp_path，结束时清场回 IDLE。"""
    cfg = ConfigManager()
    stats = SixTargetStatsRepository()
    isolate_stats_repo(stats, tmp_path)
    ctrl = SixTargetController(cfg, stats)
    yield ctrl
    # 清理：停止所有定时器、销毁目标窗口，回到 IDLE，防止悬挂定时器
    try:
        ctrl.request_quit()
    except Exception:
        pass


@skip_no_pyside
class TestSixTargetStateMachine:
    def test_initial_state_is_idle(self, six_controller):
        assert six_controller.state == SixState.IDLE

    def test_happy_path_idle_running_paused_resume_finished(self, six_controller):
        """合法转换：start→(RUNNING)→pause→(PAUSED)→resume→(RUNNING)→quit→(IDLE)。

        无 CountdownWidget 时 start() 直接 _begin_round 进入 RUNNING。
        """
        ctrl = six_controller
        ctrl.start()
        assert ctrl.state == SixState.RUNNING

        ctrl.pause()
        assert ctrl.state == SixState.PAUSED

        ctrl.resume()
        assert ctrl.state == SixState.RUNNING

        ctrl.request_quit()
        assert ctrl.state == SixState.IDLE

    def test_illegal_ops_are_noops_without_exception(self, six_controller):
        """非法操作防护：非对应状态下调用 pause/resume/start 静默 return，
        既不抛异常，也不改变状态。"""
        ctrl = six_controller
        # IDLE 下调用 pause / resume 应无效
        ctrl.pause()
        assert ctrl.state == SixState.IDLE
        ctrl.resume()
        assert ctrl.state == SixState.IDLE

        # 进入 RUNNING
        ctrl.start()
        assert ctrl.state == SixState.RUNNING

        # RUNNING 下重复 start 无效（仅 IDLE 可启动）
        ctrl.start()
        assert ctrl.state == SixState.RUNNING

        # 进入 PAUSED
        ctrl.pause()
        assert ctrl.state == SixState.PAUSED

        # PAUSED 下重复 pause 无效
        ctrl.pause()
        assert ctrl.state == SixState.PAUSED

        # 回到 RUNNING
        ctrl.resume()
        assert ctrl.state == SixState.RUNNING

        # RUNNING 下重复 resume 无效
        ctrl.resume()
        assert ctrl.state == SixState.RUNNING

    def test_restart_after_quit(self, six_controller):
        """request_quit 回 IDLE 后，可再次 start 开新一局。"""
        ctrl = six_controller
        ctrl.start()
        assert ctrl.state == SixState.RUNNING
        ctrl.request_quit()
        assert ctrl.state == SixState.IDLE
        ctrl.start()  # 二次启动
        assert ctrl.state == SixState.RUNNING


@skip_no_pyside
class TestSixTargetScoring:
    def _finish_with(self, six_controller, hits, misses):
        """设定 hits/misses 后直接驱动结算，捕获 sig_round_finished 回报。"""
        ctrl = six_controller
        captured = {}
        ctrl.sig_round_finished.connect(lambda r: captured.update(r))
        ctrl._hits = hits
        ctrl._misses = misses
        ctrl._on_round_finished()
        return captured

    def test_reference_case_72hits_8misses(self, six_controller):
        """官方参考用例：72 命中 / 8 未命中 = 90% 准确率 → 81664 分。"""
        r = self._finish_with(six_controller, 72, 8)
        assert r["hits"] == 72
        assert r["misses"] == 8
        assert r["accuracy"] == 90.0
        assert r["score"] == 81664
        # 最高分应被记录
        assert six_controller._stats.get_best_score() == 81664

    def test_all_hit_full_accuracy(self, six_controller):
        """全命中：50 命中 / 0 未命中 = 100% 准确率。"""
        r = self._finish_with(six_controller, 50, 0)
        assert r["accuracy"] == 100.0
        # (50*1000 - 0) * (0.8 + 1.0*0.4) = 50000 * 1.2 = 60000
        assert r["score"] == 60000

    def test_all_miss_clamped_to_zero(self, six_controller):
        """全未命中：0 命中 / 100 未命中 → 分数被 max(0,...) 钳为 0。"""
        r = self._finish_with(six_controller, 0, 100)
        assert r["accuracy"] == 0.0
        assert r["score"] == 0

    def test_partial_accuracy_formula(self, six_controller):
        """部分命中：30 命中 / 10 未命中 = 75% 准确率。
        (30000 - 2000) * (0.8 + 0.75*0.4) = 28000 * 1.1 = 30800。"""
        r = self._finish_with(six_controller, 30, 10)
        assert r["accuracy"] == 75.0
        assert r["score"] == 30800
