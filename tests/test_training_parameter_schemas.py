"""训练参数严格协议与执行映射回归测试。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.service.api.rest.v1.routes.classification_training_tasks.schemas import (
    ClassificationTrainingTaskCreateRequestBody,
)
from backend.service.api.rest.v1.routes.detection_training_tasks.schemas import (
    DetectionTrainingTaskCreateRequestBody,
)
from backend.service.api.rest.v1.routes.obb_training_tasks.schemas import (
    ObbTrainingTaskCreateRequestBody,
)
from backend.service.api.rest.v1.routes.models.router import (
    list_training_parameter_schemas,
)
from backend.service.api.rest.v1.routes.pose_training_tasks.schemas import (
    PoseTrainingTaskCreateRequestBody,
)
from backend.service.api.rest.v1.routes.segmentation_training_tasks.schemas import (
    SegmentationTrainingTaskCreateRequestBody,
)
from backend.service.api.rest.v1.routes.training_parameter_schemas import (
    RfdetrDetectionTrainingParameters,
    RfdetrSegmentationTrainingParameters,
    YoloClassificationTrainingParameters,
    YoloDetectionTrainingParameters,
    YoloObbTrainingParameters,
    YoloPoseTrainingParameters,
    YoloSegmentationTrainingParameters,
    YoloXDetectionTrainingParameters,
)


def _base_request(*, model_type: str) -> dict[str, object]:
    """构造最小训练请求。"""

    return {
        "project_id": "project-1",
        "model_type": model_type,
        "dataset_export_id": "export-1",
        "model_scale": "s",
        "output_model_name": "model-1",
    }


@pytest.mark.parametrize(
    ("model_type", "expected_type"),
    [
        ("yolox", YoloXDetectionTrainingParameters),
        ("yolov8", YoloDetectionTrainingParameters),
        ("yolo11", YoloDetectionTrainingParameters),
        ("yolo26", YoloDetectionTrainingParameters),
        ("rfdetr", RfdetrDetectionTrainingParameters),
    ],
)
def test_detection_request_selects_exact_model_parameter_schema(
    model_type: str,
    expected_type: type,
) -> None:
    """同一个 detection endpoint 必须按 model_type 选择唯一 schema。"""

    request = DetectionTrainingTaskCreateRequestBody.model_validate(
        _base_request(model_type=model_type)
    )
    assert isinstance(request.parameters, expected_type)


@pytest.mark.parametrize(
    ("schema", "model_type", "expected_type"),
    [
        (
            ClassificationTrainingTaskCreateRequestBody,
            "yolov8",
            YoloClassificationTrainingParameters,
        ),
        (
            SegmentationTrainingTaskCreateRequestBody,
            "yolo11",
            YoloSegmentationTrainingParameters,
        ),
        (
            SegmentationTrainingTaskCreateRequestBody,
            "rfdetr",
            RfdetrSegmentationTrainingParameters,
        ),
        (PoseTrainingTaskCreateRequestBody, "yolo26", YoloPoseTrainingParameters),
        (ObbTrainingTaskCreateRequestBody, "yolov8", YoloObbTrainingParameters),
    ],
)
def test_non_detection_request_selects_task_parameter_schema(
    schema: type,
    model_type: str,
    expected_type: type,
) -> None:
    """非 detection 任务也不能回退到无类型字典。"""

    request = schema.model_validate(_base_request(model_type=model_type))
    assert isinstance(request.parameters, expected_type)


def test_request_rejects_removed_extra_options_and_unknown_nested_fields() -> None:
    """旧扁平入口和拼写错误必须在任务入队前失败。"""

    payload = _base_request(model_type="yolo11")
    payload["extra_options"] = {"learning_rate": 0.001}
    with pytest.raises(ValidationError, match="extra_options"):
        DetectionTrainingTaskCreateRequestBody.model_validate(payload)

    payload = _base_request(model_type="yolo11")
    payload["parameters"] = {"optimization": {"learnig_rate": 0.001}}
    with pytest.raises(ValidationError, match="learnig_rate"):
        DetectionTrainingTaskCreateRequestBody.model_validate(payload)


def test_request_rejects_parameters_from_another_model_family() -> None:
    """RF-DETR 请求不能携带 YOLO Mosaic 参数，反向同理。"""

    payload = _base_request(model_type="rfdetr")
    payload["parameters"] = {
        "augmentation": {"mosaic_probability": 0.5},
    }
    with pytest.raises(ValidationError, match="mosaic_probability"):
        DetectionTrainingTaskCreateRequestBody.model_validate(payload)

    payload = _base_request(model_type="yolox")
    payload["parameters"] = {
        "optimization": {"lr_scheduler": "cosine"},
    }
    with pytest.raises(ValidationError, match="lr_scheduler"):
        DetectionTrainingTaskCreateRequestBody.model_validate(payload)


@pytest.mark.parametrize(
    "bad_value",
    [float("nan"), float("inf"), float("-inf"), -0.1, 1.1],
)
def test_probability_rejects_non_finite_and_out_of_range_values(
    bad_value: float,
) -> None:
    """概率参数不得产生 NaN、Infinity 或越界值。"""

    payload = _base_request(model_type="yolov8")
    payload["parameters"] = {"augmentation": {"horizontal_flip_probability": bad_value}}
    with pytest.raises(ValidationError):
        DetectionTrainingTaskCreateRequestBody.model_validate(payload)


def test_optimizer_learning_rate_has_explicit_semantics() -> None:
    """auto 不接受伪学习率，显式 optimizer 必须给出真实学习率。"""

    with pytest.raises(ValidationError, match="optimizer=auto"):
        YoloDetectionTrainingParameters.model_validate(
            {"optimization": {"optimizer": "auto", "learning_rate": 0.01}}
        )
    with pytest.raises(ValidationError, match="必须指定 learning_rate"):
        YoloDetectionTrainingParameters.model_validate(
            {"optimization": {"optimizer": "adamw"}}
        )

    parameters = YoloDetectionTrainingParameters.model_validate(
        {"optimization": {"optimizer": "adamw", "learning_rate": 0.001}}
    )
    assert parameters.to_execution_options()["learning_rate"] == 0.001


def test_classification_rejects_manual_augmentation_hidden_by_auto_policy() -> None:
    """会被 auto_augment 忽略的非中性参数不得进入任务快照。"""

    with pytest.raises(ValidationError, match="auto_augment"):
        YoloClassificationTrainingParameters.model_validate(
            {
                "augmentation": {
                    "auto_augment": "randaugment",
                    "rotation_degrees": 10.0,
                }
            }
        )


def test_short_yolox_training_resolves_only_implicit_schedule_defaults() -> None:
    """短训练会固化解析后的默认调度，但无效显式值会被拒绝。"""

    payload = _base_request(model_type="yolox")
    payload["max_epochs"] = 3
    request = DetectionTrainingTaskCreateRequestBody.model_validate(payload)
    options = request.parameters.to_execution_options()
    assert options["warmup_epochs"] == 2
    assert options["no_aug_epochs"] == 0

    payload["parameters"] = {"optimization": {"warmup_epochs": 3}}
    with pytest.raises(ValidationError, match="warmup_epochs"):
        DetectionTrainingTaskCreateRequestBody.model_validate(payload)


def test_execution_mapping_uses_runner_keys_and_disables_augmentation() -> None:
    """嵌套协议只在执行边界映射为 runner 字段。"""

    parameters = YoloPoseTrainingParameters.model_validate(
        {
            "runtime": {"device": "cuda:1", "num_workers": 0},
            "optimization": {
                "optimizer": "adamw",
                "learning_rate": 0.001,
            },
            "loss": {"keypoint_weight": 9.0},
            "matching": {"topk": 7},
            "evaluation": {"keypoint_confidence_threshold": 0.3},
            "augmentation": {"enabled": False},
        }
    )
    options = parameters.to_execution_options()
    assert options["device"] == "cuda:1"
    assert options["learning_rate"] == 0.001
    assert options["kpt_loss_weight"] == 9.0
    assert options["assign_topk"] == 7
    assert options["keypoint_confidence_threshold"] == 0.3
    assert options["disable_augmentation"] is True
    assert options["mosaic_prob"] == 0.0


def test_obb_does_not_expose_unimplemented_loss_or_matching_parameters() -> None:
    """OBB runner 未读取的旧损失和匹配字段不再公开。"""

    for unsupported_group in ("loss", "matching"):
        with pytest.raises(ValidationError, match=unsupported_group):
            YoloObbTrainingParameters.model_validate({unsupported_group: {}})


def test_rfdetr_step_scheduler_does_not_emit_unused_minimum_lr() -> None:
    """RF-DETR step scheduler 不把无效的 cosine 参数写入 runner。"""

    parameters = RfdetrDetectionTrainingParameters()
    options = parameters.to_execution_options()
    assert options["lr_scheduler"] == "step"
    assert "min_lr_ratio" not in options


def test_training_parameter_catalog_exposes_all_supported_task_model_pairs() -> None:
    """参数目录必须覆盖支持矩阵中的全部 18 个训练组合。"""

    catalog = list_training_parameter_schemas(
        principal=object(),
        task_type=None,
        model_type=None,
    )
    assert catalog.protocol_version == 1
    assert len(catalog.items) == 18
    assert len({(item.task_type, item.model_type) for item in catalog.items}) == 18
    assert all(
        item.parameter_schema.get("additionalProperties") is False
        for item in catalog.items
    )

    filtered = list_training_parameter_schemas(
        principal=object(),
        task_type="segmentation",
        model_type="rfdetr",
    )
    assert [(item.task_type, item.model_type) for item in filtered.items] == [
        ("segmentation", "rfdetr")
    ]
