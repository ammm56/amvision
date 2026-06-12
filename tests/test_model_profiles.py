"""模型 profile 与规格基础行为测试。"""

from __future__ import annotations

import pytest

from backend.contracts.datasets.exports.coco_detection_export import COCO_DETECTION_DATASET_FORMAT
from backend.contracts.datasets.exports.dataset_formats import (
    YOLO_DETECTION_DATASET_FORMAT,
    YOLO_INSTANCE_SEGMENTATION_DATASET_FORMAT,
    YOLO_POSE_DATASET_FORMAT,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.model_type_support import (
    ensure_requested_platform_model_type_matches,
    normalize_optional_platform_model_type,
    require_optional_supported_platform_model_type,
    require_supported_platform_model_type,
)
from backend.service.domain.models.model_task_types import (
    CLASSIFICATION_TASK_TYPE,
    DETECTION_TASK_TYPE,
    OBB_TASK_TYPE,
    POSE_TASK_TYPE,
    SEGMENTATION_TASK_TYPE,
)
from backend.service.domain.models.platform_model_support import (
    SUPPORTED_PLATFORM_MODEL_TYPES,
    SUPPORTED_PLATFORM_MODEL_TYPES_BY_TASK_TYPE,
    build_platform_model_type_field_description,
    get_supported_platform_model_types,
    is_supported_platform_model_type,
)
from backend.service.domain.models.yolo_model_profiles import get_yolo_model_profile
from backend.service.domain.models.yolo11_model_spec import DEFAULT_YOLO11_MODEL_SPEC
from backend.service.domain.models.yolo26_model_spec import DEFAULT_YOLO26_MODEL_SPEC
from backend.service.domain.models.yolov8_model_spec import DEFAULT_YOLOV8_MODEL_SPEC
from backend.service.domain.models.yolox_model_spec import DEFAULT_YOLOX_MODEL_SPEC


def test_yolox_model_spec_exposes_detection_capabilities() -> None:
    """验证 YOLOX 规格对象暴露 detection 主线的最小公共能力。"""

    spec = DEFAULT_YOLOX_MODEL_SPEC

    assert spec.supports_task_type(DETECTION_TASK_TYPE) is True
    assert spec.supports_model_scale("s") is True
    assert spec.supports_model_scale("nano") is True
    assert spec.supports_build_format("onnx") is True
    assert spec.resolve_default_dataset_format(DETECTION_TASK_TYPE) == COCO_DETECTION_DATASET_FORMAT


def test_yolo_model_profiles_expose_shared_task_defaults() -> None:
    """验证 YOLO 系列 profile 已登记 detection、segmentation 和 pose 的默认导出格式。"""

    profile = get_yolo_model_profile("yolo11")

    assert profile is not None
    assert profile.supports_task_type(DETECTION_TASK_TYPE) is True
    assert profile.supports_task_type(SEGMENTATION_TASK_TYPE) is True
    assert profile.supports_task_type(POSE_TASK_TYPE) is True
    assert profile.supports_task_type(OBB_TASK_TYPE) is True
    assert profile.supports_model_scale("nano") is True
    assert profile.resolve_default_dataset_format(DETECTION_TASK_TYPE) == YOLO_DETECTION_DATASET_FORMAT
    assert profile.resolve_default_dataset_format(SEGMENTATION_TASK_TYPE) == YOLO_INSTANCE_SEGMENTATION_DATASET_FORMAT
    assert profile.resolve_default_dataset_format(POSE_TASK_TYPE) == YOLO_POSE_DATASET_FORMAT
    assert profile.resolve_default_dataset_format(OBB_TASK_TYPE) is None


def test_yolo_model_specs_follow_registered_profiles() -> None:
    """验证 YOLOv8、YOLO11、YOLO26 规格对象已经正式暴露多任务能力。"""

    for spec in (DEFAULT_YOLOV8_MODEL_SPEC, DEFAULT_YOLO11_MODEL_SPEC, DEFAULT_YOLO26_MODEL_SPEC):
        assert spec.supports_task_type(DETECTION_TASK_TYPE) is True
        assert spec.supports_task_type(SEGMENTATION_TASK_TYPE) is True
        assert spec.supports_task_type(POSE_TASK_TYPE) is True
        assert spec.supports_task_type(OBB_TASK_TYPE) is True
        assert spec.supports_task_type(CLASSIFICATION_TASK_TYPE) is True
        assert spec.resolve_default_dataset_format(DETECTION_TASK_TYPE) == YOLO_DETECTION_DATASET_FORMAT
        assert spec.resolve_default_dataset_format(SEGMENTATION_TASK_TYPE) == YOLO_INSTANCE_SEGMENTATION_DATASET_FORMAT
        assert spec.resolve_default_dataset_format(POSE_TASK_TYPE) == YOLO_POSE_DATASET_FORMAT
        assert spec.resolve_default_dataset_format(CLASSIFICATION_TASK_TYPE) is None


def test_platform_model_support_matrix_matches_registered_specs() -> None:
    """验证平台模型支持矩阵已经按真实规格汇总。"""

    assert SUPPORTED_PLATFORM_MODEL_TYPES == ("yolox", "yolov8", "yolo11", "yolo26", "rfdetr")
    assert SUPPORTED_PLATFORM_MODEL_TYPES_BY_TASK_TYPE[DETECTION_TASK_TYPE] == (
        "yolox",
        "yolov8",
        "yolo11",
        "yolo26",
        "rfdetr",
    )
    assert SUPPORTED_PLATFORM_MODEL_TYPES_BY_TASK_TYPE[CLASSIFICATION_TASK_TYPE] == (
        "yolov8",
        "yolo11",
        "yolo26",
    )
    assert SUPPORTED_PLATFORM_MODEL_TYPES_BY_TASK_TYPE[SEGMENTATION_TASK_TYPE] == (
        "yolov8",
        "yolo11",
        "yolo26",
        "rfdetr",
    )
    assert SUPPORTED_PLATFORM_MODEL_TYPES_BY_TASK_TYPE[POSE_TASK_TYPE] == (
        "yolov8",
        "yolo11",
        "yolo26",
    )
    assert SUPPORTED_PLATFORM_MODEL_TYPES_BY_TASK_TYPE[OBB_TASK_TYPE] == (
        "yolov8",
        "yolo11",
        "yolo26",
    )
    assert get_supported_platform_model_types("unknown") == ()


def test_platform_model_support_helpers_expose_normalized_checks_and_descriptions() -> None:
    """验证平台模型支持 helper 会返回统一说明和归一化判定。"""

    assert (
        build_platform_model_type_field_description(DETECTION_TASK_TYPE)
        == "模型分类；当前支持 yolox、yolov8、yolo11、yolo26、rfdetr"
    )
    assert is_supported_platform_model_type(CLASSIFICATION_TASK_TYPE, " YOLO11 ") is True
    assert is_supported_platform_model_type(CLASSIFICATION_TASK_TYPE, "rfdetr") is False


def test_application_model_type_helpers_reuse_shared_normalization_and_support_checks() -> None:
    """验证应用层 model_type helper 会复用统一归一化和任务支持矩阵。"""

    assert normalize_optional_platform_model_type(" YOLO11 ") == "yolo11"
    assert (
        require_supported_platform_model_type(
            task_type=CLASSIFICATION_TASK_TYPE,
            model_type=" YOLO11 ",
            unsupported_message="当前 classification 不支持指定模型分类",
        )
        == "yolo11"
    )
    assert (
        require_optional_supported_platform_model_type(
            task_type=CLASSIFICATION_TASK_TYPE,
            model_type="   ",
            unsupported_message="当前 classification 不支持指定模型分类",
        )
        is None
    )
    with pytest.raises(InvalidRequestError) as error:
        require_supported_platform_model_type(
            task_type=CLASSIFICATION_TASK_TYPE,
            model_type="rfdetr",
            unsupported_message="当前 classification 不支持指定模型分类",
        )
    assert error.value.details == {
        "model_type": "rfdetr",
        "supported": ["yolov8", "yolo11", "yolo26"],
    }


def test_application_model_type_helpers_can_validate_requested_and_resolved_match() -> None:
    """验证应用层 helper 会统一校验请求 model_type 与实际绑定模型的一致性。"""

    ensure_requested_platform_model_type_matches(
        requested_model_type=" YOLOX ",
        resolved_model_type="yolox",
        deployment_instance_id="deployment-1",
    )
    with pytest.raises(InvalidRequestError) as error:
        ensure_requested_platform_model_type_matches(
            requested_model_type="yolov8",
            resolved_model_type="yolox",
            deployment_instance_id="deployment-1",
        )
    assert error.value.details == {
        "deployment_instance_id": "deployment-1",
        "requested_model_type": "yolov8",
        "resolved_model_type": "yolox",
    }
