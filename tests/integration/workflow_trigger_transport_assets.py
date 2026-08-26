"""为 Workflow Trigger 传输性能门禁准备和清理专用开发资产。

该工具只通过公开 REST API 管理带 ``stage9-transport`` 前缀的资源。性能图会
真实消费输入图片并执行一次 OpenCV grayscale，但只返回小型 JSON，从而把图片
传输、LocalBuffer 物化和首次消费成本与业务模型推理解耦。业务模型链路由独立 soak
工具验证。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import time
from typing import Final

import httpx

from backend.service.infrastructure.filesystem.atomic_files import (
    replace_path_with_retry,
)


ROOT: Final = Path(__file__).resolve().parents[2]
DEFAULT_BASE_URL: Final = "http://127.0.0.1:5600"
DEFAULT_TOKEN: Final = "amvision-default-user-token"
PROJECT_ID: Final = "project-1"
APPLICATION_ID: Final = "stage9-transport-benchmark-app"
TEMPLATE_ID: Final = "stage9-transport-benchmark-template"
TEMPLATE_VERSION: Final = "1.0.0"
OUTPUT_BINDING_ID: Final = "benchmark_result"
SOURCE_PREFIX: Final = "stage9-transport"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """解析命令行。"""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("create", "delete"))
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--token", default=DEFAULT_TOKEN)
    parser.add_argument("--pair-count", type=int, default=8)
    parser.add_argument("--first-zeromq-port", type=int, default=5651)
    parser.add_argument("--output-json", type=Path)
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """执行创建或清理，并输出不含凭证的资源清单。"""

    args = parse_args(argv)
    if args.pair_count <= 0:
        raise ValueError("pair-count 必须大于 0")
    if not 1 <= args.first_zeromq_port <= 65535:
        raise ValueError("first-zeromq-port 不合法")
    if args.first_zeromq_port + args.pair_count - 1 > 65535:
        raise ValueError("ZeroMQ 端口范围越界")
    with httpx.Client(
        base_url=f"{args.base_url.rstrip('/')}/api/v1",
        headers={"Authorization": f"Bearer {args.token}"},
        timeout=httpx.Timeout(args.timeout_seconds),
    ) as client:
        if args.action == "create":
            report = create_assets(
                client,
                pair_count=args.pair_count,
                first_zeromq_port=args.first_zeromq_port,
                timeout_seconds=args.timeout_seconds,
            )
        else:
            report = delete_assets(client)
    if args.output_json is not None:
        _write_json(args.output_json.resolve(), report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def create_assets(
    client: httpx.Client,
    *,
    pair_count: int,
    first_zeromq_port: int,
    timeout_seconds: float,
) -> dict[str, object]:
    """创建不可变版本、独立 Runtime 和两种成对 TriggerSource。"""

    _require_clean_source_prefix(client)
    application_document = _save_benchmark_application(client)
    workflow_app_version_id = _publish_or_reuse_version(
        client,
        application_document=application_document,
    )
    runtimes: list[dict[str, object]] = []
    zeromq_source_ids: list[str] = []
    shared_source_ids: list[str] = []
    try:
        for index in range(pair_count):
            ordinal = index + 1
            runtime = _post_json(
                client,
                "/workflows/app-runtimes",
                {
                    "project_id": PROJECT_ID,
                    "workflow_app_version_id": workflow_app_version_id,
                    "display_name": f"Stage 9 Transport Runtime {ordinal}",
                    "request_timeout_seconds": int(timeout_seconds),
                    "metadata": {
                        "test_asset": True,
                        "asset_kind": "workflow-trigger-transport-benchmark",
                    },
                },
                expected_status=201,
            )
            runtime_id = _required_text(runtime, "workflow_runtime_id")
            runtimes.append(runtime)
            _post_json(
                client,
                f"/workflows/app-runtimes/{runtime_id}/start",
                None,
                expected_status=200,
            )
            zeromq_source_id = f"{SOURCE_PREFIX}-zeromq-{ordinal}"
            shared_source_id = f"{SOURCE_PREFIX}-shared-{ordinal}"
            common = _source_common(runtime_id=runtime_id, ordinal=ordinal)
            _post_json(
                client,
                "/workflows/trigger-sources",
                {
                    **common,
                    "trigger_source_id": zeromq_source_id,
                    "display_name": f"Stage 9 ZeroMQ Transport {ordinal}",
                    "trigger_kind": "zeromq-topic",
                    "transport_config": {
                        "bind_endpoint": (
                            f"tcp://127.0.0.1:{first_zeromq_port + index}"
                        ),
                        "default_input_binding": "request_image_ref",
                        "content_transport": "local-buffer",
                    },
                },
                expected_status=201,
            )
            _post_json(
                client,
                "/workflows/trigger-sources",
                {
                    **common,
                    "trigger_source_id": shared_source_id,
                    "display_name": f"Stage 9 Shared Memory Transport {ordinal}",
                    "trigger_kind": "local-shared-memory",
                    "transport_config": {},
                },
                expected_status=201,
            )
            zeromq_source_ids.append(zeromq_source_id)
            shared_source_ids.append(shared_source_id)
        _wait_ready(
            client,
            runtime_ids=[_required_text(item, "workflow_runtime_id") for item in runtimes],
            source_ids=[*zeromq_source_ids, *shared_source_ids],
            timeout_seconds=timeout_seconds,
        )
    except Exception:
        delete_assets(client)
        raise
    return {
        "format_id": "amvision.workflow-trigger-transport-assets.v1",
        "project_id": PROJECT_ID,
        "application_id": APPLICATION_ID,
        "workflow_app_version_id": workflow_app_version_id,
        "workflow_runtime_ids": [
            _required_text(item, "workflow_runtime_id") for item in runtimes
        ],
        "zeromq_trigger_source_ids": zeromq_source_ids,
        "shared_memory_trigger_source_ids": shared_source_ids,
    }


def delete_assets(client: httpx.Client) -> dict[str, object]:
    """只删除本工具创建的 TriggerSource 和 Runtime；保留可复用的不可变版本。"""

    removed_sources: list[str] = []
    removed_runtimes: list[str] = []
    sources = _get_list(
        client,
        "/workflows/trigger-sources",
        params={"project_id": PROJECT_ID, "limit": 500},
    )
    runtime_ids: set[str] = set()
    for source in sources:
        source_id = str(source.get("trigger_source_id") or "")
        if not source_id.startswith(f"{SOURCE_PREFIX}-"):
            continue
        runtime_id = str(source.get("workflow_runtime_id") or "")
        if runtime_id:
            runtime_ids.add(runtime_id)
        if bool(source.get("enabled")):
            _post_json(
                client,
                f"/workflows/trigger-sources/{source_id}/disable",
                None,
                expected_status=200,
            )
        _delete(client, f"/workflows/trigger-sources/{source_id}")
        removed_sources.append(source_id)
    runtimes = _get_list(
        client,
        "/workflows/app-runtimes",
        params={
            "project_id": PROJECT_ID,
            "application_id": APPLICATION_ID,
            "limit": 500,
        },
    )
    runtime_ids.update(
        str(item.get("workflow_runtime_id") or "")
        for item in runtimes
        if str(item.get("workflow_runtime_id") or "")
    )
    for runtime_id in sorted(runtime_ids):
        runtime = _get_json(client, f"/workflows/app-runtimes/{runtime_id}")
        if str(runtime.get("desired_state") or "") != "stopped":
            _post_json(
                client,
                f"/workflows/app-runtimes/{runtime_id}/stop",
                None,
                expected_status=200,
            )
        _delete(client, f"/workflows/app-runtimes/{runtime_id}")
        removed_runtimes.append(runtime_id)
    return {
        "format_id": "amvision.workflow-trigger-transport-assets-cleanup.v1",
        "removed_trigger_source_ids": removed_sources,
        "removed_workflow_runtime_ids": removed_runtimes,
    }


def _save_benchmark_application(client: httpx.Client) -> dict[str, object]:
    """保存固定、无文件副作用的轻量传输基准图。"""

    template = {
        "format_id": "amvision.workflow-graph-template.v1",
        "template_id": TEMPLATE_ID,
        "template_version": TEMPLATE_VERSION,
        "display_name": "Stage 9 Workflow Trigger Transport Benchmark",
        "description": "消费图片并执行 grayscale；仅返回小型 JSON。",
        "nodes": [
            {
                "node_id": "resolve_image",
                "node_type_id": "core.logic.image-ref-coalesce",
                "parameters": {},
            },
            {
                "node_id": "consume_image",
                "node_type_id": "custom.opencv.grayscale",
                "parameters": {},
            },
            {
                "node_id": "benchmark_result",
                "node_type_id": "core.output.workflow-result",
                "parameters": {
                    "status": "succeeded",
                    "code": 0,
                    "message": "transport benchmark completed",
                },
            },
        ],
        "edges": [
            {
                "edge_id": "edge-input-consumer",
                "source_node_id": "resolve_image",
                "source_port": "image",
                "target_node_id": "consume_image",
                "target_port": "image",
            }
        ],
        "template_inputs": [
            {
                "input_id": "request_image_ref",
                "display_name": "Request Image",
                "payload_type_id": "image-ref.v1",
                "target_node_id": "resolve_image",
                "target_port": "primary",
                "required": True,
            }
        ],
        "template_outputs": [
            {
                "output_id": OUTPUT_BINDING_ID,
                "display_name": "Benchmark Result",
                "payload_type_id": "workflow-result.v1",
                "source_node_id": "benchmark_result",
                "source_port": "workflow_result",
            }
        ],
        "metadata": {
            "test_asset": True,
            "asset_kind": "workflow-trigger-transport-benchmark",
        },
    }
    application = {
        "format_id": "amvision.flow-application.v1",
        "application_id": APPLICATION_ID,
        "display_name": "Stage 9 Workflow Trigger Transport Benchmark",
        "description": "独立测量 ZeroMQ 与本机共享内存图片传输。",
        "template_ref": {
            "template_id": TEMPLATE_ID,
            "template_version": TEMPLATE_VERSION,
            "source_kind": "json-file",
            "source_uri": "tests/integration/workflow_trigger_transport_assets.py",
        },
        "bindings": [
            {
                "binding_id": "request_image_ref",
                "direction": "input",
                "template_port_id": "request_image_ref",
                "binding_kind": "trigger-source-input",
                "required": True,
                "config": {"payload_type_id": "image-ref.v1"},
                "metadata": {"payload_type_id": "image-ref.v1"},
            },
            {
                "binding_id": OUTPUT_BINDING_ID,
                "direction": "output",
                "template_port_id": OUTPUT_BINDING_ID,
                "binding_kind": "http-response",
                "required": True,
                "config": {"payload_type_id": "workflow-result.v1"},
                "metadata": {"payload_type_id": "workflow-result.v1"},
            },
        ],
        "runtime_mode": "python-json-workflow",
        "metadata": {
            "test_asset": True,
            "asset_kind": "workflow-trigger-transport-benchmark",
        },
    }
    return _put_json(
        client,
        f"/workflows/projects/{PROJECT_ID}/applications/{APPLICATION_ID}",
        {"application": application, "template": template},
        expected_status=201,
    )


def _publish_or_reuse_version(
    client: httpx.Client,
    *,
    application_document: dict[str, object],
) -> str:
    """复用相同内容版本；内容变化时发布新的不可变版本。"""

    draft_fingerprint = _required_text(application_document, "draft_fingerprint")
    versions = _get_list(
        client,
        f"/workflows/projects/{PROJECT_ID}/applications/{APPLICATION_ID}/versions",
        params={"limit": 500},
    )
    matching = [
        item
        for item in versions
        if item.get("content_fingerprint") == draft_fingerprint
        and item.get("state") == "published"
    ]
    if matching:
        matching.sort(key=lambda item: int(item.get("version_number") or 0))
        return _required_text(matching[-1], "workflow_app_version_id")
    version = _post_json(
        client,
        f"/workflows/projects/{PROJECT_ID}/applications/{APPLICATION_ID}/versions",
        {
            "expected_draft_fingerprint": draft_fingerprint,
            "release_notes": "Stage 9 transport benchmark contract",
            "display_version": f"stage9-{int(time.time())}",
            "allow_duplicate_content": False,
        },
        expected_status=201,
    )
    return _required_text(version, "workflow_app_version_id")


def _source_common(*, runtime_id: str, ordinal: int) -> dict[str, object]:
    """构造两种 TriggerSource 完全一致的业务契约。"""

    return {
        "project_id": PROJECT_ID,
        "workflow_runtime_id": runtime_id,
        "submit_mode": "sync",
        "enabled": True,
        "match_rule": {},
        "input_binding_mapping": {
            "request_image_ref": {
                "source": "payload.request_image_ref",
                "required": True,
                "payload_type_id": "image-ref.v1",
            }
        },
        "result_mapping": {"result_bindings": [OUTPUT_BINDING_ID]},
        "default_execution_metadata": {
            "workflow_run_record_mode": "none",
            "return_timing_metadata_enabled": True,
            "return_node_timings_enabled": False,
            "trace_level": "none",
            "retain_trace_enabled": False,
            "retain_node_records_enabled": False,
            "retain_input_payload_enabled": False,
            "retain_outputs_enabled": False,
            "benchmark_pair": ordinal,
        },
        "ack_policy": "ack-after-run-finished",
        "result_mode": "sync-reply",
        "reply_timeout_seconds": 60,
        "idempotency_key_path": "payload.idempotency_key",
        "metadata": {
            "test_asset": True,
            "asset_kind": "workflow-trigger-transport-benchmark",
            "benchmark_pair": ordinal,
        },
    }


def _require_clean_source_prefix(client: httpx.Client) -> None:
    """拒绝覆盖残留资源，要求先显式清理。"""

    sources = _get_list(
        client,
        "/workflows/trigger-sources",
        params={"project_id": PROJECT_ID, "limit": 500},
    )
    conflicts = sorted(
        str(item.get("trigger_source_id") or "")
        for item in sources
        if str(item.get("trigger_source_id") or "").startswith(
            f"{SOURCE_PREFIX}-"
        )
    )
    if conflicts:
        raise RuntimeError(
            "存在未清理的 Stage 9 TriggerSource：" + ", ".join(conflicts)
        )


def _wait_ready(
    client: httpx.Client,
    *,
    runtime_ids: list[str],
    source_ids: list[str],
    timeout_seconds: float,
) -> None:
    """等待所有 Runtime 和 TriggerSource 公开健康状态就绪。"""

    deadline = time.monotonic() + timeout_seconds
    recent: dict[str, object] = {}
    while time.monotonic() < deadline:
        ready = True
        recent = {}
        for runtime_id in runtime_ids:
            runtime = _get_json(client, f"/workflows/app-runtimes/{runtime_id}")
            state = str(runtime.get("observed_state") or "")
            recent[runtime_id] = state
            ready = ready and state == "running"
        for source_id in source_ids:
            health = _get_json(
                client, f"/workflows/trigger-sources/{source_id}/health"
            )
            state = str(health.get("observed_state") or "")
            recent[source_id] = state
            ready = ready and state == "running"
        if ready:
            return
        time.sleep(0.2)
    raise RuntimeError(f"Stage 9 资源未在期限内就绪：{recent}")


def _get_json(client: httpx.Client, path: str) -> dict[str, object]:
    response = client.get(path)
    return _require_json_object(response, expected_status=200)


def _get_list(
    client: httpx.Client,
    path: str,
    *,
    params: dict[str, object],
) -> list[dict[str, object]]:
    response = client.get(path, params=params)
    if response.status_code != 200:
        raise RuntimeError(f"GET {path} failed: {response.status_code} {response.text}")
    payload = response.json()
    if not isinstance(payload, list) or not all(
        isinstance(item, dict) for item in payload
    ):
        raise RuntimeError(f"GET {path} 未返回 JSON object array")
    return payload


def _post_json(
    client: httpx.Client,
    path: str,
    payload: dict[str, object] | None,
    *,
    expected_status: int,
) -> dict[str, object]:
    response = client.post(path, json=payload)
    return _require_json_object(response, expected_status=expected_status)


def _put_json(
    client: httpx.Client,
    path: str,
    payload: dict[str, object],
    *,
    expected_status: int,
) -> dict[str, object]:
    response = client.put(path, json=payload)
    return _require_json_object(response, expected_status=expected_status)


def _delete(client: httpx.Client, path: str) -> None:
    response = client.delete(path)
    if response.status_code != 204:
        raise RuntimeError(f"DELETE {path} failed: {response.status_code} {response.text}")


def _require_json_object(
    response: httpx.Response,
    *,
    expected_status: int,
) -> dict[str, object]:
    if response.status_code != expected_status:
        raise RuntimeError(
            f"{response.request.method} {response.request.url.path} failed: "
            f"{response.status_code} {response.text}"
        )
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError("API 未返回 JSON object")
    return payload


def _required_text(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    normalized = value.strip() if isinstance(value, str) else ""
    if not normalized:
        raise RuntimeError(f"API 响应缺少 {key}")
    return normalized


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(f"{path.suffix}.tmp")
    temporary_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    replace_path_with_retry(temporary_path, path)


if __name__ == "__main__":
    raise SystemExit(main())
