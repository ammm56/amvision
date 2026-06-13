"""数据集导出格式支持规则回归测试。"""

from __future__ import annotations

import pytest

from backend.contracts.datasets.exports.dataset_formats import (
    COCO_DETECTION_DATASET_FORMAT,
    COCO_INSTANCE_SEGMENTATION_DATASET_FORMAT,
    COCO_KEYPOINTS_DATASET_FORMAT,
    DOTA_OBB_DATASET_FORMAT,
    IMAGENET_CLASSIFICATION_DATASET_FORMAT,
    YOLO_DETECTION_DATASET_FORMAT,
    YOLO_INSTANCE_SEGMENTATION_DATASET_FORMAT,
    YOLO_POSE_DATASET_FORMAT,
)
from backend.service.application.dataset_export_format_support import (
    require_supported_dataset_export_format,
    resolve_supported_dataset_export_format,
    resolve_supported_dataset_export_formats,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.domain.models.model_task_types import (
    CLASSIFICATION_TASK_TYPE,
    DETECTION_TASK_TYPE,
    OBB_TASK_TYPE,
    POSE_TASK_TYPE,
    SEGMENTATION_TASK_TYPE,
)
from backend.service.domain.models.yolo_model_profiles import (
    YOLO11_MODEL_PROFILE,
    YOLO26_MODEL_PROFILE,
    YOLOV8_MODEL_PROFILE,
)


@pytest.mark.parametrize(
    ("model_type", "task_type", "expected_formats"),
    [
        ("yolox", DETECTION_TASK_TYPE, (COCO_DETECTION_DATASET_FORMAT,)),
        (
            "yolov8",
            DETECTION_TASK_TYPE,
            (YOLO_DETECTION_DATASET_FORMAT, COCO_DETECTION_DATASET_FORMAT),
        ),
        (
            "yolo11",
            DETECTION_TASK_TYPE,
            (YOLO_DETECTION_DATASET_FORMAT, COCO_DETECTION_DATASET_FORMAT),
        ),
        (
            "yolo26",
            DETECTION_TASK_TYPE,
            (YOLO_DETECTION_DATASET_FORMAT, COCO_DETECTION_DATASET_FORMAT),
        ),
        ("rfdetr", DETECTION_TASK_TYPE, (COCO_DETECTION_DATASET_FORMAT,)),
        (
            "yolov8",
            SEGMENTATION_TASK_TYPE,
            (YOLO_INSTANCE_SEGMENTATION_DATASET_FORMAT, COCO_INSTANCE_SEGMENTATION_DATASET_FORMAT),
        ),
        (
            "yolo11",
            SEGMENTATION_TASK_TYPE,
            (YOLO_INSTANCE_SEGMENTATION_DATASET_FORMAT, COCO_INSTANCE_SEGMENTATION_DATASET_FORMAT),
        ),
        (
            "yolo26",
            SEGMENTATION_TASK_TYPE,
            (YOLO_INSTANCE_SEGMENTATION_DATASET_FORMAT, COCO_INSTANCE_SEGMENTATION_DATASET_FORMAT),
        ),
        ("rfdetr", SEGMENTATION_TASK_TYPE, (COCO_INSTANCE_SEGMENTATION_DATASET_FORMAT,)),
        ("yolov8", POSE_TASK_TYPE, (YOLO_POSE_DATASET_FORMAT, COCO_KEYPOINTS_DATASET_FORMAT)),
        ("yolo11", POSE_TASK_TYPE, (YOLO_POSE_DATASET_FORMAT, COCO_KEYPOINTS_DATASET_FORMAT)),
        ("yolo26", POSE_TASK_TYPE, (YOLO_POSE_DATASET_FORMAT, COCO_KEYPOINTS_DATASET_FORMAT)),
        ("yolov8", OBB_TASK_TYPE, (DOTA_OBB_DATASET_FORMAT,)),
        ("yolo11", OBB_TASK_TYPE, (DOTA_OBB_DATASET_FORMAT,)),
        ("yolo26", OBB_TASK_TYPE, (DOTA_OBB_DATASET_FORMAT,)),
        ("yolov8", CLASSIFICATION_TASK_TYPE, (IMAGENET_CLASSIFICATION_DATASET_FORMAT,)),
        ("yolo11", CLASSIFICATION_TASK_TYPE, (IMAGENET_CLASSIFICATION_DATASET_FORMAT,)),
        ("yolo26", CLASSIFICATION_TASK_TYPE, (IMAGENET_CLASSIFICATION_DATASET_FORMAT,)),
    ],
)
def test_resolve_supported_dataset_export_format_returns_current_runner_formats(
    model_type: str,
    task_type: str,
    expected_formats: tuple[str, ...],
) -> None:
    """验证每个已实现模型任务组合对应当前真正接通的导出格式列表。"""

    assert resolve_supported_dataset_export_formats(
        model_type=model_type,
        task_type=task_type,
    ) == expected_formats

    assert resolve_supported_dataset_export_format(
        model_type=model_type,
        task_type=task_type,
    ) == expected_formats[0]


def test_yolo_primary_profiles_match_current_supported_dataset_formats() -> None:
    """验证 YOLO 主线 profile 默认导出格式与当前训练执行器能力一致。"""

    for profile in (YOLOV8_MODEL_PROFILE, YOLO11_MODEL_PROFILE, YOLO26_MODEL_PROFILE):
        assert profile.resolve_default_dataset_format(DETECTION_TASK_TYPE) == YOLO_DETECTION_DATASET_FORMAT
        assert profile.resolve_default_dataset_format(SEGMENTATION_TASK_TYPE) == YOLO_INSTANCE_SEGMENTATION_DATASET_FORMAT
        assert profile.resolve_default_dataset_format(POSE_TASK_TYPE) == YOLO_POSE_DATASET_FORMAT
        assert profile.resolve_default_dataset_format(OBB_TASK_TYPE) == DOTA_OBB_DATASET_FORMAT
        assert profile.resolve_default_dataset_format(CLASSIFICATION_TASK_TYPE) == IMAGENET_CLASSIFICATION_DATASET_FORMAT


@pytest.mark.parametrize(
    ("model_type", "task_type", "wrong_format"),
    [
        ("yolo26", SEGMENTATION_TASK_TYPE, COCO_DETECTION_DATASET_FORMAT),
        ("yolo11", POSE_TASK_TYPE, COCO_DETECTION_DATASET_FORMAT),
        ("yolov8", CLASSIFICATION_TASK_TYPE, COCO_DETECTION_DATASET_FORMAT),
    ],
)
def test_require_supported_dataset_export_format_rejects_hidden_mismatch(
    model_type: str,
    task_type: str,
    wrong_format: str,
) -> None:
    """验证会在任务提交前拦住同类格式错配。"""

    with pytest.raises(InvalidRequestError):
        require_supported_dataset_export_format(
            model_type=model_type,
            task_type=task_type,
            format_id=wrong_format,
            dataset_export_id="dataset-export-demo",
            unsupported_message="mismatch",
        )


@pytest.mark.parametrize("model_type", ["yolov8", "yolo11", "yolo26"])
def test_require_supported_dataset_export_format_accepts_coco_detection_for_yolo_detection_models(
    model_type: str,
) -> None:
    """验证 YOLO detection 主线已经允许直接复用 COCO detection 导出。"""

    assert (
        require_supported_dataset_export_format(
            model_type=model_type,
            task_type=DETECTION_TASK_TYPE,
            format_id=COCO_DETECTION_DATASET_FORMAT,
            dataset_export_id="dataset-export-demo",
            unsupported_message="mismatch",
        )
        == COCO_DETECTION_DATASET_FORMAT
    )


@pytest.mark.parametrize("model_type", ["yolov8", "yolo11", "yolo26"])
def test_require_supported_dataset_export_format_accepts_yolo_segmentation_for_yolo_segmentation_models(
    model_type: str,
) -> None:
    """验证 YOLO segmentation 主线已接受 yolo-instance-seg-v1。"""

    assert (
        require_supported_dataset_export_format(
            model_type=model_type,
            task_type=SEGMENTATION_TASK_TYPE,
            format_id=YOLO_INSTANCE_SEGMENTATION_DATASET_FORMAT,
            dataset_export_id="dataset-export-demo",
            unsupported_message="mismatch",
        )
        == YOLO_INSTANCE_SEGMENTATION_DATASET_FORMAT
    )


@pytest.mark.parametrize("model_type", ["yolov8", "yolo11", "yolo26"])
def test_require_supported_dataset_export_format_accepts_yolo_pose_for_yolo_pose_models(
    model_type: str,
) -> None:
    """验证 YOLO pose 主线已接受 yolo-pose-v1。"""

    assert (
        require_supported_dataset_export_format(
            model_type=model_type,
            task_type=POSE_TASK_TYPE,
            format_id=YOLO_POSE_DATASET_FORMAT,
            dataset_export_id="dataset-export-demo",
            unsupported_message="mismatch",
        )
        == YOLO_POSE_DATASET_FORMAT
    )
