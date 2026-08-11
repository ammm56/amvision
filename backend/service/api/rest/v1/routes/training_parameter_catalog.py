"""训练参数表单目录构建。

该模块把严格 Pydantic schema 中的数值边界、multipleOf 和默认值转换为
前端可直接使用的扁平字段规格。表单字段名只负责页面状态绑定，真实数值约束
始终从后端公开 schema 读取，避免前后端分别维护范围和步长。
"""

from __future__ import annotations

from decimal import Decimal
from typing import Mapping

from backend.service.api.rest.v1.routes.models.schemas import (
    TrainingNumericParameterSpecResponse,
)
from backend.service.api.rest.v1.routes.training_parameter_schemas import (
    StrictTrainingParameters,
)


_YOLO_RUNTIME_NUMERIC_PATHS: dict[str, str] = {
    "num_workers": "runtime.num_workers",
    "prefetch_factor": "runtime.prefetch_factor",
}

_YOLO_OPTIMIZATION_NUMERIC_PATHS: dict[str, str] = {
    "learning_rate": "optimization.learning_rate",
    "weight_decay": "optimization.weight_decay",
    "min_lr_ratio": "optimization.min_lr_ratio",
    "grad_clip_norm": "optimization.grad_clip_norm",
}

_YOLO_EVALUATION_NUMERIC_PATHS: dict[str, str] = {
    "evaluation_confidence_threshold": "evaluation.confidence_threshold",
}

_YOLO_NMS_NUMERIC_PATHS: dict[str, str] = {
    "evaluation_nms_threshold": "evaluation.nms_threshold",
}

_YOLO_MATCHING_NUMERIC_PATHS: dict[str, str] = {
    "assign_topk": "matching.topk",
    "assign_alpha": "matching.alpha",
    "assign_beta": "matching.beta",
}

_YOLO_AUGMENTATION_NUMERIC_PATHS: dict[str, str] = {
    "flip_prob": "augmentation.horizontal_flip_probability",
    "hsv_h": "augmentation.hue_gain",
    "hsv_s": "augmentation.saturation_gain",
    "hsv_v": "augmentation.value_gain",
    "mosaic_prob": "augmentation.mosaic_probability",
    "mixup_prob": "augmentation.mixup_probability",
    "affine_prob": "augmentation.affine_probability",
    "degrees": "augmentation.rotation_degrees",
    "translate": "augmentation.translation_ratio",
    "scale": "augmentation.scale_ratio",
    "shear": "augmentation.shear_degrees",
    "perspective": "augmentation.perspective_ratio",
    "close_mosaic": "augmentation.close_mosaic_epochs",
    "multi_scale": "augmentation.multi_scale_ratio",
    "multi_scale_stride": "augmentation.multi_scale_stride",
}

_YOLOX_NUMERIC_PATHS: dict[str, str] = {
    "seed": "runtime.seed",
    "num_workers": "runtime.num_workers",
    "prefetch_factor": "runtime.prefetch_factor",
    "max_labels": "data.max_labels_per_image",
    "evaluation_confidence_threshold": "evaluation.confidence_threshold",
    "evaluation_nms_threshold": "evaluation.nms_threshold",
    "flip_prob": "augmentation.horizontal_flip_probability",
    "hsv_prob": "augmentation.hsv_probability",
    "mosaic_prob": "augmentation.mosaic_probability",
    "mixup_prob": "augmentation.mixup_probability",
    "degrees": "augmentation.rotation_degrees",
    "translate": "augmentation.translation_ratio",
    "shear": "augmentation.shear_degrees",
    "mosaic_scale_min": "augmentation.mosaic_scale.minimum",
    "mosaic_scale_max": "augmentation.mosaic_scale.maximum",
    "mixup_scale_min": "augmentation.mixup_scale.minimum",
    "mixup_scale_max": "augmentation.mixup_scale.maximum",
    "multiscale_range": "augmentation.multiscale_range",
    "no_aug_epochs": "optimization.no_aug_epochs",
    "warmup_epochs": "optimization.warmup_epochs",
    "min_lr_ratio": "optimization.min_lr_ratio",
}

_RFDETR_NUMERIC_PATHS: dict[str, str] = {
    "num_workers": "runtime.num_workers",
    "learning_rate": "optimization.learning_rate",
    "weight_decay": "optimization.weight_decay",
    "min_lr_ratio": "optimization.min_lr_ratio",
    "grad_accum_steps": "optimization.grad_accum_steps",
    "class_cost": "matching.class_cost",
    "bbox_cost": "matching.bbox_cost",
    "giou_cost": "matching.giou_cost",
    "class_loss_weight": "loss.class_weight",
    "bbox_loss_weight": "loss.bbox_weight",
    "giou_loss_weight": "loss.giou_weight",
    "evaluation_max_detections": "evaluation.max_detections",
}

_CLASSIFICATION_AUGMENTATION_NUMERIC_PATHS: dict[str, str] = {
    "flip_prob": "augmentation.horizontal_flip_probability",
    "crop_scale_min": "augmentation.crop_scale.minimum",
    "crop_scale_max": "augmentation.crop_scale.maximum",
    "rotation_degrees": "augmentation.rotation_degrees",
    "translate_ratio": "augmentation.translation_ratio",
    "scale_min": "augmentation.affine_scale.minimum",
    "scale_max": "augmentation.affine_scale.maximum",
    "brightness_gain": "augmentation.brightness_gain",
    "contrast_gain": "augmentation.contrast_gain",
    "gamma_min": "augmentation.gamma.minimum",
    "gamma_max": "augmentation.gamma.maximum",
    "hue_gain": "augmentation.hue_gain",
    "saturation_gain": "augmentation.saturation_gain",
    "value_gain": "augmentation.value_gain",
    "random_erasing_prob": "augmentation.random_erasing_probability",
}


def _merge_paths(*mappings: Mapping[str, str]) -> dict[str, str]:
    """合并字段路径并拒绝名称冲突。"""

    result: dict[str, str] = {}
    for mapping in mappings:
        duplicates = result.keys() & mapping.keys()
        if duplicates:
            raise ValueError(f"训练参数目录存在重复字段: {sorted(duplicates)}")
        result.update(mapping)
    return result


def get_training_numeric_parameter_paths(
    *, task_type: str, model_type: str
) -> dict[str, str]:
    """返回指定任务和模型的公开数值字段到严格 schema 路径映射。"""

    task = str(task_type).strip().lower()
    model = str(model_type).strip().lower()
    if task == "detection" and model == "yolox":
        return dict(_YOLOX_NUMERIC_PATHS)
    if model == "rfdetr":
        paths = dict(_RFDETR_NUMERIC_PATHS)
        if task == "segmentation":
            paths.update(
                {
                    "mask_ce_weight": "loss.mask_ce_weight",
                    "mask_dice_weight": "loss.mask_dice_weight",
                }
            )
        return paths

    paths = _merge_paths(
        _YOLO_RUNTIME_NUMERIC_PATHS,
        _YOLO_OPTIMIZATION_NUMERIC_PATHS,
    )
    if task == "classification":
        return _merge_paths(paths, _CLASSIFICATION_AUGMENTATION_NUMERIC_PATHS)

    paths = _merge_paths(paths, _YOLO_EVALUATION_NUMERIC_PATHS)
    if model != "yolo26":
        paths = _merge_paths(paths, _YOLO_NMS_NUMERIC_PATHS)
    if task == "detection":
        regression_loss_path = (
            {"l1_loss_weight": "loss.l1_weight"}
            if model == "yolo26"
            else {"dfl_loss_weight": "loss.dfl_weight"}
        )
        paths = _merge_paths(
            paths,
            {
                "class_loss_weight": "loss.class_weight",
                "box_loss_weight": "loss.box_weight",
            },
            regression_loss_path,
            _YOLO_MATCHING_NUMERIC_PATHS,
        )
    elif task == "segmentation":
        regression_loss_path = (
            {"l1_loss_weight": "loss.l1_weight"}
            if model == "yolo26"
            else {"dfl_loss_weight": "loss.dfl_weight"}
        )
        paths = _merge_paths(
            paths,
            {
                "class_loss_weight": "loss.class_weight",
                "box_loss_weight": "loss.box_weight",
                "mask_loss_weight": "loss.mask_weight",
            },
            regression_loss_path,
            _YOLO_MATCHING_NUMERIC_PATHS,
        )
    elif task == "pose":
        regression_loss_path = (
            {"l1_loss_weight": "loss.l1_weight"}
            if model == "yolo26"
            else {"dfl_loss_weight": "loss.dfl_weight"}
        )
        paths = _merge_paths(
            paths,
            {
                "class_loss_weight": "loss.class_weight",
                "box_loss_weight": "loss.box_weight",
                "kpt_loss_weight": "loss.keypoint_weight",
            },
            regression_loss_path,
            _YOLO_MATCHING_NUMERIC_PATHS,
        )
    elif task != "obb":
        raise ValueError("指定 task_type/model_type 没有训练数值参数目录")
    return _merge_paths(paths, _YOLO_AUGMENTATION_NUMERIC_PATHS)


def _resolve_reference(
    *, root_schema: Mapping[str, object], value: Mapping[str, object]
) -> Mapping[str, object]:
    """解析当前 JSON Schema 节点的本地引用。"""

    reference = value.get("$ref")
    if not isinstance(reference, str):
        return value
    prefix = "#/$defs/"
    if not reference.startswith(prefix):
        raise ValueError(f"训练参数 schema 使用了不支持的引用: {reference}")
    definitions = root_schema.get("$defs")
    if not isinstance(definitions, Mapping):
        raise ValueError("训练参数 schema 缺少 $defs")
    resolved = definitions.get(reference[len(prefix) :])
    if not isinstance(resolved, Mapping):
        raise ValueError(f"训练参数 schema 引用不存在: {reference}")
    return resolved


def _select_numeric_schema(value: Mapping[str, object]) -> Mapping[str, object]:
    """从可空 schema 中选择整数或浮点分支。"""

    if value.get("type") in {"integer", "number"}:
        return value
    variants = value.get("anyOf")
    if isinstance(variants, list):
        for variant in variants:
            if isinstance(variant, Mapping) and variant.get("type") in {
                "integer",
                "number",
            }:
                selected = dict(variant)
                if "x-ui-default" in value:
                    selected["x-ui-default"] = value["x-ui-default"]
                return selected
    raise ValueError("训练参数字段不是数值 schema")


def _read_schema_path(
    *, root_schema: Mapping[str, object], schema_path: str
) -> Mapping[str, object]:
    """读取严格训练 schema 中的字段节点。"""

    current: Mapping[str, object] = root_schema
    for token in schema_path.split("."):
        current = _resolve_reference(root_schema=root_schema, value=current)
        properties = current.get("properties")
        if not isinstance(properties, Mapping):
            raise ValueError(f"训练参数 schema 路径没有 properties: {schema_path}")
        child = properties.get(token)
        if not isinstance(child, Mapping):
            raise ValueError(f"训练参数 schema 路径不存在: {schema_path}")
        current = child
    current = _resolve_reference(root_schema=root_schema, value=current)
    return _select_numeric_schema(current)


def _read_default_path(*, defaults: Mapping[str, object], schema_path: str) -> object:
    """读取训练参数实例中的默认值。"""

    current: object = defaults
    for token in schema_path.split("."):
        if not isinstance(current, Mapping) or token not in current:
            raise ValueError(f"训练参数默认值路径不存在: {schema_path}")
        current = current[token]
    return current


def _decimal_places(step: int | float) -> int:
    """计算十进制步长需要显示的小数位数。"""

    exponent = Decimal(str(step)).normalize().as_tuple().exponent
    return max(0, -int(exponent))


def build_training_numeric_parameter_specs(
    *, task_type: str, model_type: str, schema: type[StrictTrainingParameters]
) -> list[TrainingNumericParameterSpecResponse]:
    """从唯一训练 schema 构建前端可直接使用的数值规格。"""

    parameter_schema = schema.model_json_schema()
    defaults = schema().model_dump(mode="json")
    paths = get_training_numeric_parameter_paths(
        task_type=task_type,
        model_type=model_type,
    )
    result: list[TrainingNumericParameterSpecResponse] = []
    for key, schema_path in paths.items():
        field_schema = _read_schema_path(
            root_schema=parameter_schema,
            schema_path=schema_path,
        )
        value_kind = "int" if field_schema.get("type") == "integer" else "float"
        minimum = field_schema.get("minimum")
        maximum = field_schema.get("maximum")
        if not isinstance(minimum, (int, float)) or not isinstance(
            maximum, (int, float)
        ):
            raise ValueError(f"训练数值字段缺少闭区间: {schema_path}")
        step: object = 1 if value_kind == "int" else field_schema.get("multipleOf")
        if not isinstance(step, (int, float)) or step <= 0:
            raise ValueError(f"训练数值字段缺少有效 multipleOf: {schema_path}")
        default_value = _read_default_path(
            defaults=defaults,
            schema_path=schema_path,
        )
        if default_value is None:
            default_value = field_schema.get("x-ui-default")
        if not isinstance(default_value, (int, float)):
            raise ValueError(f"训练数值字段缺少有效默认值: {schema_path}")
        result.append(
            TrainingNumericParameterSpecResponse(
                key=key,
                schema_path=schema_path,
                value_kind=value_kind,
                minimum=minimum,
                maximum=maximum,
                step=step,
                decimals=_decimal_places(step),
                default_value=default_value,
            )
        )
    return result


__all__ = [
    "build_training_numeric_parameter_specs",
    "get_training_numeric_parameter_paths",
]
