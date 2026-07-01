from PySide6.QtNetwork import QLocalSocket, QLocalServer


class WinHelper:
    """系统 API 封装：单实例检测等。"""

    # 持有 QLocalServer 引用，防止被 GC 回收导致锁失效
    _lock_server = None

    @staticmethod
    def ensure_single_instance(app_name: str = "OfficeAimTrainer_Lock") -> bool:
        """
        检测单实例。若已有实例运行返回 False，否则占用锁并返回 True。
        通过 QLocalServer 名字锁实现：尝试连接，连得上说明已有实例。
        """
        socket = QLocalSocket()
        socket.connectToServer(app_name)
        if socket.waitForConnected(300):
            socket.close()
            return False  # 已有实例运行
        # 清理可能残留的服务器名，然后创建新锁
        QLocalServer.removeServer(app_name)
        server = QLocalServer()
        server.listen(app_name)
        # 注意：server 需要保持引用，否则会被 GC 回收导致锁失效
        # 将其挂到静态属性上保持生命周期
        WinHelper._lock_server = server
        return True  # 允许启动
