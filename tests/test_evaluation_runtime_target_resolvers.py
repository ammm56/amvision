"""评估 runtime resolver 映射测试。"""

from __future__ import annotations

import pytest

from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.evaluation_runtime_target_resolvers import (
    get_detection_evaluation_runtime_target_resolver,
    get_segmentation_evaluation_runtime_target_resolver,
    get_yolo_primary_evaluation_runtime_target_resolver,
)
from backend.service.application.runtime.targets.rfdetr import (
    SqlAlchemyRfdetrRuntimeTargetResolver,
)
from backend.service.application.runtime.runtime_target import (
    SqlAlchemyRuntimeTargetResolver,
)
from backend.service.application.runtime.targets.yolo11 import (
    SqlAlchemyYolo11RuntimeTargetResolver,
)
from backend.service.application.runtime.targets.yolo26 import (
    SqlAlchemyYolo26RuntimeTargetResolver,
)
from backend.service.application.runtime.targets.yolov8 import (
    SqlAlchemyYoloV8RuntimeTargetResolver,
)


def test_yolo_primary_evaluation_runtime_resolver_supports_expected_model_types() -> None:
    """YOLO 主线评估 resolver 只支持 yolov8/yolo11/yolo26。"""

    assert (
        get_yolo_primary_evaluation_runtime_target_resolver("yolov8")
        is SqlAlchemyYoloV8RuntimeTargetResolver
    )
    assert (
        get_yolo_primary_evaluation_runtime_target_resolver("yolo11")
        is SqlAlchemyYolo11RuntimeTargetResolver
    )
    assert (
        get_yolo_primary_evaluation_runtime_target_resolver("yolo26")
        is SqlAlchemyYolo26RuntimeTargetResolver
    )
    with pytest.raises(InvalidRequestError):
        get_yolo_primary_evaluation_runtime_target_resolver("rfdetr")
    with pytest.raises(InvalidRequestError):
        get_yolo_primary_evaluation_runtime_target_resolver("yolox")


def test_segmentation_evaluation_runtime_resolver_supports_rfdetr() -> None:
    """segmentation 评估应支持 RF-DETR segmentation。"""

    assert (
        get_segmentation_evaluation_runtime_target_resolver("rfdetr")
        is SqlAlchemyRfdetrRuntimeTargetResolver
    )
    assert (
        get_segmentation_evaluation_runtime_target_resolver("yolov8")
        is SqlAlchemyYoloV8RuntimeTargetResolver
    )


def test_detection_evaluation_runtime_resolver_supports_detection_matrix() -> None:
    """detection 评估 resolver 应覆盖当前 detection 支持矩阵。"""

    assert (
        get_detection_evaluation_runtime_target_resolver("yolox")
        is SqlAlchemyRuntimeTargetResolver
    )
    assert (
        get_detection_evaluation_runtime_target_resolver("rfdetr")
        is SqlAlchemyRfdetrRuntimeTargetResolver
    )
    assert (
        get_detection_evaluation_runtime_target_resolver("yolo11")
        is SqlAlchemyYolo11RuntimeTargetResolver
    )
