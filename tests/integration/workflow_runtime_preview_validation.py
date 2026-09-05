"""显式创建无磁盘写入的预览验证 App，并测量实际 Runtime 显示开销。

开发命令：conda activate amvision 后使用 python -m tests.integration.workflow_runtime_preview_validation。
仅 --create 创建开发资源；已有 Runtime 由 --runtime-id 显式选择，不操作生产 Trigger。
"""

from __future__ import annotations

import argparse
import gc
import json
import os
import threading
from datetime import datetime
from multiprocessing import get_context
from pathlib import Path
from statistics import median
from tempfile import TemporaryDirectory
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


def _process_resources(process: psutil.Process) -> dict[str, int | float]:
    """读取一个固定进程的可比较资源指标。"""
    memory = process.memory_info()
    return {
        "pid": process.pid,
        "private_mb": round(getattr(memory, "private", memory.rss) / 1048576, 2),
        "rss_mb": round(memory.rss / 1048576, 2),
        "handles": process.num_handles(),
        "threads": process.num_threads(),
    }


def _resources(worker_id: int) -> dict:
    """采样固定 worker 与其 backend 父进程，不遍历或触碰其他进程。"""
    worker = psutil.Process(worker_id)
    result = {}
    for name, process in (("worker", worker), ("backend", worker.parent())):
        result[name] = _process_resources(process)
    return result


def _latency_summary(values: list[float]) -> dict[str, float]:
    """用同一套离散分位规则汇总调用耗时。"""
    ordered = sorted(values)
    assert ordered
    return {
        "p50_ms": round(median(ordered), 3),
        "p95_ms": round(ordered[int((len(ordered) - 1) * .95)], 3),
        "p99_ms": round(ordered[int((len(ordered) - 1) * .99)], 3),
        "max_ms": round(ordered[-1], 3),
    }


class _PreviewObservers:
    """并行消费多个大图观察连接；每连接最多处理当前一帧。"""

    def __init__(self, ws_url: str, token: str, snapshot: dict, count: int) -> None:
        """建立全部连接后再启动消费线程，避免连接时序混入调用测量。"""
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.snapshot = snapshot
        self.connections = []
        try:
            for _ in range(count):
                self.connections.append(connect(
                    ws_url,
                    additional_headers={"Authorization": f"Bearer {token}"},
                    max_size=64 * 1048576,
                ))
        except Exception:
            for connection in self.connections:
                connection.close()
            raise
        for connection in self.connections:
            connected = json.loads(connection.recv(timeout=10))
            assert connected["state"] == "connected"
        self.counts = [0] * count
        self.baseline_counts = [0] * count
        self.last_sequences = [0] * count
        self.frame_bytes = [0] * count
        self.errors: list[str] = []
        self.threads = [
            threading.Thread(
                target=self._consume,
                args=(index, connection),
                name=f"runtime-preview-observer-{index + 1}",
                daemon=True,
            )
            for index, connection in enumerate(self.connections)
        ]
        for thread in self.threads:
            thread.start()

    def _consume(self, index: int, connection: object) -> None:
        """模拟浏览器解析并确认帧；超时只继续等待，不触发业务重试。"""
        try:
            while not self.stop.is_set():
                try:
                    raw = connection.recv(timeout=15)
                except TimeoutError:
                    continue
                frame = json.loads(raw)
                assert frame["format_id"] == "amvision.workflow-runtime-preview.v1"
                for key in (
                    "workflow_runtime_id",
                    "workflow_runtime_revision_id",
                    "workflow_app_version_id",
                    "runtime_generation",
                    "worker_instance_id",
                    "snapshot_fingerprint",
                ):
                    assert frame[key] == self.snapshot[key]
                sequence = int(frame["sequence"])
                assert sequence > self.last_sequences[index]
                assert frame["state"] == "succeeded" and frame["display_error"] is None
                assert any(
                    item.get("payload", {}).get("type") == "image-preview"
                    for item in frame["displays"]
                )
                with self.lock:
                    self.last_sequences[index] = sequence
                    self.counts[index] += 1
                    self.frame_bytes[index] = len(raw)
                connection.send("ready")
                del raw, frame
        except Exception as exc:
            if not self.stop.is_set():
                with self.lock:
                    self.errors.append(f"observer-{index + 1}: {type(exc).__name__}: {exc}")

    def close(self) -> None:
        """关闭连接并等待消费线程退出，供句柄回落测量。"""
        self.stop.set()
        for connection in self.connections:
            connection.close()
        for thread in self.threads:
            thread.join(timeout=20)
        self.connections.clear()
        self.threads.clear()

    def mark_baseline(self) -> None:
        """把已完成的启动预热帧排除在正式门禁计数之外。"""
        deadline = perf_counter() + 15
        while perf_counter() < deadline:
            with self.lock:
                if min(self.counts) >= 3:
                    self.baseline_counts = list(self.counts)
                    return
            sleep(.05)
        raise TimeoutError("预览观察客户端未完成启动预热")

    def report(self, calls: int) -> dict:
        """报告每个连接实际接收数量；允许产品定义的主动丢帧。"""
        with self.lock:
            counts = [
                count - baseline
                for count, baseline in zip(self.counts, self.baseline_counts, strict=True)
            ]
            return {
                "connections": len(self.connections),
                "received_min": min(counts),
                "received_max": max(counts),
                "received_total": sum(counts),
                "dropped_max": max(calls - item for item in counts),
                "frame_bytes_min": min(self.frame_bytes),
                "frame_bytes_max": max(self.frame_bytes),
                "errors": list(self.errors),
            }


def _run_observer_process(
    ws_url: str,
    token: str,
    snapshot: dict,
    count: int,
    control: object,
) -> None:
    """在独立进程解析大帧，避免观察客户端 GIL 污染 HTTP 延迟测量。"""
    observers: _PreviewObservers | None = None
    try:
        observers = _PreviewObservers(ws_url, token, snapshot, count)
        control.send({"state": "ready", "pid": os.getpid()})
        while True:
            command = control.recv()
            name = command["name"]
            if name == "baseline":
                observers.mark_baseline()
                control.send({"state": "ok"})
            elif name == "report":
                control.send({"state": "ok", "report": observers.report(command["calls"])})
            elif name == "close":
                observers.close()
                observers = None
                control.send({"state": "closed"})
                return
            else:
                raise ValueError(f"未知观察进程命令: {name}")
    except BaseException as exc:
        try:
            control.send({"state": "error", "error": f"{type(exc).__name__}: {exc}"})
        except (BrokenPipeError, EOFError, OSError):
            pass
        raise
    finally:
        if observers is not None:
            observers.close()
        control.close()


class _PreviewObserverProcess:
    """管理独立的大图观察进程，只通过有界控制消息读取摘要。"""

    def __init__(self, ws_url: str, token: str, snapshot: dict, count: int) -> None:
        """使用 Windows 可复现的 spawn 上下文启动观察进程。"""
        context = get_context("spawn")
        self.control, child_control = context.Pipe()
        self.process = context.Process(
            target=_run_observer_process,
            args=(ws_url, token, snapshot, count, child_control),
            name="runtime-preview-observers",
        )
        self.closed = False
        self.process.start()
        child_control.close()
        message = self._receive(timeout_seconds=45)
        if message.get("state") != "ready":
            self.close()
            raise RuntimeError(f"预览观察进程启动失败: {message}")
        self.pid = int(message["pid"])

    def _receive(self, *, timeout_seconds: float) -> dict:
        """读取一条控制结果；子进程失联时明确失败。"""
        if not self.control.poll(timeout_seconds):
            raise TimeoutError("预览观察进程没有按时响应")
        message = self.control.recv()
        if message.get("state") == "error":
            raise RuntimeError(str(message.get("error")))
        return message

    def _command(self, name: str, **values: object) -> dict:
        """发送一条无业务正文的控制命令。"""
        if self.closed:
            raise RuntimeError("预览观察进程已经关闭")
        self.control.send({"name": name, **values})
        return self._receive(timeout_seconds=30)

    def mark_baseline(self) -> None:
        """等待并排除启动预热帧。"""
        assert self._command("baseline")["state"] == "ok"

    def report(self, calls: int) -> dict:
        """读取观察端累计摘要，不传输大帧。"""
        return dict(self._command("report", calls=calls)["report"])

    def close(self) -> None:
        """协作关闭后等待进程退出，确保线程和 socket 全部释放。"""
        if self.closed:
            return
        self.closed = True
        try:
            if self.process.is_alive():
                self.control.send({"name": "close"})
                self._receive(timeout_seconds=30)
        finally:
            self.control.close()
            self.process.join(timeout=30)
            if self.process.is_alive():
                self.process.kill()
                self.process.join(timeout=10)


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
            result["phases"].append({"watched": watched, "calls": cycles, **_latency_summary(ordered),
                "frame_bytes": frame_bytes, "resources": _resources(worker_id)})
        finally:
            if connection:
                connection.close()
    sleep(.5)
    result["after"] = _resources(worker_id)
    return result


def _soak(
    client: httpx.Client,
    runtime_id: str,
    token: str,
    duration_seconds: float,
    interval_seconds: float,
    subscriber_count: int,
) -> dict:
    """按现场节拍运行最多 16 个大图观察客户端的一小时稳定性门禁。"""
    base = f"/workflows/app-runtimes/{runtime_id}"
    snapshot = client.get(f"{base}/preview-snapshot").json()
    assert snapshot["active"] is True and snapshot["observed_state"] == "running"
    instances = client.get(f"{base}/instances").json()
    worker_id = next(item["process_id"] for item in instances if item.get("process_id"))
    query = urlencode({
        key: snapshot[key]
        for key in (
            "workflow_runtime_id",
            "workflow_runtime_revision_id",
            "runtime_generation",
            "worker_instance_id",
        )
    })
    ws_url = f"ws://127.0.0.1:5600/ws/v1/workflows/app-runtimes/preview?{query}"
    cold_before = _resources(worker_id)
    cold_before["client"] = _process_resources(psutil.Process())
    observers = _PreviewObserverProcess(ws_url, token, snapshot, subscriber_count)

    def invoke(sequence: int, text: str) -> dict:
        """调用一次真实 Runtime，并保持业务记录模式为 none。"""
        response = client.post(f"{base}/invoke?response_mode=run", json={
            "input_bindings": {
                "request_json": {
                    "value": {
                        "sequence": sequence,
                        "flag": False,
                        "zero": 0,
                        "text": text,
                    }
                }
            },
            "execution_metadata": {"workflow_run_record_mode": "none"},
        })
        response.raise_for_status()
        body = response.json()
        assert body["state"] == "succeeded", body
        return body

    for warmup in range(3):
        invoke(-warmup - 1, "Runtime 预览稳定性预热")
        sleep(.5)
    observers.mark_baseline()
    # websockets 默认 keepalive 会在约 20 秒后启动辅助资源；先进入稳定高水位。
    sleep(25)
    observer_process = psutil.Process(observers.pid)
    observer_before = _process_resources(observer_process)
    before = _resources(worker_id)
    before["client"] = _process_resources(psutil.Process())
    latencies: list[float] = []
    samples: list[dict] = []
    started = perf_counter()
    deadline = started + duration_seconds
    next_sample = started
    calls = 0
    try:
        while perf_counter() < deadline:
            sequence = calls
            request_started = perf_counter()
            invoke(sequence, "一小时 Runtime 预览稳定性验证")
            latencies.append((perf_counter() - request_started) * 1000)
            calls += 1
            now = perf_counter()
            if now >= next_sample:
                resources = _resources(worker_id)
                resources["client"] = _process_resources(psutil.Process())
                resources["observer_client"] = _process_resources(observer_process)
                sample = {
                    "elapsed_seconds": round(now - started, 1),
                    "calls": calls,
                    "latest_ms": round(latencies[-1], 3),
                    "resources": resources,
                }
                samples.append(sample)
                print(json.dumps({"soak_progress": sample}, ensure_ascii=True), flush=True)
                next_sample = now + 60
            # 现场节拍按本次完成后起算；发生系统停顿时不补发、不追赶。
            remaining = min(interval_seconds, deadline - perf_counter())
            if remaining > 0:
                sleep(remaining)
        sleep(min(5.0, interval_seconds))
        observer_report = observers.report(calls)
        assert not observer_report["errors"], observer_report
        assert observer_report["received_min"] >= max(1, calls - 2), observer_report
    finally:
        observers.close()
    gc.collect()
    sleep(5)
    after = _resources(worker_id)
    after["client"] = _process_resources(psutil.Process())
    observer_after = samples[-1]["resources"]["observer_client"]
    return {
        "format_id": "amvision.workflow-runtime-preview-soak.v1",
        "runtime_id": runtime_id,
        "duration_seconds": round(perf_counter() - started, 3),
        "configured_duration_seconds": duration_seconds,
        "interval_seconds": interval_seconds,
        "calls": calls,
        "failures": 0,
        "latency": _latency_summary(latencies),
        "observers": observer_report,
        "observer_process": {
            "pid": observers.pid,
            "exitcode": observers.process.exitcode,
            "before": observer_before,
            "last_sample": observer_after,
            "resource_deltas": {
                metric: round(observer_after[metric] - observer_before[metric], 2)
                for metric in ("private_mb", "rss_mb", "handles", "threads")
            },
        },
        "cold_before": cold_before,
        "before": before,
        "after": after,
        "resource_deltas": {
            process: {
                metric: round(after[process][metric] - before[process][metric], 2)
                for metric in ("private_mb", "rss_mb", "handles", "threads")
            }
            for process in ("worker", "backend", "client")
        },
        "samples": samples,
    }


def _wait_for_trigger_state(
    client: httpx.Client,
    trigger_source_id: str,
    state: str,
    timeout_seconds: float = 20,
) -> dict:
    """等待本次验证 Trigger 的真实 supervisor 状态。"""
    deadline = perf_counter() + timeout_seconds
    while perf_counter() < deadline:
        health = client.get(f"/workflows/trigger-sources/{trigger_source_id}/health")
        health.raise_for_status()
        payload = health.json()
        if payload.get("observed_state") == state:
            return payload
        sleep(.2)
    raise TimeoutError(f"Trigger 未进入 {state}: {trigger_source_id}")


def _validate_directory_trigger(client: httpx.Client, runtime_id: str, token: str) -> dict:
    """用临时目录变化触发实际 Runtime，并核对同一预览观察通道。"""
    base = f"/workflows/app-runtimes/{runtime_id}"
    snapshot = client.get(f"{base}/preview-snapshot").json()
    assert snapshot["display_name"].startswith("Runtime 预览画布验证 "), "仅允许专用验证 App"
    query = urlencode({
        key: snapshot[key]
        for key in (
            "workflow_runtime_id",
            "workflow_runtime_revision_id",
            "runtime_generation",
            "worker_instance_id",
        )
    })
    ws_url = f"ws://127.0.0.1:5600/ws/v1/workflows/app-runtimes/preview?{query}"
    Path(".tmp").mkdir(exist_ok=True)
    source_id = f"directory-watch-{runtime_id}-{uuid4().hex[:8]}"
    source_created = False
    with TemporaryDirectory(dir=".tmp", prefix="runtime-preview-directory-") as directory:
        source_payload = {
            "trigger_source_id": source_id,
            "project_id": snapshot["project_id"],
            "display_name": "Runtime 预览验证 directory-watch",
            "trigger_kind": "directory-watch",
            "workflow_runtime_id": runtime_id,
            "submit_mode": "async",
            "enabled": True,
            "transport_config": {
                "directory_path": str(Path(directory).resolve()),
                "extensions": [".json"],
                "min_trigger_interval_seconds": 3.0,
                "event_sample_limit": 10,
            },
            "input_binding_mapping": {
                "request_json": {
                    "source": "payload.directory_event_value",
                    "required": False,
                    "payload_type_id": "value.v1",
                }
            },
            "result_mapping": {"result_bindings": []},
            "default_execution_metadata": {"workflow_run_record_mode": "none"},
            "ack_policy": "ack-after-run-created",
            "result_mode": "event-only",
            "idempotency_key_path": "payload.directory_event_value.value.event_id",
        }
        try:
            created = client.post("/workflows/trigger-sources", json=source_payload)
            created.raise_for_status()
            source_created = True
            _wait_for_trigger_state(client, source_id, "running")
            with connect(
                ws_url,
                additional_headers={"Authorization": f"Bearer {token}"},
                max_size=64 * 1048576,
            ) as ws:
                assert json.loads(ws.recv(timeout=10))["state"] == "connected"
                event_path = Path(directory, "event.json")
                event_path.write_text('{"source":"directory-preview-validation"}', encoding="utf-8")
                frame = json.loads(ws.recv(timeout=20))
                ws.send("ready")
                assert frame["state"] == "succeeded" and frame["display_error"] is None
                value = next(
                    item for item in frame["displays"]
                    if item["node_id"] == "json_preview"
                )["payload"]["value"]
                assert value["event_id"].startswith("directory-watch-event-")
                assert value["trigger_source_id"] == source_id
                assert value["directory"]["path"] == str(Path(directory).resolve())
                assert value["change_counts"]["created"] >= 1
                assert any(item["path"] == str(event_path.resolve()) for item in value["samples"])
                return {
                    "runtime_id": runtime_id,
                    "trigger_source_id": source_id,
                    "workflow_run_id": frame["workflow_run_id"],
                    "event_id": value["event_id"],
                    "created_count": value["change_counts"]["created"],
                    "sample_count": len(value["samples"]),
                    "correct": True,
                }
        finally:
            if source_created:
                response = client.post(f"/workflows/trigger-sources/{source_id}/disable")
                response.raise_for_status()
                _wait_for_trigger_state(client, source_id, "stopped")
                deleted = client.delete(f"/workflows/trigger-sources/{source_id}")
                assert deleted.status_code == 204, deleted.text


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
    parser.add_argument("--validate-directory-trigger", action="store_true")
    parser.add_argument("--soak-seconds", type=float, default=0)
    parser.add_argument("--interval-seconds", type=float, default=3.0)
    parser.add_argument("--subscribers", type=int, default=16)
    parser.add_argument("--output")
    args = parser.parse_args()
    token = _token(json.loads(Path(args.sdk_config).read_text(encoding="utf-8-sig")))
    assert token and 1 <= args.cycles <= 5000
    assert 0 <= args.soak_seconds <= 3600
    assert .1 <= args.interval_seconds <= 60
    assert 1 <= args.subscribers <= 16
    selected_modes = sum((
        args.validate_triggers,
        args.validate_directory_trigger,
        args.soak_seconds > 0,
    ))
    if selected_modes > 1:
        parser.error("Trigger、目录 Trigger 和 soak 验证模式不能同时启用")
    with httpx.Client(base_url="http://127.0.0.1:5600/api/v1", headers={"Authorization": f"Bearer {token}"}, timeout=60) as client:
        if args.create:
            image_path = Path(args.image_path or "")
            assert image_path.is_file()
            print(json.dumps(_create(client, image_path), ensure_ascii=True))
        elif args.runtime_id:
            if args.validate_triggers:
                report = _validate_triggers(client, args.runtime_id, token)
            elif args.validate_directory_trigger:
                report = _validate_directory_trigger(client, args.runtime_id, token)
            elif args.soak_seconds > 0:
                report = _soak(
                    client,
                    args.runtime_id,
                    token,
                    args.soak_seconds,
                    args.interval_seconds,
                    args.subscribers,
                )
            else:
                report = _benchmark(client, args.runtime_id, token, args.cycles)
            serialized_report = json.dumps(report, ensure_ascii=True)
            if args.output:
                output_path = Path(args.output).resolve()
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text(serialized_report + "\n", encoding="utf-8")
            print(serialized_report)
        else:
            parser.error("必须显式选择 --create 或 --runtime-id")


if __name__ == "__main__":
    main()
