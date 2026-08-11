"""训练参数严格协议与执行映射回归测试。"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal

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
    TRAINING_PARAMETER_SCHEMA_BY_TASK_AND_MODEL,
    RfdetrDetectionTrainingParameters,
    RfdetrSegmentationTrainingParameters,
    YoloClassificationTrainingParameters,
    Yolo26DetectionTrainingParameters,
    Yolo26ObbTrainingParameters,
    Yolo26PoseTrainingParameters,
    Yolo26SegmentationTrainingParameters,
    YoloDetectionTrainingParameters,
    YoloObbTrainingParameters,
    YoloPoseTrainingParameters,
    YoloSegmentationTrainingParameters,
    YoloXDetectionTrainingParameters,
)
from backend.service.api.rest.v1.routes.training_parameter_capabilities import (
    TRAINING_PARAMETER_CAPABILITIES_BY_TASK_AND_MODEL,
)
from backend.service.api.rest.v1.routes.training_execution_schemas import (
    TrainingExecutionPolicyRequest,
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
        ("yolo26", Yolo26DetectionTrainingParameters),
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
        (PoseTrainingTaskCreateRequestBody, "yolo26", Yolo26PoseTrainingParameters),
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


@pytest.mark.parametrize("model_type", ["yolov8", "yolo11", "yolo26"])
def test_yolo_segmentation_default_mask_gain_matches_reference_box_gain(
    model_type: str,
) -> None:
    """YOLO segmentation 默认 mask gain 应与参考实现的 box gain 一致。"""

    request = SegmentationTrainingTaskCreateRequestBody.model_validate(
        _base_request(model_type=model_type)
    )

    assert request.parameters.loss.box_weight == 7.5
    assert request.parameters.loss.mask_weight == 7.5
    assert request.parameters.to_execution_options()["mask_loss_weight"] == 7.5


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
    payload["execution"] = {"max_epochs": 3}
    request = DetectionTrainingTaskCreateRequestBody.model_validate(payload)
    options = request.parameters.to_execution_options()
    assert options["warmup_epochs"] == 2
    assert options["no_aug_epochs"] == 0

    payload["parameters"] = {"optimization": {"warmup_epochs": 3}}
    with pytest.raises(ValidationError, match="warmup_epochs"):
        DetectionTrainingTaskCreateRequestBody.model_validate(payload)


def test_training_execution_policy_defaults_to_auto_batch_amp_and_five_epoch_io() -> None:
    """公共执行策略默认使用 AutoBatch、AMP 和五轮磁盘/验证周期。"""

    execution = TrainingExecutionPolicyRequest()

    assert execution.max_epochs == 100
    assert execution.batch.mode == "auto"
    assert execution.batch.size is None
    assert execution.batch.target_memory_fraction == pytest.approx(0.6)
    assert execution.batch.recover_on_oom is True
    assert execution.batch.max_oom_retries == 3
    assert execution.amp.mode == "auto"
    assert execution.amp.dtype == "auto"
    assert execution.checkpoint.interval_epochs == 5
    assert execution.validation.interval_epochs == 5
    assert execution.fixed_batch_size is None
    assert execution.requested_precision is None
    assert execution.to_execution_options()["checkpoint_interval"] == 5
    assert execution.to_execution_options()["batch_recover_on_oom"] is True
    assert execution.to_execution_options()["batch_oom_max_retries"] == 3


def test_training_execution_policy_rejects_ambiguous_batch_and_amp_values() -> None:
    """AutoBatch、固定 batch 和关闭 AMP 的参数组合必须无歧义。"""

    with pytest.raises(ValidationError, match="必须提供 batch.size"):
        TrainingExecutionPolicyRequest.model_validate(
            {"batch": {"mode": "fixed"}}
        )
    with pytest.raises(ValidationError, match="不能提供 batch.size"):
        TrainingExecutionPolicyRequest.model_validate(
            {"batch": {"mode": "auto", "size": 16}}
        )
    with pytest.raises(ValidationError, match="maximum_size"):
        TrainingExecutionPolicyRequest.model_validate(
            {"batch": {"minimum_size": 32, "maximum_size": 16}}
        )
    with pytest.raises(ValidationError, match="amp.dtype"):
        TrainingExecutionPolicyRequest.model_validate(
            {"amp": {"mode": "disabled", "dtype": "fp16"}}
        )
    with pytest.raises(ValidationError, match="max_oom_retries"):
        TrainingExecutionPolicyRequest.model_validate(
            {"batch": {"max_oom_retries": 11}}
        )


@pytest.mark.parametrize(
    "request_schema",
    [
        DetectionTrainingTaskCreateRequestBody,
        ClassificationTrainingTaskCreateRequestBody,
        SegmentationTrainingTaskCreateRequestBody,
        PoseTrainingTaskCreateRequestBody,
        ObbTrainingTaskCreateRequestBody,
    ],
)
def test_training_requests_reject_removed_top_level_runtime_fields(
    request_schema: type,
) -> None:
    """v1 直接使用 execution，旧 batch/precision/evaluation 字段不再保留。"""

    for field_name, value in (
        ("batch_size", 16),
        ("precision", "fp16"),
        ("evaluation_interval", 5),
        ("max_epochs", 100),
    ):
        payload = _base_request(model_type="yolov8")
        payload[field_name] = value
        with pytest.raises(ValidationError, match=field_name):
            request_schema.model_validate(payload)


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
            "evaluation": {"confidence_threshold": 0.003},
            "augmentation": {"enabled": False},
        }
    )
    options = parameters.to_execution_options()
    assert options["device"] == "cuda:1"
    assert options["learning_rate"] == 0.001
    assert options["kpt_loss_weight"] == 9.0
    assert options["assign_topk"] == 7
    assert options["evaluation_confidence_threshold"] == 0.003
    assert "keypoint_confidence_threshold" not in options
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
    assert set(TRAINING_PARAMETER_CAPABILITIES_BY_TASK_AND_MODEL) == set(
        TRAINING_PARAMETER_SCHEMA_BY_TASK_AND_MODEL
    )
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


@pytest.mark.parametrize(
    ("task_type", "request_schema", "expected_parameter_schema"),
    [
        ("detection", DetectionTrainingTaskCreateRequestBody, Yolo26DetectionTrainingParameters),
        (
            "segmentation",
            SegmentationTrainingTaskCreateRequestBody,
            Yolo26SegmentationTrainingParameters,
        ),
        ("pose", PoseTrainingTaskCreateRequestBody, Yolo26PoseTrainingParameters),
        ("obb", ObbTrainingTaskCreateRequestBody, Yolo26ObbTrainingParameters),
    ],
)
def test_yolo26_end_to_end_tasks_reject_nms_parameter(
    task_type: str,
    request_schema: type,
    expected_parameter_schema: type,
) -> None:
    """YOLO26 end-to-end 任务不能接受或展示 NMS 参数。"""

    catalog_item = list_training_parameter_schemas(
        principal=object(),
        task_type=task_type,
        model_type="yolo26",
    ).items[0]
    assert catalog_item.capabilities.postprocess_mode == "end_to_end"
    assert catalog_item.capabilities.supports_nms_threshold is False
    assert catalog_item.capabilities.distribution_loss_name == "l1_loss"
    numeric_keys = {
        field.key for field in catalog_item.numeric_fields
    }
    assert "evaluation_nms_threshold" not in numeric_keys
    if task_type in {"detection", "segmentation", "pose"}:
        assert "l1_loss_weight" in numeric_keys
        assert "dfl_loss_weight" not in numeric_keys

    request = request_schema.model_validate(_base_request(model_type="yolo26"))
    assert isinstance(request.parameters, expected_parameter_schema)
    payload = _base_request(model_type="yolo26")
    payload["parameters"] = {"evaluation": {"nms_threshold": 0.7}}
    with pytest.raises(ValidationError, match="nms_threshold"):
        request_schema.model_validate(payload)

    if task_type in {"detection", "segmentation", "pose"}:
        l1_payload = _base_request(model_type="yolo26")
        l1_payload["parameters"] = {"loss": {"l1_weight": 2.0}}
        l1_request = request_schema.model_validate(l1_payload)
        execution_options = l1_request.parameters.to_execution_options()
        assert execution_options["l1_loss_weight"] == 2.0
        assert "dfl_loss_weight" not in execution_options

        legacy_payload = _base_request(model_type="yolo26")
        legacy_payload["parameters"] = {"loss": {"dfl_weight": 1.5}}
        with pytest.raises(ValidationError, match="dfl_weight"):
            request_schema.model_validate(legacy_payload)


def test_capability_nms_flag_matches_every_public_numeric_catalog() -> None:
    """能力声明和页面数值字段必须由同一模型语义约束。"""

    catalog = list_training_parameter_schemas(
        principal=object(),
        task_type=None,
        model_type=None,
    )
    for item in catalog.items:
        exposes_nms = "evaluation_nms_threshold" in {
            field.key for field in item.numeric_fields
        }
        assert exposes_nms is item.capabilities.supports_nms_threshold


def test_training_parameter_catalog_exposes_aligned_numeric_input_specs() -> None:
    """全部公开数值字段必须具有可由浏览器和 API 共同执行的离散精度。"""

    catalog = list_training_parameter_schemas(
        principal=object(),
        task_type=None,
        model_type=None,
    )
    for item in catalog.items:
        assert item.numeric_fields
        assert len({field.key for field in item.numeric_fields}) == len(
            item.numeric_fields
        )
        for field in item.numeric_fields:
            step = Decimal(str(field.step))
            minimum = Decimal(str(field.minimum))
            maximum = Decimal(str(field.maximum))
            default_value = Decimal(str(field.default_value))
            assert step > 0
            assert minimum <= default_value <= maximum
            assert minimum % step == 0, (
                item.task_type,
                item.model_type,
                field.key,
            )
            assert default_value % step == 0, (
                item.task_type,
                item.model_type,
                field.key,
            )
            assert maximum % step == 0, (
                item.task_type,
                item.model_type,
                field.key,
            )
            assert field.decimals == max(0, -step.normalize().as_tuple().exponent)


def test_every_public_float_parameter_declares_multiple_of() -> None:
    """严格训练 schema 的全部 float 叶子都必须声明确定精度。"""

    missing_paths: list[str] = []
    for (task_type, model_type), schema_type in sorted(
        TRAINING_PARAMETER_SCHEMA_BY_TASK_AND_MODEL.items()
    ):
        root_schema = schema_type.model_json_schema()
        definitions = root_schema.get("$defs", {})

        def visit(value: object, path: str) -> None:
            if not isinstance(value, Mapping):
                return
            reference = value.get("$ref")
            if isinstance(reference, str) and reference.startswith("#/$defs/"):
                visit(definitions.get(reference.removeprefix("#/$defs/")), path)
                return
            if value.get("type") == "number" and "multipleOf" not in value:
                missing_paths.append(f"{task_type}/{model_type}/{path}")
            properties = value.get("properties")
            if isinstance(properties, Mapping):
                for property_name, property_schema in properties.items():
                    visit(
                        property_schema,
                        f"{path}.{property_name}".strip("."),
                    )
            variants = value.get("anyOf")
            if isinstance(variants, list):
                for variant in variants:
                    visit(variant, path)

        visit(root_schema, "")

    assert missing_paths == []


def test_training_parameter_catalog_uses_model_specific_decimal_steps() -> None:
    """学习率和增强比例必须按模型语义公开不同的实际输入精度。"""

    yolo = list_training_parameter_schemas(
        principal=object(),
        task_type="detection",
        model_type="yolo26",
    ).items[0]
    yolo_fields = {field.key: field for field in yolo.numeric_fields}
    assert yolo_fields["learning_rate"].step == pytest.approx(0.00001)
    assert yolo_fields["learning_rate"].default_value == pytest.approx(0.01)
    assert yolo_fields["grad_clip_norm"].step == pytest.approx(0.1)
    assert yolo_fields["hsv_h"].minimum == pytest.approx(0.0)
    assert yolo_fields["hsv_h"].step == pytest.approx(0.001)
    assert yolo_fields["hsv_h"].default_value == pytest.approx(0.015)
    assert "mosaic_scale_min" not in yolo_fields
    assert "mixup_scale_min" not in yolo_fields
    assert "evaluation_nms_threshold" not in yolo_fields

    rfdetr = list_training_parameter_schemas(
        principal=object(),
        task_type="detection",
        model_type="rfdetr",
    ).items[0]
    rfdetr_fields = {field.key: field for field in rfdetr.numeric_fields}
    assert rfdetr_fields["learning_rate"].step == pytest.approx(0.000001)


def test_training_parameter_schema_rejects_values_outside_public_step_grid() -> None:
    """直接调用 API schema 也必须拒绝页面不允许的超精度数值。"""

    with pytest.raises(ValidationError, match="multiple"):
        YoloDetectionTrainingParameters.model_validate(
            {"optimization": {"optimizer": "adamw", "learning_rate": 0.000011}}
        )
    with pytest.raises(ValidationError, match="Extra inputs"):
        YoloDetectionTrainingParameters.model_validate(
            {"augmentation": {"mosaic_scale": {"minimum": 0.505, "maximum": 1.5}}}
        )

    with pytest.raises(ValidationError, match="Extra inputs"):
        YoloDetectionTrainingParameters.model_validate(
            {"augmentation": {"mixup_scale": {"minimum": 0.5, "maximum": 1.5}}}
        )
