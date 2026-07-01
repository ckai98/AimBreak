from PySide6.QtCore import QSettings


class ConfigManager:
    """配置管理器：封装 QSettings，提供 5 项配置的读写与默认值。"""

    # 5 项配置的默认值（键名 -> 默认值）
    _DEFAULTS = {
        "min_interval_ms": 5000,      # 最小触发间隔（毫秒）
        "max_interval_ms": 30000,     # 最大触发间隔（毫秒）
        "target_size_px": 30,         # 小球直径（像素）
        "target_color_hex": "#FF3B30",  # 小球颜色（十六进制）
        "target_lifetime_ms": 2000,   # 小球存活时间（毫秒）
    }

    def __init__(self):
        # QSettings 依赖 QApplication 的 applicationName / organizationName
        # 在 main.py 中已设置，这里直接使用默认构造
        self._settings = QSettings()

    def get(self, key: str):
        """读取配置，不存在则返回默认值。

        根据 _DEFAULTS 中默认值的类型进行强转，确保返回类型一致
        （QSettings 在某些后端默认会返回 str）。
        """
        default = self._DEFAULTS.get(key)
        if default is None:
            # 非已知键，回退为字符串读取
            return self._settings.value(key, "", str)
        expected_type = type(default)
        value = self._settings.value(key, default, expected_type)
        # int 类型二次包裹，防止部分后端返回字符串
        if expected_type is int:
            return int(value)
        return value

    def set(self, key: str, value):
        """写入配置（MVP 暂无配置界面，预留写入入口）。"""
        self._settings.setValue(key, value)

    # ---------- 便捷只读属性 ----------

    @property
    def min_interval_ms(self) -> int:
        """最小触发间隔（毫秒）"""
        return int(self._settings.value(
            "min_interval_ms", self._DEFAULTS["min_interval_ms"]))

    @property
    def max_interval_ms(self) -> int:
        """最大触发间隔（毫秒）"""
        return int(self._settings.value(
            "max_interval_ms", self._DEFAULTS["max_interval_ms"]))

    @property
    def target_size_px(self) -> int:
        """小球直径（像素）"""
        return int(self._settings.value(
            "target_size_px", self._DEFAULTS["target_size_px"]))

    @property
    def target_color_hex(self) -> str:
        """小球颜色（十六进制字符串）"""
        return self._settings.value(
            "target_color_hex", self._DEFAULTS["target_color_hex"])

    @property
    def target_lifetime_ms(self) -> int:
        """小球存活时间（毫秒）"""
        return int(self._settings.value(
            "target_lifetime_ms", self._DEFAULTS["target_lifetime_ms"]))
