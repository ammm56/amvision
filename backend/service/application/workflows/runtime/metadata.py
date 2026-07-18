"""Workflow runtime 时间、诊断和持久化 metadata 工具。"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from time import monotonic

from backend.service.application.errors import ServiceError
from backend.service.application.workflows.runtime.policies import (
    should_return_workflow_node_timings,
    should_return_workflow_timing_metadata,
)
from backend.service.application.workflows.runtime_payload_sanitizer import (
    sanitize_runtime_mapping,
)
from backend.service.domain.workflows.workflow_runtime_records import (
    WorkflowAppRuntime,
    WorkflowExecutionPolicy,
    WorkflowRun,
)


def now_isoformat() -> str:
    """返回当前 UTC 时间的 ISO8601 文本。"""

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def normalize_optional_str(value: str | None) -> str | None:
    """规范化可选字符串字段。"""

    if value is None:
        return None
    normalized_value = value.strip()
    return normalized_value or None


def build_runtime_default_execution_metadata(
    workflow_app_runtime: WorkflowAppRuntime,
) -> dict[str, object]:
    """读取 WorkflowAppRuntime 上配置的默认执行元数据。"""

    raw_metadata = workflow_app_runtime.metadata.get("default_execution_metadata")
    if isinstance(raw_metadata, dict):
        return dict(raw_metadata)
    return {}


def build_minimal_workflow_run_record(workflow_run: WorkflowRun) -> WorkflowRun:
    """构造高速触发模式使用的最小 WorkflowRun 记录。"""

    return replace(
        workflow_run,
        input_payload={},
        outputs={},
        template_outputs={},
        node_records=(),
        metadata=dict(workflow_run.metadata),
    )


def should_run_preview_inline(metadata: dict[str, object]) -> bool:
    """判断 Preview Run 是否应走当前进程直接执行路径。"""

    raw_mode = metadata.get("preview_execution_mode")
    if isinstance(raw_mode, str):
        normalized_mode = raw_mode.strip().lower()
        if normalized_mode in {"inline", "direct"}:
            return True
        if normalized_mode in {"process", "subprocess"}:
            return False
    return metadata.get("source") == "workflow-graph-workbench"


def merge_preview_run_inline_metadata(
    metadata: dict[str, object],
    *,
    inline_duration_ms: float | None = None,
) -> dict[str, object]:
    """给 PreviewRun metadata 标记当前使用的直接执行模式。"""

    payload = dict(metadata)
    payload["preview_execution_mode"] = "inline"
    if inline_duration_ms is not None:
        timings = payload.get("timings")
        timings_payload = dict(timings) if isinstance(timings, dict) else {}
        timings_payload["preview_inline_total_ms"] = inline_duration_ms
        payload["timings"] = timings_payload
    return payload


def build_preview_run_error_metadata(
    metadata: dict[str, object],
    *,
    error: ServiceError,
) -> dict[str, object]:
    """构造 PreviewRun 失败 metadata。"""

    payload = dict(metadata)
    payload["last_error"] = {
        "code": error.code,
        "message": error.message,
        "details": sanitize_runtime_mapping(error.details),
    }
    return payload


def strip_output_diagnostic_timings(
    value: object,
    *,
    return_timings_enabled: bool,
) -> object:
    """按诊断开关移除业务输出里嵌套的 metadata.timings。"""

    if return_timings_enabled:
        if isinstance(value, dict):
            return dict(value)
        return value
    if isinstance(value, dict):
        cleaned: dict[str, object] = {}
        for key, child_value in value.items():
            if key == "metadata" and isinstance(child_value, dict):
                child_metadata = dict(child_value)
                child_metadata.pop("timings", None)
                child_metadata.pop("node_timings", None)
                cleaned[key] = strip_output_diagnostic_timings(
                    child_metadata,
                    return_timings_enabled=return_timings_enabled,
                )
                continue
            cleaned[str(key)] = strip_output_diagnostic_timings(
                child_value,
                return_timings_enabled=return_timings_enabled,
            )
        return cleaned
    if isinstance(value, list):
        return [
            strip_output_diagnostic_timings(
                item,
                return_timings_enabled=return_timings_enabled,
            )
            for item in value
        ]
    if isinstance(value, tuple):
        return tuple(
            strip_output_diagnostic_timings(
                item,
                return_timings_enabled=return_timings_enabled,
            )
            for item in value
        )
    return value


def resolve_preview_retain_node_records_enabled(
    metadata: dict[str, object],
    *,
    execution_policy: WorkflowExecutionPolicy | None,
) -> bool:
    """解析 Preview Run 是否需要保留完整 node_records。"""

    explicit_value = read_optional_bool_flag(metadata.get("retain_node_records_enabled"))
    if explicit_value is not None:
        return explicit_value
    return True if execution_policy is None else execution_policy.retain_node_records_enabled


def elapsed_ms(started_at: float) -> float:
    """把 monotonic 起点转换为毫秒耗时。"""

    return round((monotonic() - started_at) * 1000.0, 3)


def should_retain_runtime_payload(metadata: dict[str, object], key: str) -> bool:
    """读取 runtime 调用里的持久化 payload 开关，默认保留。"""

    return read_optional_bool_flag(metadata.get(key)) is not False


def merge_workflow_run_timing_metadata(
    metadata: dict[str, object],
    timing_payload: dict[str, object],
) -> dict[str, object]:
    """把本次调用计时合并进 WorkflowRun metadata。"""

    payload = dict(metadata)
    existing_timings = payload.get("timings")
    timings = dict(existing_timings) if isinstance(existing_timings, dict) else {}
    for key, value in timing_payload.items():
        if isinstance(value, bool):
            timings[str(key)] = value
            continue
        if isinstance(value, int | float | str) or value is None:
            timings[str(key)] = value
    payload["timings"] = timings
    return payload


def merge_workflow_run_diagnostic_metadata(
    metadata: dict[str, object],
    timing_payload: dict[str, object],
    *,
    node_timings: tuple[dict[str, object], ...] = (),
) -> dict[str, object]:
    """合并 WorkflowRun 的计时和轻量节点耗时诊断。"""

    payload = dict(metadata)
    if should_return_workflow_timing_metadata(payload):
        payload = merge_workflow_run_timing_metadata(payload, timing_payload)
    if node_timings and should_return_workflow_node_timings(payload):
        payload["node_timings"] = [dict(item) for item in node_timings]
    return payload


def build_compact_node_timings(
    node_records: tuple[dict[str, object], ...],
) -> tuple[dict[str, object], ...]:
    """从 node_records 提取不包含 inputs/outputs 的轻量节点耗时摘要。"""

    timings: list[dict[str, object]] = []
    for item in node_records:
        node_id = item.get("node_id")
        node_type_id = item.get("node_type_id")
        runtime_kind = item.get("runtime_kind")
        if not isinstance(node_id, str) or not node_id:
            continue
        timing: dict[str, object] = {"node_id": node_id}
        if isinstance(node_type_id, str) and node_type_id:
            timing["node_type_id"] = node_type_id
        if isinstance(runtime_kind, str) and runtime_kind:
            timing["runtime_kind"] = runtime_kind
        duration_ms = item.get("duration_ms")
        if isinstance(duration_ms, bool):
            duration_ms = None
        if isinstance(duration_ms, int | float):
            timing["duration_ms"] = float(duration_ms)
        timings.append(timing)
    return tuple(timings)


def read_optional_bool_flag(value: object) -> bool | None:
    """读取可由 JSON 或文本传入的布尔开关。"""

    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized_value = value.strip().lower()
        if normalized_value in {"true", "1", "yes", "on"}:
            return True
        if normalized_value in {"false", "0", "no", "off"}:
            return False
    return None


__all__ = [
    "build_compact_node_timings",
    "build_minimal_workflow_run_record",
    "build_preview_run_error_metadata",
    "build_runtime_default_execution_metadata",
    "elapsed_ms",
    "merge_preview_run_inline_metadata",
    "merge_workflow_run_diagnostic_metadata",
    "normalize_optional_str",
    "now_isoformat",
    "resolve_preview_retain_node_records_enabled",
    "should_retain_runtime_payload",
    "should_run_preview_inline",
    "strip_output_diagnostic_timings",
]
