"""Preview 会话唯一发送协程：状态优先，图片使用有 ACK 的有界二进制窗口。"""

import asyncio
from collections import deque
import json
from time import monotonic
from uuid import UUID

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.contracts.workflows.preview_session import PreviewInputBegin, PREVIEW_CHUNK_SIZE, decode_preview_frame, encode_preview_frame
from backend.service.application.workflows.preview.session import PreviewSessionError

preview_sessions_ws_router = APIRouter()


@preview_sessions_ws_router.websocket("/workflows/preview-sessions/{session_id}")
async def stream_session(socket: WebSocket, session_id: str):
    """订阅快照与 live 原子衔接；断线不重放业务，不使用事件文件。"""
    from backend.service.api.ws.v1.router import _get_socket_principal, _scope_granted
    # 浏览器只能在握手后接收到应用关闭码；握手前关闭会变成不透明的 1006。
    await socket.accept()
    principal = _get_socket_principal(socket)
    if principal is None or not _scope_granted(principal.scopes, "workflows:read"):
        await socket.close(code=4401 if principal is None else 4403)
        return
    manager = socket.app.state.workflow_preview_sessions
    try:
        manager.authorize(session_id, principal.principal_id, principal.project_ids)
        subscription, snapshot = manager.subscribe(session_id, principal.principal_id)
    except PreviewSessionError:
        await socket.close(code=4404, reason="preview_session_expired")
        return
    uploads = {}
    transfers = deque()
    receiving = None

    async def send(message):
        """慢客户端的发送有期限，不占用 Worker 控制线程。"""
        await asyncio.wait_for(socket.send_json(message), timeout=5)

    def finish_transfer(transfer):
        """先归还 view 再释放 pin，连接取消与正常结束共用同一释放路径。"""
        transfer["borrow"].__exit__(None, None, None)

    try:
        await send(snapshot)
        heartbeat = monotonic()
        receiving = asyncio.create_task(socket.receive())
        while not subscription.closed:
            if subscription.overflowed:
                await socket.close(code=1013, reason="preview_snapshot_required")
                return
            for _ in range(16):
                event = manager.take(subscription)
                if event is None:
                    break
                await send(event)
            if receiving.done():
                incoming = receiving.result()
                if incoming["type"] == "websocket.disconnect":
                    return
                error_context = {}
                try:
                    binary = incoming.get("bytes")
                    if binary is not None:
                        if not _scope_granted(principal.scopes, "workflows:write"):
                            raise ValueError("permission_denied")
                        transfer_id, index, content = decode_preview_frame(binary, expected_kind=1)
                        error_context = {"request_type": "input.chunk", "transfer_id": str(transfer_id), "chunk_index": index}
                        try:
                            blob = uploads[str(transfer_id)]
                            manager.buffers.write_chunk(session_id, blob, index, content)
                        finally:
                            content.release()
                        await send({"type": "input.ack", "transfer_id": str(transfer_id), "chunk_index": index})
                    else:
                        raw = incoming.get("text", "")
                        if len(raw.encode()) > 64 * 1024:
                            raise ValueError("preview_control_capacity")
                        command = json.loads(raw)
                        if not isinstance(command, dict):
                            raise ValueError("preview_command_invalid")
                        error_context = {"request_type": command.get("type"), **{key: command[key] for key in ("blob_id", "transfer_id", "request_id") if key in command}}
                        kind = command.get("type")
                        if kind == "input.begin":
                            if not _scope_granted(principal.scopes, "workflows:write"):
                                raise ValueError("permission_denied")
                            body = PreviewInputBegin.model_validate(command)
                            transfer_id = str(body.transfer_id)
                            if transfer_id in uploads or len(uploads) >= 4:
                                raise ValueError("preview_upload_capacity")
                            blob = await asyncio.to_thread(manager.buffers.allocate, session_id, body.byte_length,
                                                           media_type=body.media_type, digest=body.sha256, file_name=body.file_name)
                            uploads[transfer_id] = blob
                            await send({"type": "input.ready", "transfer_id": transfer_id})
                        elif kind == "input.commit":
                            transfer_id = str(UUID(command["transfer_id"]))
                            result = await asyncio.to_thread(manager.buffers.commit, session_id, uploads[transfer_id])
                            uploads.pop(transfer_id)
                            await send({"type": "input.committed", "transfer_id": transfer_id, "input_id": result["blob_id"], **result})
                        elif kind == "display.get":
                            if len(transfers) >= 4:
                                raise ValueError("preview_transfer_capacity")
                            blob = UUID(command["blob_id"]).hex
                            if any(item["blob_id"] == blob for item in transfers):
                                raise ValueError("preview_transfer_active")
                            borrow = manager.buffers.borrow(session_id, blob)
                            view = borrow.__enter__()
                            transfer = {"blob_id": blob, "borrow": borrow, "view": view, "sent": 0, "acked": 0, "touched": monotonic()}
                            transfers.append(transfer)
                            await send({"type": "display.begin", "blob_id": blob, "byte_length": len(view)})
                        elif kind == "resource.received":
                            blob = UUID(command["blob_id"]).hex
                            manager.received_blob(session_id, subscription, blob, command.get("receipt"))
                        elif kind == "display.ack":
                            blob = UUID(command["blob_id"]).hex
                            transfer = next(item for item in transfers if item["blob_id"] == blob)
                            index = command["chunk_index"]
                            if type(index) is not int:
                                raise ValueError("preview_ack_invalid")
                            acked = index + 1
                            if not transfer["acked"] <= acked <= transfer["sent"]:
                                raise ValueError("preview_ack_invalid")
                            transfer["acked"], transfer["touched"] = acked, monotonic()
                        elif kind != "session.pong":
                            raise ValueError("preview_command_invalid")
                except (ValueError, KeyError, TypeError, IndexError, AttributeError, StopIteration) as error:
                    await send({"type": "protocol.error", "error": str(error)[:512], **error_context})
                receiving = asyncio.create_task(socket.receive())
            outstanding = sum(item["sent"] - item["acked"] for item in transfers)
            for transfer in list(transfers):
                if monotonic() - transfer["touched"] >= 15:
                    raise TimeoutError("preview_transfer_ack_timeout")
                offset = transfer["sent"] * PREVIEW_CHUNK_SIZE
                if offset >= len(transfer["view"]) and transfer["acked"] == transfer["sent"]:
                    receipt = manager.issue_receipt(session_id, transfer["blob_id"])
                    await send({"type": "display.end", "blob_id": transfer["blob_id"], "receipt": receipt})
                    finish_transfer(transfer)
                    transfers.remove(transfer)
                elif outstanding < 4 and offset < len(transfer["view"]):
                    frame = encode_preview_frame(UUID(transfer["blob_id"]), transfer["sent"], bytes(transfer["view"][offset:offset + PREVIEW_CHUNK_SIZE]), kind=2)
                    await asyncio.wait_for(socket.send_bytes(frame), timeout=5)
                    transfer["sent"] += 1
                    outstanding += 1
            if monotonic() - heartbeat >= 15:
                await send({"type": "session.ping"})
                heartbeat = monotonic()
            if not receiving.done():
                await asyncio.wait({receiving}, timeout=.01)
    except WebSocketDisconnect:
        pass
    except (TimeoutError, RuntimeError):
        try:
            await socket.close(code=1013, reason="preview_connection_interrupted")
        except RuntimeError:
            pass
    finally:
        if receiving is not None:
            receiving.cancel()
            await asyncio.gather(receiving, return_exceptions=True)
        for transfer in transfers:
            finish_transfer(transfer)
        for blob in uploads.values():
            manager.buffers.release(session_id, blob)
        manager.unsubscribe(session_id, subscription)
