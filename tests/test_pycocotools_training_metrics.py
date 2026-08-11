"""真实 pycocotools 与训练 best metric 规则回归测试。"""

from __future__ import annotations

from contextlib import redirect_stdout
import io
import math
from types import SimpleNamespace

import pytest

from backend.service.application.models.evaluation.pycocotools_metrics import (
    evaluate_pycocotools_average_precision,
)
from backend.service.application.models.training.metric_policy import (
    resolve_best_metric_decision,
    serialize_training_metric,
)
from backend.service.application.models.training.yolo_classification_training_progress import (
    build_yolo_classification_epoch_progress_event,
)
from backend.service.application.models.yolo_core_common.training import (
    normalize_yolo_detection_loss_metrics,
)
from backend.service.application.models.yolo11_core.training.epoch import (
    resolve_yolo11_detection_best_metric_update,
)
from backend.service.application.models.yolo26_core.training.epoch import (
    resolve_yolo26_detection_best_metric_update,
)
from backend.service.application.models.yolov8_core.training.epoch import (
    resolve_yolov8_detection_best_metric_update,
)
from backend.service.application.models.yolox_core.training.trainer import (
    is_yolox_metric_improved,
)


def _build_single_box_ground_truth():
    """构建可由真实 pycocotools 评估的最小 COCO 数据集。"""

    coco_class = pytest.importorskip("pycocotools.coco").COCO
    ground_truth = coco_class()
    ground_truth.dataset = {
        "info": {"description": "amvision pycocotools regression"},
        "images": [{"id": 1, "file_name": "image.jpg", "width": 100, "height": 100}],
        "annotations": [
            {
                "id": 1,
                "image_id": 1,
                "category_id": 1,
                "bbox": [10.0, 20.0, 30.0, 40.0],
                "area": 1200.0,
                "iscrowd": 0,
            }
        ],
        "categories": [{"id": 1, "name": "object"}],
    }
    with redirect_stdout(io.StringIO()):
        ground_truth.createIndex()
    return ground_truth


def _build_two_category_ground_truth():
    """构建两个都有标注的类别，用于验证逐类别 AP。"""

    coco_class = pytest.importorskip("pycocotools.coco").COCO
    ground_truth = coco_class()
    ground_truth.dataset = {
        "info": {"description": "amvision per-category regression"},
        "images": [{"id": 1, "file_name": "image.jpg", "width": 100, "height": 100}],
        "annotations": [
            {
                "id": 1,
                "image_id": 1,
                "category_id": 1,
                "bbox": [10.0, 10.0, 20.0, 20.0],
                "area": 400.0,
                "iscrowd": 0,
            },
            {
                "id": 2,
                "image_id": 1,
                "category_id": 2,
                "bbox": [60.0, 60.0, 20.0, 20.0],
                "area": 400.0,
                "iscrowd": 0,
            },
        ],
        "categories": [
            {"id": 1, "name": "detected"},
            {"id": 2, "name": "missed"},
        ],
    }
    with redirect_stdout(io.StringIO()):
        ground_truth.createIndex()
    return ground_truth


def _build_segmentation_ground_truth():
    """构建真实 polygon segmentation COCO 数据集。"""

    coco_class = pytest.importorskip("pycocotools.coco").COCO
    ground_truth = coco_class()
    ground_truth.dataset = {
        "info": {"description": "amvision segmentation regression"},
        "images": [
            {"id": 1, "file_name": "image.jpg", "width": 32, "height": 32}
        ],
        "annotations": [
            {
                "id": 1,
                "image_id": 1,
                "category_id": 1,
                "bbox": [4.0, 4.0, 16.0, 16.0],
                "segmentation": [[4.0, 4.0, 20.0, 4.0, 20.0, 20.0, 4.0, 20.0]],
                "area": 256.0,
                "iscrowd": 0,
            }
        ],
        "categories": [{"id": 1, "name": "part"}],
    }
    with redirect_stdout(io.StringIO()):
        ground_truth.createIndex()
    return ground_truth


def _build_keypoint_ground_truth():
    """构建非 COCO-17 拓扑的真实 keypoints COCO 数据集。"""

    coco_class = pytest.importorskip("pycocotools.coco").COCO
    ground_truth = coco_class()
    ground_truth.dataset = {
        "info": {"description": "amvision keypoint regression"},
        "images": [
            {"id": 1, "file_name": "image.jpg", "width": 32, "height": 32}
        ],
        "annotations": [
            {
                "id": 1,
                "image_id": 1,
                "category_id": 1,
                "bbox": [4.0, 4.0, 20.0, 20.0],
                "area": 400.0,
                "iscrowd": 0,
                "num_keypoints": 2,
                "keypoints": [10.0, 10.0, 2.0, 20.0, 20.0, 2.0],
            }
        ],
        "categories": [
            {
                "id": 1,
                "name": "hand",
                "keypoints": ["root", "tip"],
                "skeleton": [[1, 2]],
            }
        ],
    }
    with redirect_stdout(io.StringIO()):
        ground_truth.createIndex()
    return ground_truth


def test_shared_coco_evaluator_uses_requested_max_detections_for_all_ap() -> None:
    """验证 maxDets=300 时 AP50 和 AP50-95 均来自相同评估切片。"""

    cocoeval_class = pytest.importorskip("pycocotools.cocoeval").COCOeval
    ground_truth = _build_single_box_ground_truth()
    detections = [
        {
            "image_id": 1,
            "category_id": 1,
            "bbox": [10.0, 20.0, 30.0, 40.0],
            "score": 0.99,
        }
    ]

    # 先固定复现旧实现：stats[0] 在 maxDets 不含 100 时返回 -1。
    with redirect_stdout(io.StringIO()):
        legacy_detections = ground_truth.loadRes(detections)
        legacy_evaluator = cocoeval_class(ground_truth, legacy_detections, "bbox")
        legacy_evaluator.params.maxDets = [1, 10, 300]
        legacy_evaluator.evaluate()
        legacy_evaluator.accumulate()
        legacy_evaluator.summarize()
    assert float(legacy_evaluator.stats[0]) == -1.0

    metrics = evaluate_pycocotools_average_precision(
        ground_truth=ground_truth,
        detections=detections,
        cocoeval_class=cocoeval_class,
        max_detections=300,
    )

    assert metrics.max_detections == 300
    assert metrics.map50 == pytest.approx(1.0)
    assert metrics.map50_95 == pytest.approx(1.0)


def test_shared_coco_evaluator_reports_real_per_category_ap() -> None:
    """逐类别 AP 必须来自真实 COCO precision 类别维度。"""

    cocoeval_class = pytest.importorskip("pycocotools.cocoeval").COCOeval
    ground_truth = _build_two_category_ground_truth()
    metrics = evaluate_pycocotools_average_precision(
        ground_truth=ground_truth,
        detections=[
            {
                "image_id": 1,
                "category_id": 1,
                "bbox": [10.0, 10.0, 20.0, 20.0],
                "score": 0.99,
            }
        ],
        cocoeval_class=cocoeval_class,
        max_detections=300,
    )

    assert metrics.map50 == pytest.approx(0.5)
    assert metrics.map50_95 == pytest.approx(0.5)
    assert [item.category_name for item in metrics.per_category] == [
        "detected",
        "missed",
    ]
    assert metrics.per_category[0].map50_95 == pytest.approx(1.0)
    assert metrics.per_category[1].map50_95 == pytest.approx(0.0)


def test_shared_coco_evaluator_reports_zero_per_category_without_detections() -> None:
    """完全无预测时仍应给每个有标注类别输出零 AP。"""

    cocoeval_class = pytest.importorskip("pycocotools.cocoeval").COCOeval
    metrics = evaluate_pycocotools_average_precision(
        ground_truth=_build_two_category_ground_truth(),
        detections=[],
        cocoeval_class=cocoeval_class,
        max_detections=300,
    )

    assert metrics.map50 == 0.0
    assert [item.map50_95 for item in metrics.per_category] == [0.0, 0.0]


def test_shared_coco_evaluator_runs_real_segmentation_metrics() -> None:
    """segmentation AP 必须来自真实 pycocotools mask IoU。"""

    cocoeval_class = pytest.importorskip("pycocotools.cocoeval").COCOeval
    metrics = evaluate_pycocotools_average_precision(
        ground_truth=_build_segmentation_ground_truth(),
        detections=[
            {
                "image_id": 1,
                "category_id": 1,
                "bbox": [4.0, 4.0, 16.0, 16.0],
                "segmentation": [[4.0, 4.0, 20.0, 4.0, 20.0, 20.0, 4.0, 20.0]],
                "score": 0.99,
            }
        ],
        cocoeval_class=cocoeval_class,
        iou_type="segm",
        max_detections=300,
    )

    assert metrics.map50 == pytest.approx(1.0)
    assert metrics.map50_95 == pytest.approx(1.0)


def test_shared_coco_evaluator_runs_real_non_coco_keypoint_metrics() -> None:
    """非 17 点 pose AP 必须显式设置等长 OKS sigma 后由 pycocotools 计算。"""

    cocoeval_class = pytest.importorskip("pycocotools.cocoeval").COCOeval
    metrics = evaluate_pycocotools_average_precision(
        ground_truth=_build_keypoint_ground_truth(),
        detections=[
            {
                "image_id": 1,
                "category_id": 1,
                "keypoints": [10.0, 10.0, 1.0, 20.0, 20.0, 1.0],
                "score": 0.99,
            }
        ],
        cocoeval_class=cocoeval_class,
        iou_type="keypoints",
        max_detections=300,
        keypoint_oks_sigmas=(0.5, 0.5),
    )

    assert metrics.map50 == pytest.approx(1.0)
    assert metrics.map50_95 == pytest.approx(1.0)


@pytest.mark.parametrize("batch_sample_count", [1, 2, 8, 16])
def test_detection_reported_total_loss_is_batch_size_invariant(
    batch_sample_count: int,
) -> None:
    """反向传播 total loss 的 batch 缩放不得泄漏到训练和验证报告。"""

    metrics = normalize_yolo_detection_loss_metrics(
        loss_components={
            "loss": 3.25 * batch_sample_count,
            "class_loss": 2.0,
            "box_loss": 1.0,
            "dfl_loss": 0.25,
        },
        batch_sample_count=batch_sample_count,
    )

    assert metrics == {
        "loss": pytest.approx(3.25),
        "class_loss": pytest.approx(2.0),
        "box_loss": pytest.approx(1.0),
        "dfl_loss": pytest.approx(0.25),
    }


@pytest.mark.parametrize(
    "invalid_value",
    [-1.0, float("nan"), float("inf"), float("-inf")],
)
def test_invalid_quality_metric_never_replaces_best_checkpoint(
    invalid_value: float,
) -> None:
    """验证负数和非有限质量指标不会参与 best 比较。"""

    decision = resolve_best_metric_decision(
        current_value=invalid_value,
        best_value=0.4,
        direction="maximize",
        minimum=0.0,
        maximum=1.0,
    )

    assert decision.improved is False
    assert decision.candidate_value == pytest.approx(0.4)
    assert math.isfinite(decision.candidate_value)


@pytest.mark.parametrize(
    "invalid_value",
    [-1.0, float("nan"), float("inf"), float("-inf"), None],
)
def test_invalid_metric_is_not_serialized_as_public_value(
    invalid_value: object,
) -> None:
    assert serialize_training_metric(invalid_value, maximum=1.0) is None


def test_classification_progress_hides_internal_best_metric_sentinel() -> None:
    progress = SimpleNamespace(
        epoch=0,
        max_epochs=200,
        evaluation_interval=5,
        validation_ran=False,
        input_size=(224, 224),
        learning_rate=0.001,
        train_metrics={"loss": 0.7, "accuracy": 0.5},
        validation_metrics={},
        train_metrics_snapshot={},
        validation_metrics_snapshot={},
        current_metric_name="val_top1_accuracy",
        current_metric_value=None,
        best_metric_name="val_top1_accuracy",
        best_metric_value=-1.0,
    )

    event = build_yolo_classification_epoch_progress_event(
        task_id="task-1",
        model_label="YOLO11 classification",
        model_type="yolo11",
        attempt_no=0,
        output_prefix="task-runs/task-1",
        train_metrics_object_key="train-metrics.json",
        validation_metrics_object_key="validation-metrics.json",
        progress=progress,
    )

    assert event.payload["progress"]["best_metric_value"] is None
    assert event.payload["result"]["best_metric_value"] is None


def test_equal_metric_preserves_historical_best_checkpoint() -> None:
    """验证相等指标不会反复覆盖已有 best checkpoint。"""

    decision = resolve_best_metric_decision(
        current_value=0.5,
        best_value=0.5,
        direction="maximize",
        minimum=0.0,
        maximum=1.0,
    )

    assert decision.improved is False
    assert decision.candidate_value == pytest.approx(0.5)


@pytest.mark.parametrize("invalid_best", [-1.0, float("nan"), float("inf"), None])
def test_valid_metric_replaces_corrupted_historical_best(invalid_best: object) -> None:
    """验证旧 checkpoint 的无效 best 不会阻止后续有效指标恢复。"""

    decision = resolve_best_metric_decision(
        current_value=0.25,
        best_value=invalid_best,
        direction="maximize",
        minimum=0.0,
        maximum=1.0,
    )

    assert decision.improved is True
    assert decision.candidate_value == pytest.approx(0.25)


def test_invalid_current_and_best_are_normalized_to_finite_value() -> None:
    """验证当前值和历史值同时损坏时不会继续传播 NaN/Inf。"""

    decision = resolve_best_metric_decision(
        current_value=float("nan"),
        best_value=float("inf"),
        direction="maximize",
        minimum=0.0,
        maximum=1.0,
    )

    assert decision.improved is False
    assert decision.candidate_value == 0.0


def test_invalid_minimized_metric_uses_finite_upper_fallback() -> None:
    """验证 loss 当前值和历史值同时损坏时仍允许后续有效值恢复。"""

    decision = resolve_best_metric_decision(
        current_value=float("nan"),
        best_value=float("inf"),
        direction="minimize",
        minimum=0.0,
    )

    assert decision.improved is False
    assert math.isfinite(decision.candidate_value)
    assert decision.candidate_value > 1.0
    assert resolve_best_metric_decision(
        current_value=1.0,
        best_value=decision.candidate_value,
        direction="minimize",
        minimum=0.0,
    ).improved is True


@pytest.mark.parametrize(
    "resolver",
    [
        resolve_yolov8_detection_best_metric_update,
        resolve_yolo11_detection_best_metric_update,
        resolve_yolo26_detection_best_metric_update,
    ],
)
@pytest.mark.parametrize("candidate", [-1.0, float("nan"), float("inf"), 0.5])
def test_detection_epoch_resolvers_preserve_valid_historical_best(
    resolver,
    candidate: float,
) -> None:
    """三个 detection epoch loop 都必须拒绝无效值和平值覆盖。"""

    update = resolver(
        has_validation=True,
        validation_ran=True,
        current_metric_value=candidate,
        train_loss=1.0,
        best_metric_value=0.5,
    )
    assert update.improved is False
    assert update.candidate_value == pytest.approx(0.5)


@pytest.mark.parametrize(
    "resolver",
    [
        resolve_yolov8_detection_best_metric_update,
        resolve_yolo11_detection_best_metric_update,
        resolve_yolo26_detection_best_metric_update,
    ],
)
def test_detection_epoch_resolvers_wait_for_validation_metric(resolver) -> None:
    """存在 validation 时，未到验证轮次不得拿 train loss 污染 best AP。"""

    update = resolver(
        has_validation=True,
        validation_ran=False,
        current_metric_value=None,
        train_loss=4.25,
        best_metric_value=float("-inf"),
    )

    assert update.improved is False
    assert update.candidate_value == float("-inf")


@pytest.mark.parametrize(
    "resolver",
    [
        resolve_yolov8_detection_best_metric_update,
        resolve_yolo11_detection_best_metric_update,
        resolve_yolo26_detection_best_metric_update,
    ],
)
def test_detection_epoch_resolvers_use_train_loss_without_validation(resolver) -> None:
    """没有 validation split 时才允许 train loss 驱动 best checkpoint。"""

    update = resolver(
        has_validation=False,
        validation_ran=False,
        current_metric_value=None,
        train_loss=4.25,
        best_metric_value=float("inf"),
    )

    assert update.improved is True
    assert update.candidate_value == pytest.approx(4.25)


@pytest.mark.parametrize("candidate", [-1.0, float("nan"), float("inf"), 0.5])
def test_yolox_best_metric_rule_rejects_invalid_values_and_ties(
    candidate: float,
) -> None:
    """YOLOX 也不得用无效指标或平值覆盖历史 best。"""

    assert (
        is_yolox_metric_improved(
            current_metric_value=candidate,
            best_metric_value=0.5,
            higher_is_better=True,
        )
        is False
    )
