"""按 task_type 分发 prediction request、execution result 与 runtime session。"""

from __future__ import annotations

from dataclasses import replace
from typing import TypeAlias

from backend.service.application.errors import (
    InvalidRequestError,
    ServiceConfigurationError,
)
from backend.service.application.task_type_support import (
    require_supported_platform_task_type,
)
from backend.service.application.runtime.tasks.classification_model_runtime import (
    DefaultClassificationModelRuntime,
)
from backend.service.application.runtime.contracts.classification.prediction import (
    ClassificationPredictionExecutionResult,
    ClassificationPredictionRequest,
)
from backend.service.application.runtime.serialization.classification.prediction import (
    deserialize_classification_categories,
    deserialize_classification_category,
    deserialize_classification_runtime_session_info,
    serialize_classification_category,
    serialize_classification_runtime_session_info,
)
from backend.service.application.runtime.tasks.detection_model_runtime import (
    DefaultDetectionModelRuntime,
)
from backend.service.application.runtime.contracts.detection.prediction import (
    DetectionPredictionExecutionResult,
    DetectionPredictionRequest,
)
from backend.service.application.runtime.serialization.detection.prediction import (
    deserialize_detection_items,
    deserialize_runtime_session_info,
    serialize_detection,
    serialize_runtime_session_info,
)
from backend.service.application.runtime.tasks.obb_model_runtime import (
    DefaultObbModelRuntime,
)
from backend.service.application.runtime.contracts.obb.prediction import (
    ObbPredictionExecutionResult,
    ObbPredictionRequest,
)
from backend.service.application.runtime.serialization.obb.prediction import (
    deserialize_obb_instances,
    deserialize_obb_runtime_session_info,
    serialize_obb_instance,
    serialize_obb_runtime_session_info,
)
from backend.service.application.runtime.tasks.pose_model_runtime import (
    DefaultPoseModelRuntime,
)
from backend.service.application.runtime.contracts.pose.prediction import (
    PosePredictionExecutionResult,
    PosePredictionRequest,
)
from backend.service.application.runtime.serialization.pose.prediction import (
    deserialize_pose_instances,
    deserialize_pose_runtime_session_info,
    serialize_pose_instance,
    serialize_pose_runtime_session_info,
)
from backend.service.application.runtime.targets.runtime_target import (
    RuntimeTargetSnapshot,
)
from backend.service.application.runtime.tasks.segmentation_model_runtime import (
    DefaultSegmentationModelRuntime,
)
from backend.service.application.runtime.contracts.segmentation.prediction import (
    SegmentationPredictionExecutionResult,
    SegmentationPredictionRequest,
)
from backend.service.application.runtime.serialization.segmentation.prediction import (
    deserialize_segmentation_instances,
    deserialize_segmentation_runtime_session_info,
    serialize_segmentation_instance,
    serialize_segmentation_runtime_session_info,
)
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)
from backend.service.domain.deployments.deployment_runtime_configuration import (
    DeploymentRuntimeConfiguration,
)


PredictionRequest: TypeAlias = (
    DetectionPredictionRequest
    | ClassificationPredictionRequest
    | SegmentationPredictionRequest
    | PosePredictionRequest
    | ObbPredictionRequest
)

PredictionExecutionResult: TypeAlias = (
    DetectionPredictionExecutionResult
    | ClassificationPredictionExecutionResult
    | SegmentationPredictionExecutionResult
    | PosePredictionExecutionResult
    | ObbPredictionExecutionResult
)


def load_runtime_session(
    *,
    dataset_storage: LocalDatasetStorage,
    runtime_target: RuntimeTargetSnapshot,
    runtime_configuration: DeploymentRuntimeConfiguration,
) -> object:
    """按 task_type 与 model_type 加载正式 runtime session。"""

    task_type = require_supported_platform_task_type(
        runtime_target.task_type,
        empty_message="task_type 不能为空",
        unsupported_message="当前 deployment runtime 尚未接通该 task_type",
    )
    if task_type == "detection":
        return DefaultDetectionModelRuntime().load_session(
            dataset_storage=dataset_storage,
            runtime_target=runtime_target,
            runtime_configuration=runtime_configuration,
        )
    if task_type == "classification":
        return DefaultClassificationModelRuntime().load_session(
            dataset_storage=dataset_storage,
            runtime_target=runtime_target,
            runtime_configuration=runtime_configuration,
        )
    if task_type == "segmentation":
        return DefaultSegmentationModelRuntime().load_session(
            dataset_storage=dataset_storage,
            runtime_target=runtime_target,
            runtime_configuration=runtime_configuration,
        )
    if task_type == "pose":
        return DefaultPoseModelRuntime().load_session(
            dataset_storage=dataset_storage,
            runtime_target=runtime_target,
            runtime_configuration=runtime_configuration,
        )
    if task_type == "obb":
        return DefaultObbModelRuntime().load_session(
            dataset_storage=dataset_storage,
            runtime_target=runtime_target,
            runtime_configuration=runtime_configuration,
        )
    raise ServiceConfigurationError(
        "当前 deployment runtime 尚未接通该 task_type",
        details={"task_type": task_type},
    )


def build_prediction_request_from_payload(
    *,
    task_type: str,
    payload: dict[str, object],
) -> PredictionRequest:
    """从 worker payload 构造 task-native prediction request。"""

    if "input_image_bytes_base64" in payload:
        raise InvalidRequestError(
            "prediction IPC 不支持图片 Base64，请使用 LocalBuffer 或 ObjectStore 引用"
        )
    normalized_task_type = require_supported_platform_task_type(
        task_type,
        empty_message="task_type 不能为空",
        unsupported_message="prediction request 缺少支持的 task_type",
    )
    if normalized_task_type == "detection":
        return DetectionPredictionRequest(
            score_threshold=_read_required_float(payload, "score_threshold"),
            save_result_image=bool(payload.get("save_result_image") is True),
            input_uri=_read_optional_str(payload, "input_uri"),
            input_image_payload=_read_optional_dict(payload, "input_image_payload"),
            extra_options=_read_dict(payload, "extra_options"),
        )
    if normalized_task_type == "classification":
        return ClassificationPredictionRequest(
            top_k=_read_required_int(payload, "top_k"),
            save_result_image=bool(payload.get("save_result_image") is True),
            input_uri=_read_optional_str(payload, "input_uri"),
            input_image_payload=_read_optional_dict(payload, "input_image_payload"),
            extra_options=_read_dict(payload, "extra_options"),
        )
    if normalized_task_type == "segmentation":
        return SegmentationPredictionRequest(
            score_threshold=_read_required_float(payload, "score_threshold"),
            mask_threshold=_read_required_float(payload, "mask_threshold"),
            save_result_image=bool(payload.get("save_result_image") is True),
            input_uri=_read_optional_str(payload, "input_uri"),
            input_image_payload=_read_optional_dict(payload, "input_image_payload"),
            extra_options=_read_dict(payload, "extra_options"),
        )
    if normalized_task_type == "pose":
        return PosePredictionRequest(
            score_threshold=_read_required_float(payload, "score_threshold"),
            keypoint_confidence_threshold=_read_required_float(
                payload,
                "keypoint_confidence_threshold",
            ),
            save_result_image=bool(payload.get("save_result_image") is True),
            input_uri=_read_optional_str(payload, "input_uri"),
            input_image_payload=_read_optional_dict(payload, "input_image_payload"),
            extra_options=_read_dict(payload, "extra_options"),
        )
    if normalized_task_type == "obb":
        return ObbPredictionRequest(
            score_threshold=_read_required_float(payload, "score_threshold"),
            save_result_image=bool(payload.get("save_result_image") is True),
            input_uri=_read_optional_str(payload, "input_uri"),
            input_image_payload=_read_optional_dict(payload, "input_image_payload"),
            extra_options=_read_dict(payload, "extra_options"),
        )
    raise InvalidRequestError(
        "prediction request 缺少支持的 task_type",
        details={"task_type": task_type},
    )


def serialize_prediction_request(
    *,
    task_type: str,
    request: PredictionRequest,
) -> dict[str, object]:
    """把 prediction request 转换为不含图片 bytes 的 IPC 载荷。"""

    normalized_task_type = require_supported_platform_task_type(
        task_type,
        empty_message="task_type 不能为空",
        unsupported_message="prediction request 缺少支持的 task_type",
    )
    common_payload: dict[str, object] = {
        "save_result_image": bool(getattr(request, "save_result_image", False)),
        "input_uri": getattr(request, "input_uri", None),
        "input_image_payload": dict(
            getattr(request, "input_image_payload", None) or {}
        ),
        "extra_options": dict(getattr(request, "extra_options", {}) or {}),
    }
    if getattr(request, "input_image_bytes", None) is not None:
        raise InvalidRequestError(
            "prediction IPC 图片必须先转换为 LocalBuffer 或 ObjectStore 引用"
        )
    if normalized_task_type == "detection":
        return {
            **common_payload,
            "score_threshold": float(getattr(request, "score_threshold")),
        }
    if normalized_task_type == "classification":
        return {
            **common_payload,
            "top_k": int(getattr(request, "top_k")),
        }
    if normalized_task_type == "segmentation":
        return {
            **common_payload,
            "score_threshold": float(getattr(request, "score_threshold")),
            "mask_threshold": float(getattr(request, "mask_threshold")),
        }
    if normalized_task_type == "pose":
        return {
            **common_payload,
            "score_threshold": float(getattr(request, "score_threshold")),
            "keypoint_confidence_threshold": float(
                getattr(request, "keypoint_confidence_threshold")
            ),
        }
    if normalized_task_type == "obb":
        return {
            **common_payload,
            "score_threshold": float(getattr(request, "score_threshold")),
        }
    raise InvalidRequestError(
        "prediction request 缺少支持的 task_type",
        details={"task_type": task_type},
    )


def replace_prediction_request_inputs(
    *,
    request: PredictionRequest,
    input_uri: str | None,
    input_image_bytes: bytes | bytearray | memoryview | None,
    input_image_payload: dict[str, object] | None = None,
) -> PredictionRequest:
    """替换 prediction request 中的输入承载字段。"""

    return replace(
        request,
        input_uri=input_uri,
        input_image_bytes=input_image_bytes,
        input_image_payload=input_image_payload,
    )


def build_dummy_prediction_request(
    *,
    task_type: str,
    input_image_bytes: bytes,
) -> PredictionRequest:
    """构造 keep-warm 与 warmup 使用的最小 prediction request。"""

    extra_options = {"internal_request_kind": "deployment_dummy_warmup"}
    normalized_task_type = require_supported_platform_task_type(
        task_type,
        empty_message="task_type 不能为空",
        unsupported_message="dummy prediction request 缺少支持的 task_type",
    )
    if normalized_task_type == "detection":
        return DetectionPredictionRequest(
            input_image_bytes=input_image_bytes,
            score_threshold=0.3,
            save_result_image=False,
            extra_options=extra_options,
        )
    if normalized_task_type == "classification":
        return ClassificationPredictionRequest(
            input_image_bytes=input_image_bytes,
            top_k=1,
            save_result_image=False,
            extra_options=extra_options,
        )
    if normalized_task_type == "segmentation":
        return SegmentationPredictionRequest(
            input_image_bytes=input_image_bytes,
            score_threshold=0.3,
            mask_threshold=0.5,
            save_result_image=False,
            extra_options=extra_options,
        )
    if normalized_task_type == "pose":
        return PosePredictionRequest(
            input_image_bytes=input_image_bytes,
            score_threshold=0.3,
            keypoint_confidence_threshold=0.3,
            save_result_image=False,
            extra_options=extra_options,
        )
    if normalized_task_type == "obb":
        return ObbPredictionRequest(
            input_image_bytes=input_image_bytes,
            score_threshold=0.3,
            save_result_image=False,
            extra_options=extra_options,
        )
    raise InvalidRequestError(
        "dummy prediction request 缺少支持的 task_type",
        details={"task_type": task_type},
    )


def serialize_prediction_execution_result(
    *,
    task_type: str,
    execution_result: PredictionExecutionResult,
) -> dict[str, object]:
    """把 execution result 转为不含结果图片 bytes 的 IPC 载荷。"""

    normalized_task_type = require_supported_platform_task_type(
        task_type,
        empty_message="task_type 不能为空",
        unsupported_message="prediction execution result 缺少支持的 task_type",
    )
    common_payload: dict[str, object] = {
        "latency_ms": execution_result.latency_ms,
        "image_width": execution_result.image_width,
        "image_height": execution_result.image_height,
    }
    if normalized_task_type == "detection":
        return {
            **common_payload,
            "detections": [
                serialize_detection(item) for item in execution_result.detections
            ],
            "runtime_session_info": serialize_runtime_session_info(
                execution_result.runtime_session_info
            ),
        }
    if normalized_task_type == "classification":
        return {
            **common_payload,
            "categories": [
                serialize_classification_category(item)
                for item in execution_result.categories
            ],
            "top_category": (
                serialize_classification_category(execution_result.top_category)
                if execution_result.top_category is not None
                else None
            ),
            "runtime_session_info": serialize_classification_runtime_session_info(
                execution_result.runtime_session_info
            ),
        }
    if normalized_task_type == "segmentation":
        return {
            **common_payload,
            "instances": [
                serialize_segmentation_instance(item)
                for item in execution_result.instances
            ],
            "runtime_session_info": serialize_segmentation_runtime_session_info(
                execution_result.runtime_session_info
            ),
        }
    if normalized_task_type == "pose":
        return {
            **common_payload,
            "instances": [
                serialize_pose_instance(item) for item in execution_result.instances
            ],
            "runtime_session_info": serialize_pose_runtime_session_info(
                execution_result.runtime_session_info
            ),
        }
    if normalized_task_type == "obb":
        return {
            **common_payload,
            "instances": [
                serialize_obb_instance(item) for item in execution_result.instances
            ],
            "runtime_session_info": serialize_obb_runtime_session_info(
                execution_result.runtime_session_info
            ),
        }
    raise InvalidRequestError(
        "prediction execution result 缺少支持的 task_type",
        details={"task_type": task_type},
    )


def detect_prediction_preview_media_type(content: bytes) -> str:
    """按图片签名识别推理预览图媒体类型。"""

    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if content.startswith(b"BM"):
        return "image/bmp"
    if content.startswith((b"II*\x00", b"MM\x00*")):
        return "image/tiff"
    raise ServiceConfigurationError("inference preview 图片格式无法识别")


def deserialize_prediction_execution_result(
    *,
    task_type: str,
    payload: object,
) -> PredictionExecutionResult:
    """把跨进程 execution result 载荷恢复为 task-native 对象。"""

    if not isinstance(payload, dict):
        raise InvalidRequestError("prediction execution result 格式不合法")
    if "preview_image_bytes_base64" in payload:
        raise InvalidRequestError(
            "prediction IPC 不支持结果图片 Base64，请使用 LocalBuffer 或 ObjectStore 引用"
        )
    normalized_task_type = require_supported_platform_task_type(
        task_type,
        empty_message="task_type 不能为空",
        unsupported_message="prediction execution result 缺少支持的 task_type",
    )
    latency_ms = _read_optional_float(payload, "latency_ms")
    image_width = _read_required_int(payload, "image_width")
    image_height = _read_required_int(payload, "image_height")
    direct_preview_image_bytes = payload.get("preview_image_bytes")
    preview_image_bytes = (
        bytes(direct_preview_image_bytes)
        if isinstance(direct_preview_image_bytes, bytes | bytearray | memoryview)
        else None
    )
    if normalized_task_type == "detection":
        return DetectionPredictionExecutionResult(
            detections=deserialize_detection_items(payload.get("detections")),
            latency_ms=latency_ms,
            image_width=image_width,
            image_height=image_height,
            preview_image_bytes=preview_image_bytes,
            runtime_session_info=deserialize_runtime_session_info(
                payload.get("runtime_session_info")
            ),
        )
    if normalized_task_type == "classification":
        return ClassificationPredictionExecutionResult(
            categories=deserialize_classification_categories(payload.get("categories")),
            top_category=deserialize_classification_category(
                payload.get("top_category")
            ),
            latency_ms=latency_ms,
            image_width=image_width,
            image_height=image_height,
            preview_image_bytes=preview_image_bytes,
            runtime_session_info=deserialize_classification_runtime_session_info(
                payload.get("runtime_session_info")
            ),
        )
    if normalized_task_type == "segmentation":
        return SegmentationPredictionExecutionResult(
            instances=deserialize_segmentation_instances(payload.get("instances")),
            latency_ms=latency_ms,
            image_width=image_width,
            image_height=image_height,
            preview_image_bytes=preview_image_bytes,
            runtime_session_info=deserialize_segmentation_runtime_session_info(
                payload.get("runtime_session_info")
            ),
        )
    if normalized_task_type == "pose":
        return PosePredictionExecutionResult(
            instances=deserialize_pose_instances(payload.get("instances")),
            latency_ms=latency_ms,
            image_width=image_width,
            image_height=image_height,
            preview_image_bytes=preview_image_bytes,
            runtime_session_info=deserialize_pose_runtime_session_info(
                payload.get("runtime_session_info")
            ),
        )
    if normalized_task_type == "obb":
        return ObbPredictionExecutionResult(
            instances=deserialize_obb_instances(payload.get("instances")),
            latency_ms=latency_ms,
            image_width=image_width,
            image_height=image_height,
            preview_image_bytes=preview_image_bytes,
            runtime_session_info=deserialize_obb_runtime_session_info(
                payload.get("runtime_session_info")
            ),
        )
    raise InvalidRequestError(
        "prediction execution result 缺少支持的 task_type",
        details={"task_type": task_type},
    )


def _read_optional_str(payload: dict[str, object], key: str) -> str | None:
    """从字典中读取可选字符串。"""

    value = payload.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _read_required_int(payload: dict[str, object], key: str) -> int:
    """从字典中读取必填整数。"""

    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise InvalidRequestError(
            "prediction payload 缺少合法整数",
            details={"field": key},
        )
    return value


def _read_required_float(payload: dict[str, object], key: str) -> float:
    """从字典中读取必填浮点数。"""

    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise InvalidRequestError(
            "prediction payload 缺少合法数字",
            details={"field": key},
        )
    return float(value)


def _read_optional_float(payload: dict[str, object], key: str) -> float | None:
    """从字典中读取可选浮点数。"""

    value = payload.get(key)
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    return None


def _read_optional_dict(
    payload: dict[str, object],
    key: str,
) -> dict[str, object] | None:
    """从字典中读取可选对象。"""

    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, dict):
        raise InvalidRequestError(
            "prediction payload 字段必须是对象",
            details={"field": key},
        )
    return {
        str(current_key): current_value for current_key, current_value in value.items()
    }


def _read_dict(payload: dict[str, object], key: str) -> dict[str, object]:
    """从字典中读取对象，缺失时返回空字典。"""

    return _read_optional_dict(payload, key) or {}
