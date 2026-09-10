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
        if args.delay:
            template["nodes"].append({"node_id": "preview_probe_delay", "node_type_id": "core.logic.delay", "parameters": {"seconds": args.delay}})
            template["edges"].append({"edge_id": "preview_probe_wait", "source_node_id": output["source_node_id"], "source_port": output["source_port"], "target_node_id": "preview_probe_delay", "target_port": "value"})
            output.update(source_node_id="preview_probe_delay", source_port="value")
        for node in template["nodes"]:
            if "save_directory" in node.get("parameters", {}):
                node["parameters"]["save_directory"] = str(Path(args.output).resolve() / node["node_id"])
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
                async with websockets.connect(url, max_size=PREVIEW_CHUNK_SIZE + 65536, compression=None) as ws:
                    assert json.loads(await ws.recv())["type"] == "session.snapshot"
                    result["input_started_seconds"] = monotonic()-started
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
                    offsets = list(range(0, len(content), PREVIEW_CHUNK_SIZE))
                    for start in range(0, len(offsets), 8):
                        for index in range(start, min(start+8, len(offsets))):
                            offset = offsets[index]
                            await ws.send(encode_preview_frame(transfer, index, content[offset:offset+PREVIEW_CHUNK_SIZE], kind=1))
                        for _ in offsets[start:start+8]:
                            await expect("input.ack")
                    await send({"type": "input.commit", "transfer_id": str(transfer)})
                    uploaded = await expect("input.committed")
                    result["upload_complete_seconds"] = monotonic()-started
                    del content
                    accepted = await request("POST", f"{base}/{sid}/runs", json={"request_id": str(uuid4()), "document_revision": "isolated-live-probe", "application": app, "template": template,
                        "input_ids": {args.input_kind: uploaded["input_id"]}, "input_bindings": {"request_json": {"value": {"savepath": str(Path(args.output).resolve()).replace('\\', '/'), "barqrcode": "preview-stream-validation"}}}, "timeout_seconds": 120})
                    result["run_id"] = accepted["run_id"]
                    known, pending, active = {}, [], {}
                    result["resources"] = []
                    result["nodes"] = []
                    finished = False
                    def discover(value):
                        """收集显示与大值的所有资源，不能只验证第一张缩略图。"""
                        if isinstance(value, dict):
                            if value.get("transport_kind") == "preview-memory" and value.get("blob_id"):
                                blob = value["blob_id"]
                                if blob not in known:
                                    known[blob] = value
                                    pending.append(blob)
                            for child in value.values():
                                discover(child)
                        elif isinstance(value, list):
                            for child in value:
                                discover(child)
                    while not finished or pending or active:
                        while pending and len(active) < 4:
                            blob = pending.pop(0)
                            active[blob] = bytearray()
                            await send({"type": "display.get", "blob_id": blob})
                        raw = await ws.recv()
                        if isinstance(raw, bytes):
                            blob, index, chunk = decode_preview_frame(raw, expected_kind=2)
                            active[blob.hex].extend(chunk)
                            chunk.release()
                            await send({"type": "display.ack", "blob_id": str(blob), "chunk_index": index})
                            continue
                        event = json.loads(raw)
                        kind = event["type"]
                        elapsed = round(monotonic()-started, 3)
                        result["events"][kind] = result["events"].get(kind, 0)+1
                        payload = event.get("payload", {})
                        if kind == "session.ping":
                            await send({"type": "session.pong"})
                        if kind in {"display.updated", "value.updated", "run.outputs"}:
                            discover(payload)
                        if kind == "node.finished":
                            result["nodes"].append(payload)
                        if kind == "node.started" and payload["node_id"] == "preview_probe_delay":
                            result["delay_started_seconds"] = elapsed
                            print("Delay started; earlier displays:", result["events"].get("display.updated", 0), flush=True)
                        if kind == "display.updated":
                            result.setdefault("first_display_seconds", elapsed)
                        if kind == "display.end":
                            import cv2
                            import numpy as np
                            blob = event["blob_id"]
                            data = active.pop(blob)
                            descriptor = known[blob]
                            resource = {"media_type": descriptor.get("media_type"), "encoded_bytes": len(data), "decoded_seconds": elapsed}
                            if descriptor.get("media_type", "").startswith("image/"):
                                assert descriptor["media_type"] == "image/jpeg" and data[:2] == b"\xff\xd8"
                                matrix = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_UNCHANGED)
                                assert matrix is not None
                                if "height" in descriptor:
                                    assert matrix.shape[:2] == (descriptor["height"], descriptor["width"])
                                resource.update(width=matrix.shape[1], height=matrix.shape[0])
                                del matrix
                            elif descriptor.get("media_type") == "application/json":
                                json.loads(data)
                            result["resources"].append(resource)
                            await send({"type": "resource.received", "blob_id": blob, "receipt": event["receipt"]})
                        if kind in {"display.unavailable", "protocol.error"}:
                            result["errors"].append(event)
                            if event.get("blob_id"):
                                active.pop(event["blob_id"], None)
                        if kind == "run.finished":
                            result["terminal"] = payload
                            result["finished_seconds"] = elapsed
                            assert payload["status"] == "succeeded", payload
                        if kind == "run.outputs":
                            result["delivery"] = payload
                            finished = True
                    result["all_received_decoded_seconds"] = monotonic()-started
                    result["released_resources"] = 0
                    for blob in known:
                        await send({"type": "display.get", "blob_id": blob})
                        released = await expect("protocol.error")
                        assert released["error"] == "preview_memory_unavailable", released
                        result["released_resources"] += 1
                async with websockets.connect(url, max_size=8*1024**2, compression=None) as ws:
                    snapshot = json.loads(await ws.recv())
                    result["reconnected_state"] = snapshot["payload"]["run"]["state"]
                    result["retained_displays"] = len(snapshot["payload"]["displays"])
                assert result["terminal"]["status"] == "succeeded", result["terminal"]
                if args.delay:
                    assert result["first_display_seconds"] < result["finished_seconds"]-args.delay+1
                assert result["resources"]
                assert result["delivery"]["delivery_state"] == "ready"
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
            print(json.dumps({k: v for k, v in result.items() if k not in {"health", "terminal", "nodes", "resources", "delivery"}}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:5600")
    parser.add_argument("--project", default="project-1")
    parser.add_argument("--application", default="workflow-app-20260831130620")
    parser.add_argument("--delay", type=float, default=0)
    parser.add_argument("--input-kind", choices=["request_image_ref", "request_image_base64"], default="request_image_base64")
    parser.add_argument("--image", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--report", required=True)
    asyncio.run(validate(parser.parse_args()))
