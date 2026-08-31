"""从显式 baseline manifest 通过公开 REST API 重建开发期 Workflow 资源。"""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import re
import time
from typing import Any

import httpx


_MANIFEST_FORMAT_ID = "amvision.workflow-development-baseline.v1"
_APP_ID_PATTERN = re.compile(r"^workflow-app-\d{14}$")
_GRAPH_ID_PATTERN = re.compile(r"^workflow-graph-\d{14}$")
_RUNTIME_ID_PATTERN = re.compile(r"^workflow-runtime-[0-9a-f]{32}$")
_HIGH_PERFORMANCE_INPUT_IDS = (
    "request_image_ref",
    "request_json",
    "request_text",
)


def build_argument_parser() -> argparse.ArgumentParser:
    """构造命令行参数。"""

    parser = argparse.ArgumentParser(
        description="从受控 manifest 重建 Workflow App、v1、Runtime 和 Trigger"
    )
    parser.add_argument("--manifest", required=True, help="baseline manifest JSON 路径")
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:5600/api/v1",
        help="backend REST API v1 根地址",
    )
    parser.add_argument(
        "--access-token-env",
        default="AMVISION_ACCESS_TOKEN",
        help="读取 Bearer token 的环境变量名",
    )
    parser.add_argument(
        "--start-timestamp",
        default=None,
        help="第一个 App/Graph 使用的 14 位时间；默认使用当前本地时间",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=600.0,
        help="单次 HTTP 和 Runtime 就绪等待上限",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="只校验 manifest 和 baseline 文档，不连接 backend",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """执行开发期 Workflow baseline 重建。"""

    args = build_argument_parser().parse_args(argv)
    manifest_path = Path(args.manifest).resolve()
    manifest = _load_manifest(manifest_path)
    plans = build_rebuild_plans(
        manifest=manifest,
        manifest_path=manifest_path,
        start_timestamp=args.start_timestamp,
    )
    if args.validate_only:
        print(
            json.dumps(
                {
                    "format_id": _MANIFEST_FORMAT_ID,
                    "valid": True,
                    "plans": [_public_plan(plan) for plan in plans],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    access_token = os.environ.get(args.access_token_env, "").strip()
    if not access_token:
        raise RuntimeError(f"环境变量 {args.access_token_env} 未提供 Bearer token")
    headers = {"Authorization": f"Bearer {access_token}"}
    with httpx.Client(
        base_url=args.base_url.rstrip("/"),
        headers=headers,
        timeout=args.timeout_seconds,
    ) as client:
        _require_empty_workflow_state(client, project_id=str(manifest["project_id"]))
        results = [
            _create_plan_resources(
                client,
                project_id=str(manifest["project_id"]),
                plan=plan,
                timeout_seconds=args.timeout_seconds,
            )
            for plan in plans
        ]
    print(
        json.dumps(
            {
                "format_id": _MANIFEST_FORMAT_ID,
                "project_id": manifest["project_id"],
                "results": results,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def build_rebuild_plans(
    *,
    manifest: dict[str, Any],
    manifest_path: Path,
    start_timestamp: str | None,
) -> list[dict[str, Any]]:
    """读取 baseline 文件并生成确定性的重建计划。"""

    first_time = _parse_start_time(start_timestamp)
    manifest_root = manifest_path.parent
    plans: list[dict[str, Any]] = []
    used_ports: set[int] = set()
    for index, item in enumerate(manifest["applications"]):
        if not isinstance(item, dict):
            raise ValueError("applications 的每一项必须是 JSON object")
        source_dir_text = _required_text(item, "source_dir")
        source_dir = (manifest_root / source_dir_text).resolve()
        if not source_dir.is_relative_to(manifest_root):
            raise ValueError(f"baseline source_dir 越过 manifest 目录: {source_dir}")
        application = _read_json_object(source_dir / "application.json")
        template = _read_json_object(source_dir / "template.json")
        timestamp = (first_time + timedelta(seconds=index)).strftime("%Y%m%d%H%M%S")
        application_id = f"workflow-app-{timestamp}"
        template_id = f"workflow-graph-{timestamp}"
        display_name = _required_text(item, "display_name")
        description = str(item.get("description") or "").strip()
        zeromq_port = int(item.get("zeromq_port") or 0)
        if zeromq_port <= 0 or zeromq_port > 65535:
            raise ValueError(f"zeromq_port 无效: {zeromq_port}")
        if zeromq_port in used_ports:
            raise ValueError(f"zeromq_port 重复: {zeromq_port}")
        used_ports.add(zeromq_port)

        old_application_id = _required_text(application, "application_id")
        old_template_id = _required_text(template, "template_id")
        if application.get("format_id") != "amvision.flow-application.v1":
            raise ValueError(f"Application 不是 v1: {source_dir}")
        if template.get("format_id") != "amvision.workflow-graph-template.v1":
            raise ValueError(f"Template 不是 v1: {source_dir}")

        replacements = {
            old_application_id: application_id,
            old_template_id: template_id,
        }
        application = _replace_strings(deepcopy(application), replacements)
        template = _replace_strings(deepcopy(template), replacements)
        application["application_id"] = application_id
        application["display_name"] = display_name
        application["description"] = description
        template["template_id"] = template_id
        template["template_version"] = "1.0.0"
        template["display_name"] = display_name
        template["description"] = description
        template_ref = application.get("template_ref")
        if not isinstance(template_ref, dict):
            raise ValueError(f"Application 缺少 template_ref: {source_dir}")
        template_ref.update(
            {
                "template_id": template_id,
                "template_version": "1.0.0",
                "source_kind": "json-file",
                "source_uri": (
                    f"workflows/projects/{manifest['project_id']}/templates/"
                    f"{template_id}/versions/1.0.0/template.json"
                ),
            }
        )
        plans.append(
            {
                "application_id": application_id,
                "template_id": template_id,
                "display_name": display_name,
                "runtime_display_name": str(
                    item.get("runtime_display_name") or f"{display_name} Runtime"
                ).strip(),
                "zeromq_port": zeromq_port,
                "application": application,
                "template": template,
            }
        )
    return plans


def _create_plan_resources(
    client: httpx.Client,
    *,
    project_id: str,
    plan: dict[str, Any],
    timeout_seconds: float,
) -> dict[str, Any]:
    """按 App、v1、Runtime、Trigger 的固定顺序创建一套资源。"""

    application_id = str(plan["application_id"])
    document = _request_json(
        client,
        "PUT",
        f"/workflows/projects/{project_id}/applications/{application_id}",
        json_body={
            "application": plan["application"],
            "template": plan["template"],
        },
        expected_status=201,
    )
    draft_fingerprint = _required_text(document, "draft_fingerprint")
    version = _request_json(
        client,
        "POST",
        f"/workflows/projects/{project_id}/applications/{application_id}/versions",
        json_body={
            "expected_draft_fingerprint": draft_fingerprint,
            "release_notes": "开发期历史清理后的正式发布基线 v1",
            "allow_duplicate_content": False,
        },
        expected_status=201,
    )
    if int(version.get("version_number") or 0) != 1:
        raise RuntimeError(f"{application_id} 首次发布不是 version_number=1")
    if version.get("display_version") != "v1":
        raise RuntimeError(f"{application_id} 首次发布不是 display_version=v1")
    version_id = _required_text(version, "workflow_app_version_id")
    runtime = _request_json(
        client,
        "POST",
        "/workflows/app-runtimes",
        json_body={
            "project_id": project_id,
            "workflow_app_version_id": version_id,
            "display_name": plan["runtime_display_name"],
            "request_timeout_seconds": 60,
            "metadata": {"baseline": "production-v1"},
        },
        expected_status=201,
    )
    runtime_id = _required_text(runtime, "workflow_runtime_id")
    if _RUNTIME_ID_PATTERN.fullmatch(runtime_id) is None:
        raise RuntimeError(f"Runtime id 不符合标准: {runtime_id}")
    _request_json(
        client,
        "POST",
        f"/workflows/app-runtimes/{runtime_id}/start",
        json_body=None,
        expected_status=200,
    )
    _wait_state(
        client,
        resource_path=f"/workflows/app-runtimes/{runtime_id}",
        expected_state="running",
        timeout_seconds=timeout_seconds,
    )

    input_mapping = _build_high_performance_input_mapping(plan["application"])
    output_ids = _list_output_binding_ids(plan["application"])
    common = {
        "project_id": project_id,
        "workflow_runtime_id": runtime_id,
        "submit_mode": "sync",
        "enabled": True,
        "match_rule": {},
        "input_binding_mapping": input_mapping,
        "result_mapping": {"result_bindings": output_ids},
        "default_execution_metadata": {
            "workflow_run_record_mode": "none",
            "return_timing_metadata_enabled": False,
            "return_node_timings_enabled": False,
            "trace_level": "none",
            "retain_trace_enabled": False,
            "retain_node_records_enabled": False,
            "retain_input_payload_enabled": False,
            "retain_outputs_enabled": False,
        },
        "ack_policy": "ack-after-run-finished",
        "result_mode": "sync-reply",
        "reply_timeout_seconds": 60,
        "idempotency_key_path": "payload.idempotency_key",
        "metadata": {
            "baseline": "production-v1",
            "application_id": application_id,
        },
    }
    zeromq_id = f"zeromq-{runtime_id}"
    shared_id = f"local-shared-memory-{runtime_id}"
    _request_json(
        client,
        "POST",
        "/workflows/trigger-sources",
        json_body={
            **common,
            "trigger_source_id": zeromq_id,
            "display_name": f"{plan['display_name']} ZeroMQ Trigger",
            "trigger_kind": "zeromq-topic",
            "transport_config": {
                "bind_endpoint": f"tcp://127.0.0.1:{plan['zeromq_port']}",
                "default_input_binding": "request_image_ref",
                "content_transport": "local-buffer",
            },
        },
        expected_status=201,
    )
    _request_json(
        client,
        "POST",
        "/workflows/trigger-sources",
        json_body={
            **common,
            "trigger_source_id": shared_id,
            "display_name": f"{plan['display_name']} Local Shared Memory Trigger",
            "trigger_kind": "local-shared-memory",
            "transport_config": {},
        },
        expected_status=201,
    )
    for trigger_id in (zeromq_id, shared_id):
        _wait_state(
            client,
            resource_path=f"/workflows/trigger-sources/{trigger_id}",
            expected_state="running",
            timeout_seconds=timeout_seconds,
        )
    return {
        "application_id": application_id,
        "template_id": plan["template_id"],
        "workflow_app_version_id": version_id,
        "display_version": version["display_version"],
        "workflow_runtime_id": runtime_id,
        "trigger_source_ids": [zeromq_id, shared_id],
        "zeromq_endpoint": f"tcp://127.0.0.1:{plan['zeromq_port']}",
        "high_performance_input_ids": list(input_mapping),
        "result_binding_ids": output_ids,
    }


def _build_high_performance_input_mapping(
    application: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """只为 image-ref、JSON、文本生成高性能 Trigger 映射。"""

    bindings = application.get("bindings")
    if not isinstance(bindings, list):
        raise ValueError("Application bindings 必须是数组")
    by_id = {
        str(item.get("binding_id")): item
        for item in bindings
        if isinstance(item, dict) and item.get("direction") == "input"
    }
    mapping: dict[str, dict[str, Any]] = {}
    for binding_id in _HIGH_PERFORMANCE_INPUT_IDS:
        binding = by_id.get(binding_id)
        if binding is None:
            continue
        config = binding.get("config")
        metadata = binding.get("metadata")
        payload_type_id = None
        if isinstance(config, dict):
            payload_type_id = config.get("payload_type_id")
        if not payload_type_id and isinstance(metadata, dict):
            payload_type_id = metadata.get("payload_type_id")
        mapping[binding_id] = {
            "source": f"payload.{binding_id}",
            "required": bool(binding.get("required", False)),
            "payload_type_id": str(payload_type_id or "value.v1"),
        }
    if "request_image_ref" not in mapping:
        raise ValueError("正式高性能 Trigger 要求 Application 公开 request_image_ref")
    return mapping


def _list_output_binding_ids(application: dict[str, Any]) -> list[str]:
    """读取 Application 公开输出绑定 id。"""

    bindings = application.get("bindings")
    output_ids = [
        str(item.get("binding_id"))
        for item in bindings
        if isinstance(item, dict)
        and item.get("direction") == "output"
        and isinstance(item.get("binding_id"), str)
        and str(item["binding_id"]).strip()
    ]
    if not output_ids:
        raise ValueError("Application 至少需要一个公开输出")
    return output_ids


def _require_empty_workflow_state(client: httpx.Client, *, project_id: str) -> None:
    """要求重建前公开 Workflow 资源为空，避免叠加历史状态。"""

    resources = {
        "applications": _request_json(
            client,
            "GET",
            f"/workflows/projects/{project_id}/applications?limit=500",
            expected_status=200,
        ),
        "app_runtimes": _request_json(
            client,
            "GET",
            f"/workflows/app-runtimes?project_id={project_id}&limit=500",
            expected_status=200,
        ),
        "trigger_sources": _request_json(
            client,
            "GET",
            f"/workflows/trigger-sources?project_id={project_id}&limit=500",
            expected_status=200,
        ),
    }
    non_empty = {
        key: len(value) for key, value in resources.items() if isinstance(value, list) and value
    }
    if non_empty:
        raise RuntimeError(f"重建前 Workflow 公开资源不是空状态: {non_empty}")


def _wait_state(
    client: httpx.Client,
    *,
    resource_path: str,
    expected_state: str,
    timeout_seconds: float,
) -> None:
    """等待 Runtime 或 Trigger 达到指定 observed_state。"""

    deadline = time.monotonic() + timeout_seconds
    latest: dict[str, Any] = {}
    while time.monotonic() < deadline:
        latest = _request_json(client, "GET", resource_path, expected_status=200)
        if latest.get("observed_state") == expected_state:
            return
        if latest.get("observed_state") == "failed":
            raise RuntimeError(f"资源进入 failed: {resource_path}: {latest.get('last_error')}")
        time.sleep(0.2)
    raise TimeoutError(
        f"等待资源状态超时: {resource_path}, expected={expected_state}, latest={latest}"
    )


def _request_json(
    client: httpx.Client,
    method: str,
    path: str,
    *,
    json_body: dict[str, Any] | None = None,
    expected_status: int,
) -> Any:
    """发送 JSON 请求并执行严格状态码检查。"""

    response = client.request(method, path, json=json_body)
    if response.status_code != expected_status:
        raise RuntimeError(
            f"REST 请求失败: {method} {path}, status={response.status_code}, "
            f"body={response.text[:4000]}"
        )
    return response.json()


def _load_manifest(path: Path) -> dict[str, Any]:
    """读取并验证 baseline manifest 顶层结构。"""

    manifest = _read_json_object(path)
    if manifest.get("format_id") != _MANIFEST_FORMAT_ID:
        raise ValueError(f"baseline manifest format_id 必须是 {_MANIFEST_FORMAT_ID}")
    _required_text(manifest, "project_id")
    applications = manifest.get("applications")
    if not isinstance(applications, list) or not applications:
        raise ValueError("baseline manifest applications 必须是非空数组")
    return manifest


def _read_json_object(path: Path) -> dict[str, Any]:
    """读取 UTF-8 JSON object。"""

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON 顶层必须是 object: {path}")
    return payload


def _replace_strings(value: Any, replacements: dict[str, str]) -> Any:
    """递归替换 baseline 文档中的旧 App/Graph id。"""

    if isinstance(value, str):
        result = value
        for source, target in replacements.items():
            result = result.replace(source, target)
        return result
    if isinstance(value, list):
        return [_replace_strings(item, replacements) for item in value]
    if isinstance(value, dict):
        return {key: _replace_strings(item, replacements) for key, item in value.items()}
    return value


def _parse_start_time(value: str | None) -> datetime:
    """解析首个 14 位时间，未指定时使用本地当前时间。"""

    if value is None:
        return datetime.now()
    try:
        return datetime.strptime(value, "%Y%m%d%H%M%S")
    except ValueError as error:
        raise ValueError("start-timestamp 必须是 14 位 YYYYMMDDHHMMSS") from error


def _required_text(payload: dict[str, Any], field_name: str) -> str:
    """读取必填非空文本字段。"""

    value = payload.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"缺少非空字段: {field_name}")
    return value.strip()


def _public_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """构造不展开节点文档的计划摘要。"""

    application_id = str(plan["application_id"])
    template_id = str(plan["template_id"])
    if _APP_ID_PATTERN.fullmatch(application_id) is None:
        raise ValueError(f"App id 不符合标准: {application_id}")
    if _GRAPH_ID_PATTERN.fullmatch(template_id) is None:
        raise ValueError(f"Graph id 不符合标准: {template_id}")
    return {
        "application_id": application_id,
        "template_id": template_id,
        "display_name": plan["display_name"],
        "runtime_display_name": plan["runtime_display_name"],
        "zeromq_port": plan["zeromq_port"],
        "node_count": len(plan["template"].get("nodes") or []),
        "edge_count": len(plan["template"].get("edges") or []),
        "high_performance_input_ids": list(
            _build_high_performance_input_mapping(plan["application"])
        ),
        "result_binding_ids": _list_output_binding_ids(plan["application"]),
    }


if __name__ == "__main__":
    raise SystemExit(main())
