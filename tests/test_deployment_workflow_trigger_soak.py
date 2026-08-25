"""Deployment/workflow/trigger 持续负载工具测试。"""

from __future__ import annotations

import base64
import json
import zlib
from dataclasses import replace
from pathlib import Path

import pytest

from tests.integration import deployment_workflow_trigger_soak as soak_module
from tests.integration.deployment_workflow_trigger_soak import (
    LaneMetrics,
    RuntimeSoakConfig,
    _evaluate_result,
    _execute_deployment_async,
    _execute_workflow_invoke,
    _parse_zeromq_result_frames,
    build_lanes,
    run_preflight,
)


def _result_manifest(
    *,
    attachments: list[dict[str, object]] | None = None,
    payloads: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    """构造统一 ZeroMQ Result v1 测试 manifest。"""

    return {
        "format_id": "amvision.workflow-trigger-result.v1",
        "trigger_source_id": "trigger-1",
        "event_id": "event-1",
        "state": "succeeded",
        "workflow_run_id": "run-1",
        "response_payload": {
            "results": {},
            "attachments": attachments or [],
            "payloads": payloads or [],
        },
        "metadata": {},
    }


def _encode_manifest(payload: dict[str, object]) -> bytes:
    """编码测试 manifest。"""

    return json.dumps(payload, separators=(",", ":")).encode("utf-8")


def test_zeromq_soak_parser_accepts_json_only_result() -> None:
    """JSON-only 结果也必须使用统一 Result v1，且不能带未声明帧。"""

    manifest = _result_manifest()

    assert _parse_zeromq_result_frames([_encode_manifest(manifest)]) == manifest


def test_zeromq_soak_parser_accepts_shared_physical_frame() -> None:
    """多个逻辑 attachment 可以共享同一个去重后的物理图片帧。"""

    content = b"encoded-image"
    payload_id = "payload-1"
    manifest = _result_manifest(
        attachments=[
            {
                "attachment_id": "attachment-1",
                "binding_id": "result_image",
                "item_index": 0,
                "payload_id": payload_id,
            },
            {
                "attachment_id": "attachment-2",
                "binding_id": "preview_image",
                "item_index": 0,
                "payload_id": payload_id,
            },
        ],
        payloads=[
            {
                "payload_id": payload_id,
                "delivery_kind": "zeromq-frame",
                "frame_index": 1,
                "media_type": "image/png",
                "content_length": len(content),
                "checksum_algorithm": "crc32",
                "checksum": f"{zlib.crc32(content) & 0xFFFFFFFF:08x}",
            }
        ],
    )

    assert _parse_zeromq_result_frames(
        [_encode_manifest(manifest), content]
    ) == manifest


def _manifest_with_single_image(content: bytes) -> dict[str, object]:
    """构造声明一个图片帧的测试 manifest。"""

    return _result_manifest(
        attachments=[
            {
                "attachment_id": "attachment-1",
                "binding_id": "result_image",
                "item_index": 0,
                "payload_id": "payload-1",
            }
        ],
        payloads=[
            {
                "payload_id": "payload-1",
                "delivery_kind": "zeromq-frame",
                "frame_index": 1,
                "media_type": "image/png",
                "content_length": len(content),
                "checksum_algorithm": "crc32",
                "checksum": f"{zlib.crc32(content) & 0xFFFFFFFF:08x}",
            }
        ],
    )


def test_zeromq_soak_parser_rejects_undeclared_frame() -> None:
    """长期 soak 不能忽略 manifest 未声明的额外二进制帧。"""

    content = b"encoded-image"
    manifest = _manifest_with_single_image(content)

    with pytest.raises(RuntimeError, match="未声明"):
        _parse_zeromq_result_frames(
            [_encode_manifest(manifest), content, b"undeclared"]
        )


def test_zeromq_soak_parser_rejects_corrupt_frame_checksum() -> None:
    """长期 soak 必须检出图片帧 checksum 损坏。"""

    content = b"encoded-image"
    manifest = _manifest_with_single_image(content)
    response_payload = manifest["response_payload"]
    assert isinstance(response_payload, dict)
    payloads = response_payload["payloads"]
    assert isinstance(payloads, list)
    physical = payloads[0]
    assert isinstance(physical, dict)
    physical["checksum"] = "00000000"

    with pytest.raises(RuntimeError, match="checksum"):
        _parse_zeromq_result_frames([_encode_manifest(manifest), content])


class _FakeApiClient:
    """记录 soak helper 的公开 API 调用。"""

    def __init__(self) -> None:
        self.get_calls: list[str] = []
        self.post_calls: list[tuple[str, dict[str, object]]] = []
        self.task_poll_count = 0

    def get(self, path: str, **_kwargs: object) -> dict[str, object]:
        self.get_calls.append(path)
        if path == "/system/health":
            return {"status": "ok"}
        if path.endswith("/sync/health") or path.endswith("/async/health"):
            return {
                "process_state": "running",
                "instance_count": 2,
                "healthy_instance_count": 2,
                "warmed_instance_count": 2,
            }
        if path == "/workflows/app-runtimes/runtime-1/health":
            return {"observed_state": "running"}
        if path == "/workflows/trigger-sources/trigger-1":
            return {
                "trigger_kind": "zeromq-topic",
                "transport_config": {"bind_endpoint": "tcp://127.0.0.1:5858"},
            }
        if path == "/workflows/trigger-sources/trigger-1/health":
            return {
                "observed_state": "running",
                "health_summary": {"adapter_running": True},
            }
        if path == "/models/detection/inference-tasks/task-1":
            self.task_poll_count += 1
            return {"state": "queued" if self.task_poll_count == 1 else "succeeded"}
        if path == "/models/detection/inference-tasks/task-1/result":
            return {"status": "succeeded", "predictions": []}
        raise AssertionError(f"未处理的 GET: {path}")

    def post(self, path: str, **kwargs: object) -> dict[str, object]:
        self.post_calls.append((path, kwargs))
        if path == "/models/detection/deployment-instances/deployment-1/infer":
            return {"status": "succeeded", "predictions": []}
        if path == "/models/detection/inference-tasks":
            return {"task_id": "task-1"}
        if path == "/workflows/app-runtimes/runtime-1/invoke":
            return {"state": "succeeded", "workflow_run_id": "run-1"}
        raise AssertionError(f"未处理的 POST: {path}")


def _build_config(tmp_path: Path) -> RuntimeSoakConfig:
    return RuntimeSoakConfig(
        base_url="http://127.0.0.1:5600",
        token="test-token",
        project_id="project-1",
        duration_seconds=1.0,
        concurrency_per_lane=1,
        request_interval_seconds=0.0,
        sample_interval_seconds=1.0,
        http_timeout_seconds=5.0,
        task_timeout_seconds=5.0,
        async_poll_interval_seconds=0.001,
        max_error_rate=0.0,
        minimum_requests_per_lane=1,
        output_dir=tmp_path,
        deployment_instance_id="deployment-1",
        deployment_task_type="detection",
        deployment_model_type="yolov8",
        deployment_image_path=tmp_path / "sample.png",
        workflow_runtime_id="runtime-1",
        workflow_request={
            "input_bindings": {
                "value": {"value": 1},
                "request_image_ref": {
                    "transport_kind": "storage",
                    "object_key": "developer/image.bmp",
                },
            }
        },
        workflow_image_path=tmp_path / "sample.png",
        trigger_source_id="trigger-1",
    )


def test_runtime_soak_cli_requires_real_workflow_image_and_defaults_to_base64(
    tmp_path: Path,
) -> None:
    """验证 HTTP Workflow lane 不能退回本地路径输入。"""

    with pytest.raises(SystemExit):
        soak_module.parse_args(["--workflow-runtime-id", "runtime-1"])

    image_path = tmp_path / "camera.bmp"
    image_path.write_bytes(b"bmp")
    args = soak_module.parse_args(
        [
            "--workflow-runtime-id",
            "runtime-1",
            "--workflow-image",
            str(image_path),
        ]
    )

    assert args.workflow_image == image_path
    assert args.workflow_image_binding_id == "request_image_base64"


def test_runtime_soak_preflight_resolves_all_running_lanes(tmp_path: Path) -> None:
    """验证预检覆盖 sync/async deployment、workflow 和 TriggerSource。"""

    config = _build_config(tmp_path)
    client = _FakeApiClient()

    resolved_config, preflight = run_preflight(config, client)  # type: ignore[arg-type]

    assert resolved_config.trigger_endpoint == "tcp://127.0.0.1:5858"
    assert set(preflight["deployment"]) == {"sync", "async"}  # type: ignore[arg-type]
    assert preflight["workflow_runtime"] == {"observed_state": "running"}
    assert preflight["trigger_endpoint"] == "tcp://127.0.0.1:5858"
    assert [lane.name for lane in build_lanes(resolved_config)] == [
        "deployment-sync",
        "deployment-async",
        "workflow-invoke",
        "trigger-zeromq",
    ]


def test_runtime_soak_async_and_workflow_operations_use_public_api(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证异步推理会轮询结果，workflow invoke 会补充 soak 元数据。"""

    config = _build_config(tmp_path)
    client = _FakeApiClient()
    monkeypatch.setattr(
        "tests.integration.deployment_workflow_trigger_soak.time.sleep",
        lambda _seconds: None,
    )

    _execute_deployment_async(
        config=config,
        api_client=client,  # type: ignore[arg-type]
        image_bytes=b"png",
    )
    _execute_workflow_invoke(
        config=config,
        api_client=client,  # type: ignore[arg-type]
        sequence=7,
        worker_index=2,
        image_bytes=b"camera-frame",
    )

    assert client.task_poll_count == 2
    assert client.get_calls[-1] == "/models/detection/inference-tasks/task-1/result"
    workflow_call = client.post_calls[-1]
    assert workflow_call[0] == "/workflows/app-runtimes/runtime-1/invoke"
    request = workflow_call[1]["json"]
    assert isinstance(request, dict)
    assert request["execution_metadata"] == {
        "scenario": "deployment-workflow-trigger-soak",
        "soak_sequence": 7,
        "soak_worker_index": 2,
    }
    input_bindings = request["input_bindings"]
    assert isinstance(input_bindings, dict)
    assert "request_image_ref" not in input_bindings
    assert input_bindings["request_image_base64"] == {
        "image_base64": base64.b64encode(b"camera-frame").decode("ascii"),
        "media_type": "image/png",
    }


def test_runtime_soak_metrics_gate_counts_errors_and_latency(tmp_path: Path) -> None:
    """验证结果门禁按每条 lane 的最小请求量和错误率判定。"""

    config = _build_config(tmp_path)
    metrics = LaneMetrics(name="workflow-invoke")
    metrics.begin()
    metrics.finish(latency_ms=10.0, error=None)
    metrics.begin()
    metrics.finish(latency_ms=30.0, error=RuntimeError("failed"))

    snapshot = metrics.snapshot()
    assert snapshot["started_count"] == 2
    assert snapshot["success_count"] == 1
    assert snapshot["error_count"] == 1
    assert snapshot["error_rate"] == 0.5
    assert snapshot["latency_ms"] == {
        "min": 10.0,
        "mean": 20.0,
        "p50": 20.0,
        "p95": 29.0,
        "p99": 29.8,
        "max": 30.0,
    }
    failures = _evaluate_result(
        config=config,
        metrics={metrics.name: metrics},
        monitor_errors=[],
    )
    assert failures == ["workflow-invoke 错误率超限: 0.50000000 > 0.00000000"]


def test_runtime_soak_can_select_only_running_deployment_mode(tmp_path: Path) -> None:
    """验证现场只启动 sync runtime 时可单独选择 sync 负载。"""

    config = replace(_build_config(tmp_path), deployment_runtime_modes=("sync",))
    client = _FakeApiClient()

    _resolved_config, preflight = run_preflight(config, client)  # type: ignore[arg-type]

    assert set(preflight["deployment"]) == {"sync"}  # type: ignore[arg-type]
    assert "/models/detection/deployment-instances/deployment-1/async/health" not in (
        client.get_calls
    )
    assert [lane.name for lane in build_lanes(config)] == [
        "deployment-sync",
        "workflow-invoke",
        "trigger-zeromq",
    ]


def test_runtime_soak_preflight_rejects_cold_deployment(
    tmp_path: Path,
) -> None:
    """验证持续负载不会把未预热实例的冷启动误算成业务延迟。"""

    config = replace(_build_config(tmp_path), deployment_runtime_modes=("sync",))
    client = _FakeApiClient()
    original_get = client.get

    def get_with_cold_deployment(path: str, **kwargs: object) -> dict[str, object]:
        if path.endswith("/sync/health"):
            return {
                "process_state": "running",
                "instance_count": 2,
                "healthy_instance_count": 2,
                "warmed_instance_count": 0,
            }
        return original_get(path, **kwargs)

    client.get = get_with_cold_deployment  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="尚未完成全部实例预热"):
        run_preflight(config, client)  # type: ignore[arg-type]


def test_runtime_soak_runner_writes_successful_four_lane_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """验证 runner 会并行执行四条 lane、采样 health 并原子落结果。"""

    sample_path = tmp_path / "sample.png"
    sample_path.write_bytes(b"png")
    config = replace(
        _build_config(tmp_path),
        duration_seconds=0.12,
        request_interval_seconds=0.005,
        sample_interval_seconds=0.03,
        trigger_endpoint="tcp://127.0.0.1:5858",
    )
    client = _FakeApiClient()

    class _FakeApiContext:
        def __enter__(self) -> _FakeApiClient:
            return client

        def __exit__(self, *_args: object) -> None:
            return None

    class _FakeZeroMqClient:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def close(self) -> None:
            pass

        def send(self, _frames: list[bytes]) -> dict[str, object]:
            return {"state": "succeeded"}

    monkeypatch.setattr(soak_module, "_api_client", lambda _config: _FakeApiContext())
    monkeypatch.setattr(soak_module, "ZeroMqSoakClient", _FakeZeroMqClient)

    exit_code = soak_module.run_soak(config)

    assert exit_code == 0
    result = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
    assert result["status"] == "succeeded"
    assert set(result["lanes"]) == {
        "deployment-sync",
        "deployment-async",
        "workflow-invoke",
        "trigger-zeromq",
    }
    assert all(item["success_count"] >= 1 for item in result["lanes"].values())
    assert len(result["health_samples"]) >= 2

    console_summary = json.loads(capsys.readouterr().out)
    assert console_summary["status"] == "succeeded"
    assert console_summary["result_path"] == str(tmp_path / "result.json")
    assert console_summary["health_sample_count"] == len(result["health_samples"])
    assert "health_samples" not in console_summary
