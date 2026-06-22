"""detection conversion 创建路由。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status

from backend.queue import LocalFileQueueBackend
from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.deps.db import get_session_factory
from backend.service.api.deps.queue import get_queue_backend
from backend.service.api.deps.storage import get_dataset_storage
from backend.service.api.rest.v1.routes.detection_conversion_route_models import (
    OPENVINO_IR_PRECISION_OPTION_KEY,
    TENSORRT_ENGINE_PRECISION_OPTION_KEY,
)
from backend.service.api.rest.v1.routes.detection_conversion_tasks.schemas import (
    DetectionConversionTaskCreateRequestBody,
    DetectionConversionTaskSubmissionResponse,
)
from backend.service.api.rest.v1.routes.detection_conversion_tasks.services import (
    merge_fixed_detection_conversion_extra_options,
    submit_detection_conversion_task,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


detection_conversion_create_router = APIRouter()


@detection_conversion_create_router.post(
    "/detection/conversion-tasks/onnx",
    response_model=DetectionConversionTaskSubmissionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_detection_onnx_conversion_task(
    body: DetectionConversionTaskCreateRequestBody,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read", "tasks:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    queue_backend: Annotated[LocalFileQueueBackend, Depends(get_queue_backend)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> DetectionConversionTaskSubmissionResponse:
    """创建一个只输出 ONNX 的 detection conversion task。"""

    return submit_detection_conversion_task(
        body=body,
        target_format="onnx",
        principal=principal,
        session_factory=session_factory,
        queue_backend=queue_backend,
        dataset_storage=dataset_storage,
    )


@detection_conversion_create_router.post(
    "/detection/conversion-tasks/onnx-optimized",
    response_model=DetectionConversionTaskSubmissionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_detection_optimized_onnx_conversion_task(
    body: DetectionConversionTaskCreateRequestBody,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read", "tasks:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    queue_backend: Annotated[LocalFileQueueBackend, Depends(get_queue_backend)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> DetectionConversionTaskSubmissionResponse:
    """创建一个输出 optimized ONNX 的 detection conversion task。"""

    return submit_detection_conversion_task(
        body=body,
        target_format="onnx-optimized",
        principal=principal,
        session_factory=session_factory,
        queue_backend=queue_backend,
        dataset_storage=dataset_storage,
    )


@detection_conversion_create_router.post(
    "/detection/conversion-tasks/openvino-ir-fp32",
    response_model=DetectionConversionTaskSubmissionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_detection_openvino_ir_fp32_conversion_task(
    body: DetectionConversionTaskCreateRequestBody,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read", "tasks:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    queue_backend: Annotated[LocalFileQueueBackend, Depends(get_queue_backend)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> DetectionConversionTaskSubmissionResponse:
    """创建一个输出 FP32 OpenVINO IR 的 detection conversion task。"""

    return submit_detection_conversion_task(
        body=body,
        target_format="openvino-ir",
        extra_options_override=merge_fixed_detection_conversion_extra_options(
            body_extra_options=body.extra_options,
            fixed_extra_options={OPENVINO_IR_PRECISION_OPTION_KEY: "fp32"},
        ),
        principal=principal,
        session_factory=session_factory,
        queue_backend=queue_backend,
        dataset_storage=dataset_storage,
    )


@detection_conversion_create_router.post(
    "/detection/conversion-tasks/openvino-ir-fp16",
    response_model=DetectionConversionTaskSubmissionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_detection_openvino_ir_fp16_conversion_task(
    body: DetectionConversionTaskCreateRequestBody,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read", "tasks:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    queue_backend: Annotated[LocalFileQueueBackend, Depends(get_queue_backend)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> DetectionConversionTaskSubmissionResponse:
    """创建一个输出 FP16 OpenVINO IR 的 detection conversion task。"""

    return submit_detection_conversion_task(
        body=body,
        target_format="openvino-ir",
        extra_options_override=merge_fixed_detection_conversion_extra_options(
            body_extra_options=body.extra_options,
            fixed_extra_options={OPENVINO_IR_PRECISION_OPTION_KEY: "fp16"},
        ),
        principal=principal,
        session_factory=session_factory,
        queue_backend=queue_backend,
        dataset_storage=dataset_storage,
    )


@detection_conversion_create_router.post(
    "/detection/conversion-tasks/tensorrt-engine-fp32",
    response_model=DetectionConversionTaskSubmissionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_detection_tensorrt_engine_fp32_conversion_task(
    body: DetectionConversionTaskCreateRequestBody,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read", "tasks:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    queue_backend: Annotated[LocalFileQueueBackend, Depends(get_queue_backend)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> DetectionConversionTaskSubmissionResponse:
    """创建一个输出 FP32 TensorRT engine 的 detection conversion task。"""

    return submit_detection_conversion_task(
        body=body,
        target_format="tensorrt-engine",
        extra_options_override=merge_fixed_detection_conversion_extra_options(
            body_extra_options=body.extra_options,
            fixed_extra_options={TENSORRT_ENGINE_PRECISION_OPTION_KEY: "fp32"},
        ),
        principal=principal,
        session_factory=session_factory,
        queue_backend=queue_backend,
        dataset_storage=dataset_storage,
    )


@detection_conversion_create_router.post(
    "/detection/conversion-tasks/tensorrt-engine-fp16",
    response_model=DetectionConversionTaskSubmissionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_detection_tensorrt_engine_fp16_conversion_task(
    body: DetectionConversionTaskCreateRequestBody,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read", "tasks:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    queue_backend: Annotated[LocalFileQueueBackend, Depends(get_queue_backend)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> DetectionConversionTaskSubmissionResponse:
    """创建一个输出 FP16 TensorRT engine 的 detection conversion task。"""

    return submit_detection_conversion_task(
        body=body,
        target_format="tensorrt-engine",
        extra_options_override=merge_fixed_detection_conversion_extra_options(
            body_extra_options=body.extra_options,
            fixed_extra_options={TENSORRT_ENGINE_PRECISION_OPTION_KEY: "fp16"},
        ),
        principal=principal,
        session_factory=session_factory,
        queue_backend=queue_backend,
        dataset_storage=dataset_storage,
    )
