"""Task 失败事件 payload 构造工具。"""

from __future__ import annotations

from collections.abc import Mapping

from backend.service.application.error_serialization import serialize_error


def build_task_failure_payload(
    error: BaseException,
    *,
    finished_at: str | None = None,
    attempt_no: int | None = None,
    progress: Mapping[str, object] | None = None,
    metadata: Mapping[str, object] | None = None,
    result: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """构造统一的 Task failed event payload。

    参数：
    - error：触发失败的异常。
    - finished_at：失败完成时间。
    - attempt_no：执行尝试次数。
    - progress：失败时的进度快照。
    - metadata：附加元数据。
    - result：任务结果快照。
    """

    error_payload = serialize_error(error)
    payload: dict[str, object] = {
        "state": "failed",
        "error_message": error_payload.get("error_message", str(error)),
        "error": error_payload,
        "error_details": error_payload.get("details", {}),
    }
    if finished_at is not None:
        payload["finished_at"] = finished_at
    if attempt_no is not None:
        payload["attempt_no"] = attempt_no
    if progress is not None:
        payload["progress"] = dict(progress)
    if metadata is not None:
        merged_metadata = dict(metadata)
        merged_metadata["error"] = error_payload
        payload["metadata"] = merged_metadata
    if result is not None:
        merged_result = dict(result)
        merged_result["error"] = error_payload
        merged_result["error_details"] = error_payload.get("details", {})
        payload["result"] = merged_result
    return payload


def build_task_failure_payload_from_message(
    *,
    error_message: str,
    error: BaseException | None = None,
    finished_at: str | None = None,
    attempt_no: int | None = None,
    progress: Mapping[str, object] | None = None,
    metadata: Mapping[str, object] | None = None,
    result: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """基于旧 error_message 调用点构造统一 failed payload。

    参数：
    - error_message：旧调用点已经生成的错误文本。
    - error：原始异常；存在时保留 ServiceError.details 等结构化诊断。
    - finished_at：失败完成时间。
    - attempt_no：执行尝试次数。
    - progress：失败时的进度快照。
    - metadata：附加元数据。
    - result：任务结果快照。
    """

    failure_error = error if error is not None else RuntimeError(error_message)
    payload = build_task_failure_payload(
        failure_error,
        finished_at=finished_at,
        attempt_no=attempt_no,
        progress=progress,
        metadata=metadata,
        result=result,
    )
    if error is None:
        payload["error_message"] = error_message
        error_payload = dict(payload.get("error", {}))
        error_payload["error_message"] = error_message
        payload["error"] = error_payload
        if "result" in payload and isinstance(payload["result"], dict):
            result_payload = dict(payload["result"])
            result_payload["error"] = error_payload
            payload["result"] = result_payload
        if "metadata" in payload and isinstance(payload["metadata"], dict):
            metadata_payload = dict(payload["metadata"])
            metadata_payload["error"] = error_payload
            payload["metadata"] = metadata_payload
    return payload
