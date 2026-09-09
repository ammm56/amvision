"""只在 HTTP 服务使用的 Windows accept 适配。

IOCP 注册和 SO_UPDATE_ACCEPT_CONTEXT 顺序遵循 CPython 3.12
Lib/asyncio/windows_events.py（PSF License）。不修改标准库或全局 loop policy。
"""

from __future__ import annotations

import asyncio
import socket
import struct
import sys


SUPPORTED_PYTHON = (3, 12)
"""私有 IOCP 接口已经过回归的 Python 主次版本。"""


if sys.platform == "win32":
    import _overlapped
    from asyncio.windows_events import IocpProactor

    class HttpProactor(IocpProactor):
        """为每个监听维持一个可取消的 accept，隔离 WinError 64。"""

        def _accept_once(self, listener):
            """返回单次 IOCP future 和尚未交付的连接；同步失败也关闭连接。"""
            self._register_with_iocp(listener)
            conn = self._get_accept_socket(listener.family)
            try:
                overlapped = _overlapped.Overlapped(0)
                overlapped.AcceptEx(listener.fileno(), conn.fileno())

                def finish_accept(_transferred, _key, operation):
                    """只有成功 completion 才读取并交付有效连接。"""
                    operation.getresult()
                    conn.setsockopt(
                        socket.SOL_SOCKET,
                        _overlapped.SO_UPDATE_ACCEPT_CONTEXT,
                        struct.pack("@P", listener.fileno()),
                    )
                    conn.settimeout(listener.gettimeout())
                    return conn, conn.getpeername()

                return self._register(overlapped, listener, finish_accept), conn
            except BaseException:
                conn.close()
                raise

        def accept(self, listener):
            """对标准事件循环提供一个结果 future，不产生无人消费的旁路 Task。"""
            return self._loop.create_task(self._accept_connection(listener))

        async def _accept_connection(self, listener):
            """释放失败连接后有界退避；取消和未知错误保持原语义。"""
            failures = 0
            while True:
                conn = None
                try:
                    if listener.fileno() == -1:
                        raise asyncio.CancelledError
                    completion, conn = self._accept_once(listener)
                    result = await completion
                    if listener.fileno() == -1:
                        raise asyncio.CancelledError
                    return result
                except BaseException as error:
                    if conn is not None:
                        conn.close()
                    if not isinstance(error, OSError) or getattr(error, "winerror", None) != 64:
                        raise
                    failures += 1
                    delay = 0 if failures < 8 else min(0.1, 0.001 * 2 ** min(7, failures - 8))
                    await asyncio.sleep(delay)


def create_loop() -> asyncio.AbstractEventLoop:
    """构造服务专用循环；未经验证的 Windows Python 组合显式拒绝。"""
    if sys.platform != "win32":
        return asyncio.new_event_loop()
    if sys.version_info[:2] != SUPPORTED_PYTHON:
        raise RuntimeError("Windows HTTP accept 适配尚未验证此 Python 版本，需要更新发行兼容性矩阵")
    return asyncio.ProactorEventLoop(HttpProactor())
