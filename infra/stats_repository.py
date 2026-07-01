"""统计仓库：按日期聚合写入 stats.json，提供当日统计读取。"""
import json
import os
from datetime import date

from PySide6.QtCore import QStandardPaths


class StatsRepository:
    """统计仓库：按日期聚合写入 stats.json，提供当日统计读取。"""

    def __init__(self):
        # 借助 Qt 标准路径定位数据目录（Windows 下通常为
        # C:\\Users\\<User>\\AppData\\Local\\<OrgName>\\<AppName>）
        data_dir = QStandardPaths.writableLocation(QStandardPaths.AppLocalDataLocation)
        self._data_dir = data_dir
        self._file_path = os.path.join(data_dir, "stats.json")
        # 确保目录存在，exist_ok=True 避免目录已存在时抛错
        os.makedirs(data_dir, exist_ok=True)

    def record(self, hit: bool, reaction_ms: int):
        """记录一次射击。

        Args:
            hit: True 表示命中，False 表示超时未击中。
            reaction_ms: 本次反应时间（毫秒）。仅命中样本计入平均反应时间。
        """
        today = date.today().isoformat()  # "YYYY-MM-DD"
        data = self._load_all()
        entry = data.get(
            today,
            {
                "total_shots": 0,
                "hits": 0,
                "misses": 0,
                "avg_reaction_ms": 0,
            },
        )
        entry["total_shots"] += 1
        if hit:
            entry["hits"] += 1
            # 更新命中平均反应时间（仅命中样本计入）
            prev_total = entry["hits"] - 1
            prev_avg = entry["avg_reaction_ms"]
            new_avg = int((prev_avg * prev_total + reaction_ms) / entry["hits"])
            entry["avg_reaction_ms"] = new_avg
        else:
            entry["misses"] += 1
        data[today] = entry
        self._save_all(data)

    def get_today_stats(self) -> dict | None:
        """返回当日统计字典，无记录返回 None。"""
        today = date.today().isoformat()
        data = self._load_all()
        return data.get(today)

    def _load_all(self) -> dict:
        """读取全部统计数据。文件不存在或损坏时容错返回空字典。"""
        if not os.path.exists(self._file_path):
            return {}
        try:
            with open(self._file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            # 损坏的 JSON 或读写异常时，不崩溃，返回空字典
            return {}

    def _save_all(self, data: dict):
        """全量写入统计数据，使用 utf-8 编码。"""
        with open(self._file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
