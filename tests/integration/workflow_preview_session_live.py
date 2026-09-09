"""对已启动开发服务执行三分钟内的真实 Preview 验证，不保存应用或模板。

使用 conda activate amvision 后运行 python -m tests.integration.workflow_preview_session_live。
image 是业务图片，output 是明确保存节点的验证目录，report 是长期证据文件。
"""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
from time import monotonic
from uuid import uuid4

import httpx
import websockets
from backend.contracts.workflows.preview_session import encode_preview_frame, decode_preview_frame, PREVIEW_CHUNK_SIZE
from backend.service.application.auth.default_local_auth_seeder import DEFAULT_LOCAL_AUTH_USERNAME, DEFAULT_LOCAL_AUTH_PASSWORD


async def validate(args):
    """只提交隔离内存快照；追加 Delay 验证前面节点显示不等待整图结束。"""
    result = {"application_id": args.application, "delay_seconds": args.delay, "events": {}, "health": [], "errors": []}
    started = monotonic()
    sid = None
    health_task = None
    async with httpx.AsyncClient(base_url=args.base_url, timeout=15) as client:
        async def request(method, path, **kwargs):
            response = await client.request(method, path, **kwargs)
            response.raise_for_status()
            return response.json() if response.content else None

        login = await request("POST", "/api/v1/auth/login", json={"username": DEFAULT_LOCAL_AUTH_USERNAME, "password": DEFAULT_LOCAL_AUTH_PASSWORD})
        client.headers["Authorization"] = "Bearer " + login["access_token"]
        base = "/api/v1/workflows/preview-sessions"
        app = (await request("GET", f"/api/v1/workflows/projects/{args.project}/applications/{args.application}"))["application"]
        ref = app["template_ref"]
        template = (await request("GET", f"/api/v1/workflows/projects/{args.project}/templates/{ref['template_id']}/versions/{ref['template_version']}"))["template"]
        result["snapshot_sha256"] = hashlib.sha256(json.dumps({"application": app, "template": template}, sort_keys=True).encode()).hexdigest()
        app["application_id"] = "preview-probe-" + uuid4().hex
        output = template["template_outputs"][0]
        assert output["payload_type_id"] == "value.v1", "探针仅对值输出追加 Delay"
        template["nodes"].append({"node_id": "preview_probe_delay", "node_type_id": "core.logic.delay", "parameters": {"seconds": args.delay}})
        template["edges"].append({"edge_id": "preview_probe_wait", "source_node_id": output["source_node_id"], "source_port": output["source_port"], "target_node_id": "preview_probe_delay", "target_port": "value"})
        output.update(source_node_id="preview_probe_delay", source_port="value")
        identity = await request("POST", base, json={"project_id": args.project, "application_id": app["application_id"], "editor_session_id": str(uuid4())})
        sid = identity["session_id"]
        result["session_id"] = sid
        url = args.base_url.replace("http", "ws", 1) + f"/ws/v1/workflows/preview-sessions/{sid}?access_token=" + login["access_token"]

        async def health():
            """探测 HTTP 接入，不将它当作推理性能测量。"""
            import psutil
            while True:
                tick = monotonic()
                try:
                    reply = await request("GET", "/api/v1/system/liveness")
                    process = psutil.Process(reply["pid"])
                    result["health"].append({"seconds": round(tick-started, 3), "latency_ms": round((monotonic()-tick)*1000, 2),
                        "pid": reply["pid"], "phase": reply["phase"], "rss_bytes": process.memory_info().rss})
                except Exception as error:
                    result["errors"].append({"health": type(error).__name__})
                await asyncio.sleep(1)

        try:
            health_task = asyncio.create_task(health())
            async with asyncio.timeout(max(1, 180-(monotonic()-started))):
                async with websockets.connect(url, max_size=PREVIEW_CHUNK_SIZE + 65536) as ws:
                    assert json.loads(await ws.recv())["type"] == "session.snapshot"
                    content = Path(args.image).read_bytes()
                    result["input_bytes"] = len(content)
                    result["input_sha256"] = hashlib.sha256(content).hexdigest()
                    transfer = uuid4()
                    async def send(body):
                        await ws.send(json.dumps(body))
                    async def expect(kind):
                        while True:
                            reply = json.loads(await ws.recv())
                            if reply["type"] == "session.ping":
                                continue
                            assert reply["type"] == kind, reply
                            return reply
                    await send({"type": "input.begin", "transfer_id": str(transfer), "byte_length": len(content), "media_type": "image/bmp", "sha256": result["input_sha256"], "file_name": Path(args.image).name})
                    await expect("input.ready")
                    for index, offset in enumerate(range(0, len(content), PREVIEW_CHUNK_SIZE)):
                        await ws.send(encode_preview_frame(transfer, index, content[offset:offset+PREVIEW_CHUNK_SIZE], kind=1))
                        await expect("input.ack")
                    await send({"type": "input.commit", "transfer_id": str(transfer)})
                    uploaded = await expect("input.committed")
                    del content
                    accepted = await request("POST", f"{base}/{sid}/runs", json={"request_id": str(uuid4()), "document_revision": "isolated-live-probe", "application": app, "template": template,
                        "input_ids": {"request_image_ref": uploaded["input_id"]}, "input_bindings": {"request_json": {"value": {"savepath": str(Path(args.output).resolve()).replace('\\', '/'), "barqrcode": "preview-stream-validation"}}}, "timeout_seconds": 300})
                    result["run_id"] = accepted["run_id"]
                    source = None
                    image_bytes = bytearray()
                    while True:
                        raw = await ws.recv()
                        if isinstance(raw, bytes):
                            blob, index, chunk = decode_preview_frame(raw, expected_kind=2)
                            image_bytes.extend(chunk)
                            chunk.release()
                            await send({"type": "display.ack", "blob_id": str(blob), "chunk_index": index})
                            continue
                        event = json.loads(raw)
                        kind = event["type"]
                        elapsed = round(monotonic()-started, 3)
                        result["events"][kind] = result["events"].get(kind, 0)+1
                        payload = event.get("payload", {})
                        if kind == "node.started" and payload["node_id"] == "preview_probe_delay":
                            result["delay_started_seconds"] = elapsed
                            print("Delay started; earlier displays:", result["events"].get("display.updated", 0), flush=True)
                        if kind == "display.updated":
                            result.setdefault("first_display_seconds", elapsed)
                            if source is None:
                                image = payload.get("payload", {}).get("image", {})
                                candidate = image.get("source_image")
                                if candidate:
                                    source = candidate
                                    await send({"type": "display.get", "blob_id": source["blob_id"]})
                        if kind == "display.end":
                            import cv2
                            import numpy as np
                            matrix = cv2.imdecode(np.frombuffer(image_bytes, np.uint8), cv2.IMREAD_UNCHANGED)
                            assert matrix is not None and matrix.shape[:2] == (source["height"], source["width"])
                            result["source_image"] = {"width": matrix.shape[1], "height": matrix.shape[0], "decoded_seconds": elapsed, "encoded_bytes": len(image_bytes)}
                            image_bytes.clear()
                        if kind in {"display.unavailable", "protocol.error"}:
                            result["errors"].append(event)
                        if kind == "run.finished":
                            result["terminal"] = payload
                            result["finished_seconds"] = elapsed
                            break
                async with websockets.connect(url, max_size=8*1024**2) as ws:
                    snapshot = json.loads(await ws.recv())
                    result["reconnected_state"] = snapshot["payload"]["run"]["state"]
                    result["retained_displays"] = len(snapshot["payload"]["displays"])
                assert result["terminal"]["status"] == "succeeded", result["terminal"]
                assert result["first_display_seconds"] < result["delay_started_seconds"] < result["finished_seconds"]
                assert result["source_image"]["decoded_seconds"] < result["finished_seconds"]
                assert not result["errors"], result["errors"]
                result["passed"] = True
        finally:
            if health_task:
                health_task.cancel()
                await asyncio.gather(health_task, return_exceptions=True)
            if sid:
                await request("DELETE", f"{base}/{sid}")
                result["session_released"] = True
            Path(args.report).parent.mkdir(parents=True, exist_ok=True)
            Path(args.report).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps({k: v for k, v in result.items() if k not in {"health", "terminal"}}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:5600")
    parser.add_argument("--project", default="project-1")
    parser.add_argument("--application", default="workflow-app-20260831130620")
    parser.add_argument("--delay", type=float, default=90)
    parser.add_argument("--image", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--report", required=True)
    asyncio.run(validate(parser.parse_args()))
