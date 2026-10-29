"""通过正式 Preview 会话验证线扫配方，保存结果后释放全部会话资源。"""

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
from time import perf_counter
from uuid import uuid4

import httpx
import psutil
import websockets

from backend.contracts.workflows.preview_session import (
    PREVIEW_CHUNK_SIZE,
    encode_preview_frame,
    decode_preview_frame,
)
from backend.service.application.auth.default_local_auth_seeder import (
    DEFAULT_LOCAL_AUTH_TOKEN,
)
from scripts.configure_linescan_3913_workflow import DATA, APP_ID


async def validate(args):
    """读当前草稿快照执行，不发布、不修改 Runtime，不持久化 WorkflowRun。"""
    validation_root = (DATA / "validation").resolve()
    out = (validation_root / args.report).resolve()
    if out == validation_root or not out.is_relative_to(validation_root):
        raise ValueError("报告必须位于 validation 的独立子目录")
    out.mkdir(parents=True, exist_ok=True)
    result = {
        "face": args.face,
        "image": str(args.image),
        "events": {},
        "nodes": [],
        "memory": [],
        "resources": [],
    }
    started = perf_counter()
    async with httpx.AsyncClient(
        base_url="http://127.0.0.1:5600",
        headers={"Authorization": "Bearer " + DEFAULT_LOCAL_AUTH_TOKEN},
        timeout=60,
    ) as client:

        async def call(method, path, **kw):
            response = await client.request(method, path, **kw)
            if response.status_code >= 400:
                raise RuntimeError(response.text)
            return response.json() if response.content else None

        app = (
            await call(
                "GET", f"/api/v1/workflows/projects/project-1/applications/{APP_ID}"
            )
        )["application"]
        ref = app["template_ref"]
        template = (
            await call(
                "GET",
                f"/api/v1/workflows/projects/project-1/templates/{ref['template_id']}/versions/{ref['template_version']}",
            )
        )["template"]
        if getattr(args, "no_preview", False):
            # 仅修改本次执行快照：关闭显示节点、调试图和差异图，不删检测业务。
            for node in template["nodes"]:
                if node["node_type_id"] in {
                    "core.io.image-preview",
                    "core.io.value-preview",
                    "custom.opencv.gallery-preview",
                }:
                    node["enabled"] = False
                parameters = node.get("parameters", {})
                for key in ("debug_image_panel_enabled", "emit_comparison_images"):
                    if key in parameters:
                        parameters[key] = False
            # 检测配方显式划分的证据分支也关闭，业务测量及汇总保持执行。
            evidence_ids = {
                node_id
                for group in template.get("groups", [])
                if group["group_id"] == "inspection-evidence"
                for node_id in group["member_node_ids"]
            }
            for node in template["nodes"]:
                if node["node_id"] in evidence_ids:
                    node["enabled"] = False
            result["disabled_evidence_nodes"] = sorted(evidence_ids)
            result["no_preview"] = True
        # 缩略合成图只验证比较链，不进入原像素读码链。
        if args.inspection_only:
            if any(n["node_id"] == "barcode_roi" for n in template["nodes"]):
                # 仅在本次快照筛掉全部读码项，保留循环的外部图像依赖。
                next(n for n in template["nodes"] if n["node_id"] == "passed_items")[
                    "parameters"
                ]["condition"] = {
                    "path": "item_id",
                    "operator": "eq",
                    "right": "__validation_no_barcode__",
                }
            else:
                recipe = next(n for n in template["nodes"] if n["node_id"] == "recipe")
                recipe["parameters"]["fields"]["barcode_rois"] = []
                template["edges"] = [
                    e
                    for e in template["edges"]
                    if not (
                        e["target_node_id"] == "crop_search"
                        and e["target_port"] == "selected_ids"
                    )
                ]
        if getattr(args, "barcode_bbox", None):
            next(n for n in template["nodes"] if n["node_id"] == "barcode_roi")[
                "parameters"
            ]["bbox_xyxy"] = args.barcode_bbox
        if getattr(args, "deployment_id", None):
            next(n for n in template["nodes"] if n["node_id"] == "detect_code")[
                "parameters"
            ]["deployment_instance_id"] = args.deployment_id
        session = await call(
            "POST",
            "/api/v1/workflows/preview-sessions",
            json={
                "project_id": "project-1",
                "application_id": APP_ID,
                "editor_session_id": str(uuid4()),
            },
        )
        sid = session["session_id"]

        async def sample():
            """每秒采样本机 Python 进程，不记录命令中的凭据。"""
            while True:
                processes = []
                for p in psutil.process_iter(["name"]):
                    if (p.info["name"] or "").lower().startswith("python"):
                        try:
                            mem = p.memory_info()
                            processes.append(
                                {
                                    "pid": p.pid,
                                    "rss": mem.rss,
                                    "private": getattr(mem, "private", None),
                                    "handles": p.num_handles(),
                                }
                            )
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            pass
                result["memory"].append(
                    {"seconds": perf_counter() - started, "processes": processes}
                )
                await asyncio.sleep(1)

        sampling = asyncio.create_task(sample())
        try:
            url = f"ws://127.0.0.1:5600/ws/v1/workflows/preview-sessions/{sid}?access_token={DEFAULT_LOCAL_AUTH_TOKEN}"
            async with (
                asyncio.timeout(240),
                websockets.connect(
                    url, max_size=PREVIEW_CHUNK_SIZE + 65536, compression=None
                ) as ws,
            ):
                await ws.recv()

                async def send(msg):
                    await ws.send(json.dumps(msg))

                async def expect(kind):
                    while True:
                        event = json.loads(await ws.recv())
                        if event["type"] == "session.ping":
                            await send({"type": "session.pong"})
                            continue
                        if event["type"] != kind:
                            raise RuntimeError(str(event))
                        return event

                inputs = {}
                input_ids = {}
                if args.local_file:
                    # 本机验证 BMP，避免把近 1 GiB 文件经 WebSocket 上传；路径显式提供。
                    from PIL import Image

                    Image.MAX_IMAGE_PIXELS = 400_000_000
                    with Image.open(args.image) as source:
                        width, height = source.size
                    inputs["request_image_ref"] = {
                        "transport_kind": "local-path",
                        "local_path": str(args.image.resolve()),
                        "media_type": "image/bmp"
                        if args.image.suffix.lower() == ".bmp"
                        else "image/png",
                        "width": width,
                        "height": height,
                    }
                else:
                    content = Path(args.image).read_bytes()
                    transfer = uuid4()
                    await send(
                        {
                            "type": "input.begin",
                            "transfer_id": str(transfer),
                            "byte_length": len(content),
                            "media_type": "image/png"
                            if Path(args.image).suffix.lower() == ".png"
                            else "image/jpeg",
                            "sha256": hashlib.sha256(content).hexdigest(),
                            "file_name": Path(args.image).name,
                        }
                    )
                    await expect("input.ready")
                    for index, offset in enumerate(
                        range(0, len(content), PREVIEW_CHUNK_SIZE)
                    ):
                        await ws.send(
                            encode_preview_frame(
                                transfer,
                                index,
                                content[offset : offset + PREVIEW_CHUNK_SIZE],
                                kind=1,
                            )
                        )
                        await expect("input.ack")
                    await send({"type": "input.commit", "transfer_id": str(transfer)})
                    uploaded = await expect("input.committed")
                    del content
                    input_ids["request_image_ref"] = uploaded["input_id"]
                invoke_started = perf_counter()
                accepted = await call(
                    "POST",
                    f"/api/v1/workflows/preview-sessions/{sid}/runs",
                    json={
                        "request_id": str(uuid4()),
                        "document_revision": "3913-validation",
                        "application": app,
                        "template": template,
                        "input_ids": input_ids,
                        "input_bindings": inputs,
                        "timeout_seconds": 180,
                        **(
                            {
                                "execution_scope": {
                                    "kind": "node",
                                    "target_node_id": args.target_node,
                                }
                            }
                            if getattr(args, "target_node", None)
                            else {}
                        ),
                    },
                )
                result["run_id"] = accepted["run_id"]
                known, pending, active, origins = {}, [], {}, {}

                def discover(value, origin):
                    """只抓取标准显示资源描述符，正文不解析私有实现状态。"""
                    if isinstance(value, dict):
                        if (
                            value.get("transport_kind") == "preview-memory"
                            and value.get("blob_id")
                            and value["blob_id"] not in known
                        ):
                            blob = value["blob_id"]
                            known[blob] = value
                            origins[blob] = origin
                            pending.append(blob)
                        for v in value.values():
                            discover(v, origin)
                    elif isinstance(value, list):
                        for v in value:
                            discover(v, origin)

                finished = False
                while not finished or pending or active:
                    while pending and len(active) < 2:
                        blob = pending.pop(0)
                        active[blob] = bytearray()
                        await send({"type": "display.get", "blob_id": blob})
                    raw = await ws.recv()
                    if isinstance(raw, bytes):
                        blob, index, chunk = decode_preview_frame(raw, expected_kind=2)
                        active[blob.hex].extend(chunk)
                        chunk.release()
                        await send(
                            {
                                "type": "display.ack",
                                "blob_id": str(blob),
                                "chunk_index": index,
                            }
                        )
                        continue
                    event = json.loads(raw)
                    kind = event["type"]
                    payload = event.get("payload", {})
                    result["events"][kind] = result["events"].get(kind, 0) + 1
                    if kind == "session.ping":
                        await send({"type": "session.pong"})
                    if kind in {"display.updated", "value.updated", "run.outputs"}:
                        discover(payload, {
                            "event_type": kind,
                            **{key: payload[key] for key in ("node_id", "output_port", "invocation_id", "event_node_id") if key in payload},
                        })
                    if kind == "node.finished":
                        result["nodes"].append(payload)
                    if kind == "display.end":
                        blob = event["blob_id"]
                        data = active.pop(blob)
                        descriptor = known[blob]
                        extension = (
                            ".json"
                            if descriptor.get("media_type") == "application/json"
                            else ".jpg"
                        )
                        filename = f"resource-{len(result['resources']):03d}{extension}"
                        (out / filename).write_bytes(data)
                        result["resources"].append({"file": filename, "origin": origins[blob], **descriptor})
                        await send(
                            {
                                "type": "resource.received",
                                "blob_id": blob,
                                "receipt": event["receipt"],
                            }
                        )
                    if kind in {"protocol.error", "display.unavailable"}:
                        result.setdefault("errors", []).append({**event, "origin": origins.get(event.get("blob_id"))})
                        if event.get("blob_id"):
                            active.pop(event["blob_id"], None)
                    if kind == "run.finished":
                        result["run_roundtrip_ms"] = (perf_counter() - invoke_started) * 1000
                        result["terminal"] = payload
                        print(
                            "terminal",
                            payload["status"],
                            payload.get("timings", {}),
                            flush=True,
                        )
                        if payload["status"] != "succeeded":
                            break
                    if kind == "run.outputs":
                        result["outputs"] = payload
                        finished = True
            result["elapsed_seconds"] = perf_counter() - started
        finally:
            try:
                await call("DELETE", f"/api/v1/workflows/preview-sessions/{sid}")
                result["session_released"] = True
                await asyncio.sleep(3)
            finally:
                sampling.cancel()
                await asyncio.gather(sampling, return_exceptions=True)
                (out / "report.json").write_text(
                    json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                print("report", out / "report.json", flush=True)
    if result.get("terminal", {}).get("status") != args.expect_status:
        raise RuntimeError("Preview 验证未通过")
    if args.expect_status == "succeeded" and result.get("errors"):
        raise RuntimeError("业务完成但 Preview 显示不完整，请检查报告中的 errors")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deployment-id", help="仅在本次验证快照替换条码模型部署")
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--face", choices=["front"], default="front")
    parser.add_argument("--report", required=True)
    parser.add_argument("--inspection-only", action="store_true")
    parser.add_argument(
        "--expect-status", choices=["succeeded", "failed"], default="succeeded"
    )
    parser.add_argument("--local-file", action="store_true")
    parser.add_argument(
        "--no-preview", action="store_true", help="验证快照关闭图片/值/图集预览和调试图"
    )
    parser.add_argument("--target-node", help="只验证目标节点及其祖先，不执行后续节点")
    parser.add_argument(
        "--barcode-bbox", type=int, nargs=4, help="仅覆盖本次验证快照的条码矩形"
    )
    asyncio.run(validate(parser.parse_args()))
