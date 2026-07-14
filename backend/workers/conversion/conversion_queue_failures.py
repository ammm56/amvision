"""conversion 队列失败元数据构造工具。"""

from __future__ import annotations

from collections.abc import Mapping

from backend.queue import QueueMessage
from backend.service.application.error_serialization import serialize_error


def build_conversion_queue_failure_metadata(
    queue_task: QueueMessage,
    error: BaseException,
) -> dict[str, object]:
    """构造 conversion worker 失败时写入队列记录的元数据。

    参数：
    - queue_task：当前消费的队列任务。
    - error：执行过程中抛出的异常。
    """

    error_payload = serialize_error(error)
    metadata: dict[str, object] = {
        "task_id": _read_mapping_value(queue_task.payload, "task_id"),
        "source_model_version_id": _read_mapping_value(
            queue_task.metadata,
            "source_model_version_id",
        ),
        "error": error_payload,
        "error_type": error_payload.get("error_type", error.__class__.__name__),
        "error_message": error_payload.get("error_message", str(error)),
    }
    if "error_code" in error_payload:
        metadata["error_code"] = error_payload["error_code"]
    if "status_code" in error_payload:
        metadata["status_code"] = error_payload["status_code"]
    if "details" in error_payload:
        metadata["error_details"] = error_payload["details"]
    return metadata


def _read_mapping_value(value: object, key: str) -> object | None:
    """从可能不是 dict 的队列字段中安全读取值。"""

    if isinstance(value, Mapping):
        return value.get(key)
    return None
