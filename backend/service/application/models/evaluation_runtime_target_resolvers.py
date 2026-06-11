"""评估任务使用的 runtime target resolver 映射。"""

from __future__ import annotations

from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.rfdetr_runtime_target import (
    SqlAlchemyRfdetrRuntimeTargetResolver,
)
from backend.service.application.runtime.runtime_target import (
    SqlAlchemyRuntimeTargetResolver,
)
from backend.service.application.runtime.yolo11_runtime_target import (
    SqlAlchemyYolo11RuntimeTargetResolver,
)
from backend.service.application.runtime.yolo26_runtime_target import (
    SqlAlchemyYolo26RuntimeTargetResolver,
)
from backend.service.application.runtime.yolov8_runtime_target import (
    SqlAlchemyYoloV8RuntimeTargetResolver,
)


_YOLO_PRIMARY_EVALUATION_RUNTIME_TARGET_RESOLVER_BY_MODEL_TYPE: dict[str, type] = {
    "yolov8": SqlAlchemyYoloV8RuntimeTargetResolver,
    "yolo11": SqlAlchemyYolo11RuntimeTargetResolver,
    "yolo26": SqlAlchemyYolo26RuntimeTargetResolver,
}
_SEGMENTATION_EVALUATION_RUNTIME_TARGET_RESOLVER_BY_MODEL_TYPE: dict[str, type] = {
    **_YOLO_PRIMARY_EVALUATION_RUNTIME_TARGET_RESOLVER_BY_MODEL_TYPE,
    "rfdetr": SqlAlchemyRfdetrRuntimeTargetResolver,
}
_DETECTION_EVALUATION_RUNTIME_TARGET_RESOLVER_BY_MODEL_TYPE: dict[str, type] = {
    "yolox": SqlAlchemyRuntimeTargetResolver,
    **_YOLO_PRIMARY_EVALUATION_RUNTIME_TARGET_RESOLVER_BY_MODEL_TYPE,
    "rfdetr": SqlAlchemyRfdetrRuntimeTargetResolver,
}


def get_yolo_primary_evaluation_runtime_target_resolver(model_type: str) -> type:
    """按 model_type 返回 YOLO 主线评估使用的 resolver 类。"""

    normalized_model_type = model_type.strip().lower()
    resolver_cls = _YOLO_PRIMARY_EVALUATION_RUNTIME_TARGET_RESOLVER_BY_MODEL_TYPE.get(
        normalized_model_type
    )
    if resolver_cls is None:
        raise InvalidRequestError(
            "当前评估不支持该模型分类",
            details={
                "model_type": normalized_model_type,
                "supported": sorted(
                    _YOLO_PRIMARY_EVALUATION_RUNTIME_TARGET_RESOLVER_BY_MODEL_TYPE.keys()
                ),
            },
        )
    return resolver_cls


def get_segmentation_evaluation_runtime_target_resolver(model_type: str) -> type:
    """按 model_type 返回 segmentation 评估使用的 resolver 类。"""

    normalized_model_type = model_type.strip().lower()
    resolver_cls = _SEGMENTATION_EVALUATION_RUNTIME_TARGET_RESOLVER_BY_MODEL_TYPE.get(
        normalized_model_type
    )
    if resolver_cls is None:
        raise InvalidRequestError(
            "segmentation 评估不支持该模型分类",
            details={
                "model_type": normalized_model_type,
                "supported": sorted(
                    _SEGMENTATION_EVALUATION_RUNTIME_TARGET_RESOLVER_BY_MODEL_TYPE.keys()
                ),
            },
        )
    return resolver_cls


def get_detection_evaluation_runtime_target_resolver(model_type: str) -> type:
    """按 model_type 返回 detection 评估使用的 resolver 类。"""

    normalized_model_type = model_type.strip().lower()
    resolver_cls = _DETECTION_EVALUATION_RUNTIME_TARGET_RESOLVER_BY_MODEL_TYPE.get(
        normalized_model_type
    )
    if resolver_cls is None:
        raise InvalidRequestError(
            "detection 评估不支持该模型分类",
            details={
                "model_type": normalized_model_type,
                "supported": sorted(
                    _DETECTION_EVALUATION_RUNTIME_TARGET_RESOLVER_BY_MODEL_TYPE.keys()
                ),
            },
        )
    return resolver_cls
