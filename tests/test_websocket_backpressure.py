"""固定 WS 后端在发送背压与心跳并发时仍保持协议可用。"""

import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

from uvicorn import Config
from uvicorn.server import ServerState
from uvicorn.protocols.websockets.wsproto_impl import WSProtocol
from wsproto import ConnectionType, WSConnection
from wsproto.events import AcceptConnection, CloseConnection, Ping, Request
from wsproto.extensions import PerMessageDeflate


def test_data_send_waits_for_transport_while_ping_keeps_protocol_valid():
    """客户端请求压缩也不协商；暂停发送时心跳不争用单个 drain waiter。"""
    async def scenario():
        accepted = asyncio.Event()
        finished = asyncio.Event()

        async def app(scope, receive, send):
            assert (await receive())["type"] == "websocket.connect"
            await send({"type": "websocket.accept"})
            accepted.set()
            await finished.wait()

        protocol = WSProtocol(Config(app, ws="wsproto", ws_per_message_deflate=False, lifespan="off"), ServerState(), {})
        transport = Mock()
        transport.is_closing.return_value = False
        transport.get_extra_info.return_value = None
        output = bytearray()
        transport.write.side_effect = output.extend
        protocol.connection_made(transport)
        client = WSConnection(ConnectionType.CLIENT)
        protocol.data_received(client.send(Request(host="localhost", target="/", extensions=[PerMessageDeflate()])))
        await asyncio.wait_for(accepted.wait(), 1)
        client.receive_data(bytes(output))
        output.clear()
        response = next(client.events())
        assert isinstance(response, AcceptConnection)
        assert response.extensions == []
        protocol.pause_writing()
        sending = asyncio.create_task(protocol.send({"type": "websocket.send", "bytes": b"image-data"}))
        await asyncio.sleep(0)
        assert not sending.done()
        protocol.send_keepalive_ping()
        client.receive_data(bytes(output))
        output.clear()
        ping = next(client.events())
        assert isinstance(ping, Ping)
        protocol.data_received(client.send(ping.response()))
        protocol.resume_writing()
        await asyncio.wait_for(sending, 1)
        client.receive_data(bytes(output))
        assert next(client.events()).data == b"image-data"
        protocol.stop_keepalive()
        tasks = tuple(protocol.tasks)
        finished.set()
        await asyncio.gather(*tasks)
        protocol.connection_lost(None)
        assert not protocol.connections

    asyncio.run(scenario())


def test_runtime_preview_client_close_releases_subscription_without_asgi_error(monkeypatch, caplog):
    """真实 wsproto 关闭握手后，路由二次 close 不得泄漏订阅或冒出 ASGI 异常。"""
    from starlette.websockets import WebSocket
    from backend.service.api.ws.v1 import router

    async def scenario():
        channel = Mock()

        async def receive_frame():
            await asyncio.Event().wait()

        subscription = SimpleNamespace(receive=receive_frame)
        channel.subscribe.return_value = subscription
        monkeypatch.setattr(router, '_get_socket_principal', lambda _: SimpleNamespace(scopes=('*',), project_ids=()))
        monkeypatch.setattr(router, '_build_socket_workflow_runtime_service', lambda _: Mock())
        monkeypatch.setattr(router, '_get_socket_workflow_runtime_worker_manager', lambda _: SimpleNamespace(get_preview_channel=lambda *args, **kwargs: channel))
        for _ in range(20):
            connected = asyncio.Event()

            async def app(scope, receive, send):
                async def tracked_send(message):
                    await send(message)
                    if message['type'] == 'websocket.send':
                        connected.set()
                await router.subscribe_runtime_preview(WebSocket(scope, receive, tracked_send))

            protocol = WSProtocol(Config(app, ws='wsproto', ws_per_message_deflate=False, lifespan='off'), ServerState(), {})
            transport = Mock()
            transport.is_closing.return_value = False
            transport.get_extra_info.return_value = None
            output = bytearray()
            transport.write.side_effect = output.extend
            protocol.connection_made(transport)
            client = WSConnection(ConnectionType.CLIENT)
            protocol.data_received(client.send(Request(host='localhost', target='/?workflow_runtime_id=r&workflow_runtime_revision_id=v&runtime_generation=1&worker_instance_id=w')))
            await asyncio.wait_for(connected.wait(), 2)
            client.receive_data(bytes(output))
            assert any(isinstance(event, AcceptConnection) for event in client.events())
            tasks = tuple(protocol.tasks)
            protocol.data_received(client.send(CloseConnection(code=1000)))
            await asyncio.wait_for(asyncio.gather(*tasks), 2)
            protocol.connection_lost(None)
            assert not protocol.connections
        assert channel.unsubscribe.call_count == 20
        assert not [record for record in caplog.records if record.levelno >= 40]

    asyncio.run(scenario())
