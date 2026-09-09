"""Windows HTTP accept 故障、真实连接和取消回归。"""

from __future__ import annotations

import asyncio
import os
import socket
import sys

import pytest


pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows IOCP 回归")


@pytest.mark.parametrize("loop_factory,proactor_name", [
    ("backend.service.infrastructure.http.windows_event_loop:create_loop", "HttpProactor"),
    ("reload_probe:stock_loop", "IocpProactor"),
])
@pytest.mark.skipif(os.environ.get("AMVISION_TEST_CONSOLE_RELOAD") != "1",
    reason="真实 reload 需要可交付 CTRL_C_EVENT 的独立 Windows 控制台；设置 AMVISION_TEST_CONSOLE_RELOAD=1 后执行")
def test_uvicorn_reload_keeps_custom_proactor(tmp_path, loop_factory, proactor_name):
    """真实 reload 子进程重建后仍采用项目 Proactor；仅运行隔离 ASGI 应用。"""
    import http.client
    import json
    import os
    from pathlib import Path
    import subprocess
    import time
    import psutil

    application = tmp_path / "reload_probe.py"
    source = '''import asyncio, ctypes, json, os
# 隐藏进程启动可能继承 CTRL_C 忽略状态，测试子进程显式恢复常规控制台语义。
ctypes.windll.kernel32.SetConsoleCtrlHandler(None, False)
MARKER = "before"
def stock_loop():
    return asyncio.ProactorEventLoop()
async def app(scope, receive, send):
    if scope["type"] != "http": return
    loop = asyncio.get_running_loop()
    body = json.dumps({"pid": os.getpid(), "proactor": type(loop._proactor).__name__, "marker": MARKER}).encode()
    await send({"type":"http.response.start", "status":200, "headers":[(b"content-length", str(len(body)).encode())]})
    await send({"type":"http.response.body", "body":body})
'''
    application.write_text(source, encoding="utf-8")
    with socket.socket() as available:
        available.bind(("127.0.0.1", 0))
        port = available.getsockname()[1]
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])}
    # Uvicorn reload 使用 CTRL_C_EVENT；独立隐藏控制台防止测试信号传播到宿主。
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = subprocess.SW_HIDE
    process = subprocess.Popen([sys.executable, "-m", "uvicorn", "reload_probe:app",
        "--host", "127.0.0.1", "--port", str(port), "--reload", "--reload-dir", str(tmp_path),
        "--loop", loop_factory, "--lifespan", "off"],
        cwd=tmp_path, env=env,
        creationflags=subprocess.CREATE_NEW_CONSOLE, startupinfo=startup)
    def wait_for(marker):
        """只接受本轮加载的代码标识，并限定启动/重载等待。"""
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            assert process.poll() is None
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=.5)
            try:
                connection.request("GET", "/")
                result = json.loads(connection.getresponse().read())
                if result["marker"] == marker:
                    assert result["proactor"] == proactor_name
                    return result
            except (OSError, http.client.HTTPException):
                pass
            finally:
                connection.close()
            time.sleep(.2)
        raise TimeoutError("Uvicorn reload 未就绪")
    try:
        before = wait_for("before")
        # 等待文件监听线程注册，避免把尚未被观察到的写入当作 reload 故障。
        time.sleep(1)
        application.write_text(source.replace('"before"', '"after-change"'), encoding="utf-8")
        after = wait_for("after-change")
        assert before["pid"] != after["pid"]
    finally:
        root = psutil.Process(process.pid)
        owned = [*root.children(recursive=True), root]
        for item in reversed(owned):
            try:
                item.terminate()
            except psutil.NoSuchProcess:
                pass
        _, alive = psutil.wait_procs(owned, timeout=5)
        assert not alive
        process.wait(timeout=5)


def test_stock_loop_closes_listener_on_winerror64() -> None:
    """固定现场故障：单连接错误关闭监听，但 loop 仍存活。"""
    loop = asyncio.ProactorEventLoop()
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    listener.setblocking(False)
    errors = []
    loop.set_exception_handler(lambda _, context: errors.append(context["message"]))

    def fail_accept(_listener):
        """只在隔离 loop 中注入已确认的系统错误。"""
        future = loop.create_future()
        future.set_exception(OSError(22, "injected", None, 64))
        return future

    loop._proactor.accept = fail_accept
    try:
        loop._start_serving(asyncio.Protocol, listener)
        loop.call_later(0.02, loop.stop)
        loop.run_forever()
        assert listener.fileno() == -1
        assert not loop.is_closed()
        assert errors == ["Accept failed on a socket"]
    finally:
        listener.close()
        loop.close()


@pytest.mark.parametrize("failures", [1, 12])
def test_recovered_accept_serves_real_connection(monkeypatch, failures: int) -> None:
    """失败连接全部释放，同一监听随后仍可完成真实收发。"""
    from backend.service.infrastructure.http.windows_event_loop import create_loop

    loop = create_loop()
    proactor = loop._proactor
    original = proactor._accept_once
    discarded = []
    errors = []
    loop.set_exception_handler(lambda _, context: errors.append(context))

    def accept_once(listener):
        """先提供错误 completion，再使用真实 IOCP。"""
        if len(discarded) < failures:
            conn = socket.socket()
            discarded.append(conn)
            future = loop.create_future()
            future.set_exception(OSError(22, "injected", None, 64))
            return future, conn
        return original(listener)

    monkeypatch.setattr(proactor, "_accept_once", accept_once)

    class Echo(asyncio.Protocol):
        """最小真实连接处理器。"""

        def connection_made(self, transport):
            """登记连接。"""
            self.transport = transport

        def data_received(self, data):
            """回复并关闭连接。"""
            self.transport.write(data)
            self.transport.close()

    async def exercise():
        """建立两次连接，核对监听持续有效。"""
        server = await loop.create_server(Echo, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        try:
            for _ in range(2):
                reader, writer = await asyncio.open_connection("127.0.0.1", port)
                writer.write(b"healthy")
                await writer.drain()
                assert await asyncio.wait_for(reader.readexactly(7), 2) == b"healthy"
                writer.close()
                await writer.wait_closed()
            assert server.is_serving()
            assert all(conn.fileno() == -1 for conn in discarded)
        finally:
            server.close()
            await server.wait_closed()
            await asyncio.sleep(0.02)

    try:
        loop.run_until_complete(exercise())
        assert not errors
    finally:
        loop.close()


@pytest.mark.parametrize("cancel", [False, True])
def test_accept_error_and_cancel_release_socket(monkeypatch, cancel: bool) -> None:
    """未知错误向上传递；取消不能泄漏连接或重新 accept。"""
    from backend.service.infrastructure.http.windows_event_loop import create_loop

    loop = create_loop()
    listener = socket.socket()
    conn = socket.socket()
    completion = loop.create_future()
    calls = []

    def accept_once(_listener):
        """模拟未完成或未知错误 completion。"""
        calls.append(1)
        return completion, conn

    monkeypatch.setattr(loop._proactor, "_accept_once", accept_once)

    async def exercise():
        """在 accept 已挂起后触发错误或取消。"""
        task = loop._proactor.accept(listener)
        await asyncio.sleep(0)
        if cancel:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert completion.cancelled()
        else:
            completion.set_exception(OSError(22, "unknown", None, 5))
            with pytest.raises(OSError) as error:
                await task
            assert error.value.winerror == 5
        assert conn.fileno() == -1
        assert len(calls) == 1

    try:
        loop.run_until_complete(exercise())
    finally:
        conn.close()
        listener.close()
        loop.close()


def test_real_uvicorn_http_and_websocket_survive_accept_errors(monkeypatch):
    """实际 Uvicorn、短连接、长 WebSocket 共享同一修复循环。"""
    import json
    import uvicorn
    from websockets.asyncio.client import connect
    from backend.service.infrastructure.http.windows_event_loop import create_loop

    loop = create_loop()
    discarded, errors = [], []
    loop.set_exception_handler(lambda _, context: errors.append(context))
    original = loop._proactor._accept_once
    inject = [False]

    def accept_once(listener):
        """只在下一次新连接开始时注入已确认错误。"""
        if inject[0]:
            inject[0] = False
            future = loop.create_future()
            future.set_exception(OSError(22, "injected", None, 64))
            conn = socket.socket()
            discarded.append(conn)
            return future, conn
        return original(listener)

    monkeypatch.setattr(loop._proactor, "_accept_once", accept_once)

    async def app(scope, receive, send):
        """隔离 ASGI 业务，不引入数据库或真实业务副作用。"""
        if scope["type"] == "websocket":
            await receive()
            await send({"type": "websocket.accept"})
            while True:
                message = await receive()
                if message["type"] == "websocket.disconnect":
                    return
                await send({"type": "websocket.send", "text": message["text"]})
        else:
            body = json.dumps({"loop": type(asyncio.get_running_loop()).__name__}).encode()
            await send({"type": "http.response.start", "status": 200, "headers": [(b"content-length", str(len(body)).encode())]})
            await send({"type": "http.response.body", "body": body})

    async def exercise():
        """在 WebSocket 保持连接时穿插 100 次新 HTTP 连接和故障。"""
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        server = uvicorn.Server(uvicorn.Config(app, lifespan="off", access_log=False, log_level="error"))
        task = asyncio.create_task(server.serve(sockets=[listener]))
        try:
            for _ in range(100):
                if server.started:
                    break
                await asyncio.sleep(.01)
            port = listener.getsockname()[1]
            async with connect(f"ws://127.0.0.1:{port}") as ws:
                for index in range(100):
                    inject[0] = index % 10 == 0
                    reader, writer = await asyncio.open_connection("127.0.0.1", port)
                    writer.write(b"GET / HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n")
                    await writer.drain()
                    response = await asyncio.wait_for(reader.read(), 2)
                    assert b"200 OK" in response and b"ProactorEventLoop" in response
                    writer.close()
                    await writer.wait_closed()
                    await ws.send(str(index))
                    assert await ws.recv() == str(index)
            assert len(discarded) == 10
            assert all(conn.fileno() == -1 for conn in discarded)
        finally:
            server.should_exit = True
            await asyncio.wait_for(task, 5)
            listener.close()

    try:
        loop.run_until_complete(exercise())
        assert not errors
    finally:
        loop.close()
