"""detection 训练输出文件 API。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.deps.db import get_session_factory
from backend.service.api.deps.storage import get_dataset_storage
from backend.service.api.rest.v1.routes.detection_training_tasks.output_files import (
    DetectionTrainingMetricsFileResponse,
    DetectionTrainingOutputFileDetailResponse,
    DetectionTrainingOutputFileSummaryResponse,
    _DETECTION_TRAINING_OUTPUT_FILE_ORDER,
    _build_detection_training_metrics_file_response,
    _build_detection_training_output_file_summary_response,
    _parse_detection_training_output_file_name,
    _read_detection_training_output_file,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage

from .services import _require_visible_detection_training_task


detection_training_outputs_router = APIRouter()


@detection_training_outputs_router.get(
    "/detection/training-tasks/{task_id}/validation-metrics",
    response_model=DetectionTrainingMetricsFileResponse,
)
def get_detection_training_validation_metrics(
    task_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> DetectionTrainingMetricsFileResponse:
    """按任务 id 返回当前 detection 训练的验证快照。"""

    task_detail = _require_visible_detection_training_task(
        principal=principal,
        task_id=task_id,
        session_factory=session_factory,
        include_events=False,
    )
    output_file = _read_detection_training_output_file(
        task=task_detail.task,
        file_name="validation-metrics",
        dataset_storage=dataset_storage,
        strict_missing=True,
    )
    return _build_detection_training_metrics_file_response(output_file)


@detection_training_outputs_router.get(
    "/detection/training-tasks/{task_id}/train-metrics",
    response_model=DetectionTrainingMetricsFileResponse,
)
def get_detection_training_train_metrics(
    task_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> DetectionTrainingMetricsFileResponse:
    """按任务 id 返回当前 detection 训练的训练指标快照。"""

    task_detail = _require_visible_detection_training_task(
        principal=principal,
        task_id=task_id,
        session_factory=session_factory,
        include_events=False,
    )
    output_file = _read_detection_training_output_file(
        task=task_detail.task,
        file_name="train-metrics",
        dataset_storage=dataset_storage,
        strict_missing=True,
    )
    return _build_detection_training_metrics_file_response(output_file)


@detection_training_outputs_router.get(
    "/detection/training-tasks/{task_id}/output-files",
    response_model=list[DetectionTrainingOutputFileSummaryResponse],
)
def list_detection_training_output_files(
    task_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> list[DetectionTrainingOutputFileSummaryResponse]:
    """按任务 id 列出当前 detection 训练输出文件状态。"""

    task_detail = _require_visible_detection_training_task(
        principal=principal,
        task_id=task_id,
        session_factory=session_factory,
        include_events=False,
    )
    return [
        _build_detection_training_output_file_summary_response(
            _read_detection_training_output_file(
                task=task_detail.task,
                file_name=file_name,
                dataset_storage=dataset_storage,
                strict_missing=False,
            )
        )
        for file_name in _DETECTION_TRAINING_OUTPUT_FILE_ORDER
    ]


@detection_training_outputs_router.get(
    "/detection/training-tasks/{task_id}/output-files/{file_name}",
    response_model=DetectionTrainingOutputFileDetailResponse,
)
def get_detection_training_output_file_detail(
    task_id: str,
    file_name: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> DetectionTrainingOutputFileDetailResponse:
    """按任务 id 和文件名返回单个 detection 训练输出文件的状态与内容。"""

    task_detail = _require_visible_detection_training_task(
        principal=principal,
        task_id=task_id,
        session_factory=session_factory,
        include_events=False,
    )
    return DetectionTrainingOutputFileDetailResponse.model_validate(
        _read_detection_training_output_file(
            task=task_detail.task,
            file_name=_parse_detection_training_output_file_name(file_name),
            dataset_storage=dataset_storage,
            strict_missing=False,
        ).model_dump()
    )

