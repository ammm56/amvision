"""detection inference 结果文件读取。"""

from __future__ import annotations

from backend.service.api.rest.v1.routes.detection_inference_tasks.responses import (
    DetectionInferenceTaskResultResponse,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


def build_detection_inference_task_result_response(
    *,
    task_detail: object,
    task_id: str,
    dataset_storage: LocalDatasetStorage,
) -> DetectionInferenceTaskResultResponse:
    """读取 detection inference task result 文件并构造 API response。"""

    result = dict(task_detail.task.result)
    object_key = result.get("result_object_key")
    if not isinstance(object_key, str) or not object_key.strip():
        if task_detail.task.state in {"queued", "running"}:
            return DetectionInferenceTaskResultResponse(
                file_status="pending",
                task_state=task_detail.task.state,
                object_key=None,
                payload={},
            )
        raise InvalidRequestError(
            "当前推理任务缺少结果文件",
            details={"task_id": task_id},
        )
    resolved_path = dataset_storage.resolve(object_key)
    if not resolved_path.is_file():
        if task_detail.task.state in {"queued", "running"}:
            return DetectionInferenceTaskResultResponse(
                file_status="pending",
                task_state=task_detail.task.state,
                object_key=object_key,
                payload={},
            )
        raise InvalidRequestError(
            "当前推理任务的结果文件不存在",
            details={"task_id": task_id, "object_key": object_key},
        )
    payload = dataset_storage.read_json(object_key)
    return DetectionInferenceTaskResultResponse(
        file_status="ready",
        task_state=task_detail.task.state,
        object_key=object_key,
        payload=dict(payload) if isinstance(payload, dict) else {},
    )
