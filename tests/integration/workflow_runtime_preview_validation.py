"""显式创建无磁盘写入的预览验证 App，并测量实际 Runtime 显示开销。

开发命令：conda activate amvision 后使用 python -m tests.integration.workflow_runtime_preview_validation。
仅 --create 创建开发资源；已有 Runtime 由 --runtime-id 显式选择，不操作生产 Trigger。
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from statistics import median
from time import perf_counter, sleep
from urllib.parse import urlencode
from uuid import uuid4
import socket

import httpx
import psutil
from websockets.sync.client import connect


def _token(value: dict) -> str:
    """从已有 SDK 配置取得 token，只在本进程使用，不输出凭据。"""
    for key, item in value.items():
        if key == "access_token" and isinstance(item, str):
            return item
        if isinstance(item, dict):
            found = _token(item)
            if found:
                return found
    return ""


def _create(client: httpx.Client, image_path: Path) -> dict:
    """创建只有读取和 Preview 的标准命名 Workflow，不修改现有应用。"""
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    app_id, graph_id = f"workflow-app-{stamp}", f"workflow-graph-{stamp}"
    name = f"Runtime 预览画布验证 {stamp}"
    def node(identifier: str, kind: str, parameters: dict, x: int, y: int) -> dict:
        return {"node_id": identifier, "node_type_id": kind, "parameters": parameters,
                "ui_state": {"x": x, "y": y, "width": 320}}
    template = {
        "format_id": "amvision.workflow-graph-template.v1", "template_id": graph_id,
        "template_version": "1.0.0", "display_name": name,
        "nodes": [
            node("image", "core.io.image-load-local", {"local_path": str(image_path.resolve())}, 40, 40),
            node("image_preview", "core.io.image-preview", {"title": "生产结果图片"}, 430, 40),
            node("json", "core.logic.coalesce", {"fallback_value": {"optional": True, "empty": "", "zero": 0, "flag": False}}, 40, 470),
            node("json_preview", "core.io.value-preview", {"title": "调用 JSON"}, 430, 470),
        ],
        "edges": [
            {"edge_id": "image-display", "source_node_id": "image", "source_port": "image", "target_node_id": "image_preview", "target_port": "image"},
            {"edge_id": "json-display", "source_node_id": "json", "source_port": "value", "target_node_id": "json_preview", "target_port": "value"},
        ],
        "template_inputs": [{"input_id": "request_json", "display_name": "request_json", "payload_type_id": "value.v1", "target_node_id": "json", "target_port": "primary", "required": False}],
        "template_outputs": [{"output_id": "result", "display_name": "result", "payload_type_id": "value.v1", "source_node_id": "json", "source_port": "value"}],
    }
    application = {
        "format_id": "amvision.flow-application.v1", "application_id": app_id, "display_name": name,
        "template_ref": {"template_id": graph_id, "template_version": "1.0.0", "source_kind": "json-file", "source_uri": f"workflows/projects/project-1/templates/{graph_id}/versions/1.0.0/template.json"},
        "bindings": [
            {"binding_id": "request_json", "direction": "input", "template_port_id": "request_json", "binding_kind": "api-request", "metadata": {"payload_type_id": "value.v1"}},
            {"binding_id": "result", "direction": "output", "template_port_id": "result", "binding_kind": "http-response", "metadata": {"payload_type_id": "value.v1"}},
        ],
    }
    path = f"/workflows/projects/project-1/applications/{app_id}"
    result = client.put(path, json={"application": application, "template": template})
    result.raise_for_status()
    # 现有 Runtime create 显式从 App 发布快照创建首版，与平台入口一致。
    result = client.post("/workflows/app-runtimes", json={"project_id": "project-1", "application_id": app_id,
        "display_name": f"{name} runtime", "metadata": {"workflow_run_record_mode": "none"}})
    result.raise_for_status()
    runtime_id = result.json()["workflow_runtime_id"]
    client.post(f"/workflows/app-runtimes/{runtime_id}/start").raise_for_status()
    return {"application_id": app_id, "workflow_runtime_id": runtime_id}


def _resources(worker_id: int) -> dict:
    """采样固定 worker 与其 backend 父进程，不遍历或触碰其他进程。"""
    worker = psutil.Process(worker_id)
    result = {}
    for name, process in (("worker", worker), ("backend", worker.parent())):
        memory = process.memory_info()
        result[name] = {"pid": process.pid, "private_mb": round(getattr(memory, "private", memory.rss) / 1048576, 2),
                        "rss_mb": round(memory.rss / 1048576, 2), "handles": process.num_handles()}
    return result


def _benchmark(client: httpx.Client, runtime_id: str, token: str, cycles: int) -> dict:
    """顺序真实调用；A/B 对照，不制造不合理业务并发。"""
    base = f"/workflows/app-runtimes/{runtime_id}"
    snapshot = client.get(f"{base}/preview-snapshot").json()
    instances = client.get(f"{base}/instances").json()
    worker_id = next(item["process_id"] for item in instances if item.get("process_id"))
    query = urlencode({key: snapshot[key] for key in ("workflow_runtime_id", "workflow_runtime_revision_id", "runtime_generation", "worker_instance_id")})
    ws_url = f"ws://127.0.0.1:5600/ws/v1/workflows/app-runtimes/preview?{query}"
    def invoke(index: int) -> dict:
        response = client.post(f"{base}/invoke?response_mode=run", json={
            "input_bindings": {"request_json": {"value": {"sequence": index, "flag": False, "zero": 0, "text": "实际数据预览"}}},
            "execution_metadata": {"workflow_run_record_mode": "none"},
        })
        response.raise_for_status()
        body = response.json()
        assert body["state"] == "succeeded", body
        return body
    for i in range(15):
        invoke(i)
    result = {"runtime_id": runtime_id, "before": _resources(worker_id), "phases": []}
    for watched in (False, True, False, True):
        connection = connect(ws_url, additional_headers={"Authorization": f"Bearer {token}"}, max_size=64 * 1048576) if watched else None
        times = []
        frame_bytes = 0
        try:
            if connection:
                assert json.loads(connection.recv(timeout=5))["state"] == "connected"
            for i in range(cycles):
                started = perf_counter()
                response = invoke(i)
                times.append((perf_counter() - started) * 1000)
                if connection:
                    raw = connection.recv(timeout=10)
                    connection.send("ready")
                    frame_bytes = len(raw)
                    frame = json.loads(raw)
                    assert frame["workflow_run_id"] == response["workflow_run_id"]
                    assert frame["display_error"] is None
                    preview = next(item for item in frame["displays"] if item["node_id"] == "json_preview")
                    assert preview["payload"]["value"]["sequence"] == i
                    assert preview["payload"]["value"]["flag"] is False
                    image = next(item for item in frame["displays"] if item["node_id"] == "image_preview")
                    assert image["payload"]["image"].get("image_base64")
                    del raw, frame, preview, image
            ordered = sorted(times)
            result["phases"].append({"watched": watched, "calls": cycles, "p50_ms": round(median(times), 3),
                "p95_ms": round(ordered[int((len(times)-1)*.95)], 3), "max_ms": round(max(times), 3),
                "frame_bytes": frame_bytes, "resources": _resources(worker_id)})
        finally:
            if connection:
                connection.close()
    sleep(.5)
    result["after"] = _resources(worker_id)
    return result


def _validate_triggers(client: httpx.Client, runtime_id: str, token: str) -> dict:
    """为专用验证 App 创建两种 Trigger，逐次校验业务返回与显示身份，最后停用。"""
    from backend.contracts.workflows import WorkflowTriggerEventRequestV1
    from backend.service.infrastructure.ipc.workflow_trigger_mailbox import WorkflowTriggerMailboxClient
    from tests.integration.deployment_workflow_trigger_soak import ZeroMqSoakClient

    base = f"/workflows/app-runtimes/{runtime_id}"
    snapshot = client.get(f"{base}/preview-snapshot").json()
    assert snapshot["display_name"].startswith("Runtime 预览画布验证 "), "仅允许专用验证 App"
    query = urlencode({key: snapshot[key] for key in ("workflow_runtime_id", "workflow_runtime_revision_id", "runtime_generation", "worker_instance_id")})
    ws_url = f"ws://127.0.0.1:5600/ws/v1/workflows/app-runtimes/preview?{query}"
    with socket.socket() as port_probe:
        port_probe.bind(("127.0.0.1", 0))
        port = port_probe.getsockname()[1]
    endpoint = f"tcp://127.0.0.1:{port}"
    sources = []
    report = []
    try:
        for prefix, kind, transport in (
            ("zeromq", "zeromq-topic", {"bind_endpoint": endpoint}),
            ("local-shared-memory", "local-shared-memory", {}),
        ):
            source_id = f"{prefix}-{runtime_id}"
            existing = client.get(f"/workflows/trigger-sources/{source_id}")
            source_payload = {
                "trigger_source_id": source_id, "project_id": snapshot["project_id"],
                "display_name": f"Runtime 预览验证 {prefix}", "trigger_kind": kind,
                "workflow_runtime_id": runtime_id, "submit_mode": "sync", "enabled": True,
                "transport_config": transport,
                "input_binding_mapping": {"request_json": {"source": "payload.request_json", "required": False, "payload_type_id": "value.v1"}},
                "result_mapping": {"result_bindings": ["result"]},
                "default_execution_metadata": {"workflow_run_record_mode": "none"},
                "ack_policy": "ack-after-run-finished", "result_mode": "sync-reply", "reply_timeout_seconds": 30,
            }
            if existing.status_code == 200:
                saved = existing.json()
                assert saved["display_name"] == source_payload["display_name"] and saved["workflow_runtime_id"] == runtime_id and saved["trigger_kind"] == kind
                assert saved["enabled"] is False, "不接管已启用 Trigger"
                if prefix == "zeromq":
                    endpoint = saved["transport_config"]["bind_endpoint"]
                response = client.post(f"/workflows/trigger-sources/{source_id}/enable")
            else:
                assert existing.status_code == 404, "不覆盖已有 Trigger"
                response = client.post("/workflows/trigger-sources", json=source_payload)
            response.raise_for_status()
            sources.append(source_id)
            health = client.get(f"/workflows/trigger-sources/{source_id}/health").json()
            with connect(ws_url, additional_headers={"Authorization": f"Bearer {token}"}, max_size=64 * 1048576) as ws:
                assert json.loads(ws.recv(timeout=5))["state"] == "connected"
                zmq_client = ZeroMqSoakClient(endpoint=endpoint, timeout_seconds=30) if prefix == "zeromq" else None
                mailbox = WorkflowTriggerMailboxClient(buffers_root=Path("data/buffers")) if prefix != "zeromq" else None
                try:
                    for index in range(10):
                        payload = {"request_json": {"value": {"transport": prefix, "sequence": index, "flag": False, "zero": 0}}}
                        event_id = f"trigger-event-{uuid4().hex}"
                        if zmq_client:
                            result = zmq_client.send([json.dumps({"event_id": event_id, "payload": payload}).encode("utf-8")])
                        else:
                            route_generation = health["health_summary"]["supervisor"]["adapter_health"]["route_generation"]
                            identity = mailbox.claim_event(timeout_ms=30000, route_generation=route_generation,
                                event_payload=WorkflowTriggerEventRequestV1(trigger_source_id=source_id, event_id=event_id, payload=payload).model_dump_json().encode("utf-8"))
                            deadline = perf_counter() + 30
                            response = None
                            while response is None and perf_counter() < deadline:
                                response = mailbox.read_response(identity=identity)
                                if response is None:
                                    sleep(.002)
                            assert response is not None
                            result = json.loads(response.payload)
                            mailbox.acknowledge(identity=identity)
                        assert result["state"] == "succeeded", result
                        frame = json.loads(ws.recv(timeout=10))
                        ws.send("ready")
                        assert frame["workflow_run_id"] == result["workflow_run_id"]
                        assert frame["state"] == "succeeded" and frame["display_error"] is None
                        value = next(item for item in frame["displays"] if item["node_id"] == "json_preview")["payload"]["value"]
                        assert value == payload["request_json"]["value"]
                        assert "displays" not in result["response_payload"]
                    report.append({"trigger_source_id": source_id, "calls": 10, "correct": True})
                finally:
                    if zmq_client:
                        zmq_client.close()
                    if mailbox:
                        mailbox.close()
    finally:
        for source_id in sources:
            client.post(f"/workflows/trigger-sources/{source_id}/disable").raise_for_status()
    return {"runtime_id": runtime_id, "triggers": report, "sources_disabled": sources}


def main() -> None:
    """按显式参数创建开发验证资源或运行有界对照。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--sdk-config", default="sdks/dotnet/src/Amvar.Vision/Config/config_workflow-app-20260831130620.json")
    parser.add_argument("--create", action="store_true")
    parser.add_argument("--image-path")
    parser.add_argument("--runtime-id")
    parser.add_argument("--cycles", type=int, default=50)
    parser.add_argument("--validate-triggers", action="store_true")
    args = parser.parse_args()
    token = _token(json.loads(Path(args.sdk_config).read_text(encoding="utf-8-sig")))
    assert token and 1 <= args.cycles <= 5000
    with httpx.Client(base_url="http://127.0.0.1:5600/api/v1", headers={"Authorization": f"Bearer {token}"}, timeout=60) as client:
        if args.create:
            image_path = Path(args.image_path or "")
            assert image_path.is_file()
            print(json.dumps(_create(client, image_path), ensure_ascii=True))
        elif args.runtime_id:
            report = _validate_triggers(client, args.runtime_id, token) if args.validate_triggers else _benchmark(client, args.runtime_id, token, args.cycles)
            print(json.dumps(report, ensure_ascii=True))
        else:
            parser.error("必须显式选择 --create 或 --runtime-id")


if __name__ == "__main__":
    main()
