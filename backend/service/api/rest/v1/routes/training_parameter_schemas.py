"""训练任务公开参数协议。

公开 API 使用按模型族和任务拆分的嵌套参数；只有在进入训练执行边界时，才会
展开为现有 runner 使用的扁平配置。这样可以同时保证 OpenAPI 可读、未知字段被
拒绝，并且每一个公开参数都有明确的执行去向。
"""

from __future__ import annotations

from typing import Final, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, model_validator


TrainingDevice: TypeAlias = Literal["auto", "cpu", "cuda"] | str
YoloOptimizer: TypeAlias = Literal[
    "auto",
    "musgd",
    "sgd",
    "adamw",
    "adam",
    "nadam",
    "radam",
    "rmsprop",
]


class StrictTrainingParameters(BaseModel):
    """训练参数公共严格基类。"""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    def to_execution_options(self) -> dict[str, object]:
        """把分组参数展开为 runner 使用的唯一配置字典。"""

        options: dict[str, object] = {}
        for group_name, group in self:
            if group is None:
                continue
            if not isinstance(group, BaseModel):
                raise TypeError(f"训练参数组 {group_name} 必须是 BaseModel")
            if hasattr(group, "to_execution_options"):
                group_options = group.to_execution_options()
            else:
                group_options = group.model_dump(exclude_none=True)
            duplicate_keys = options.keys() & group_options.keys()
            if duplicate_keys:
                raise ValueError(
                    f"训练参数组存在重复执行字段: {sorted(duplicate_keys)}"
                )
            options.update(group_options)
        return options


class TrainingParameterGroup(BaseModel):
    """训练参数分组公共严格基类。"""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class YoloRuntimeParameters(TrainingParameterGroup):
    """YOLO 主线通用运行与 DataLoader 参数。"""

    device: str = Field(
        default="auto",
        pattern=r"^(auto|cpu|cuda|cuda:[0-9]+)$",
        description="单卡训练设备",
    )
    seed: int = Field(default=0, ge=0, le=4_294_967_295)
    num_workers: int = Field(default=2, ge=0, le=64)
    prefetch_factor: int = Field(default=2, ge=1, le=32)
    pin_memory: bool | None = None
    persistent_workers: bool | None = None

    @model_validator(mode="after")
    def validate_worker_options(self) -> "YoloRuntimeParameters":
        """禁止在单进程 DataLoader 上启用持久 worker。"""

        if self.num_workers == 0 and self.persistent_workers is True:
            raise ValueError("num_workers=0 时 persistent_workers 不能为 true")
        return self


class YoloXRuntimeParameters(TrainingParameterGroup):
    """YOLOX 运行与 DataLoader 参数。"""

    device: str = Field(
        default="auto",
        pattern=r"^(auto|cpu|cuda|cuda:[0-9]+)$",
    )
    seed: int = Field(default=0, ge=0, le=4_294_967_295)
    num_workers: int = Field(default=0, ge=0, le=64)
    prefetch_factor: int = Field(default=2, ge=1, le=32)
    persistent_workers: bool | None = None

    @model_validator(mode="after")
    def validate_worker_options(self) -> "YoloXRuntimeParameters":
        """禁止在单进程 DataLoader 上启用持久 worker。"""

        if self.num_workers == 0 and self.persistent_workers is True:
            raise ValueError("num_workers=0 时 persistent_workers 不能为 true")
        return self


class RfdetrRuntimeParameters(TrainingParameterGroup):
    """RF-DETR 单设备运行参数。"""

    device: str = Field(
        default="auto",
        pattern=r"^(auto|cpu|cuda|cuda:[0-9]+)$",
    )
    num_workers: int = Field(default=2, ge=0, le=64)


class YoloOptimizationParameters(TrainingParameterGroup):
    """YOLO 主线优化器与学习率参数。"""

    optimizer: YoloOptimizer = "auto"
    learning_rate: float | None = Field(
        default=None,
        ge=0.00001,
        le=1.0,
        multiple_of=0.00001,
        json_schema_extra={"x-ui-default": 0.01},
    )
    weight_decay: float = Field(default=5e-4, ge=0.0, le=1.0, multiple_of=0.0001)
    min_lr_ratio: float = Field(default=0.01, ge=0.0, le=1.0, multiple_of=0.0001)
    grad_clip_norm: float = Field(default=10.0, ge=0.1, le=10_000.0, multiple_of=0.1)

    @model_validator(mode="after")
    def validate_learning_rate(self) -> "YoloOptimizationParameters":
        """auto 优化器自行解析学习率，显式优化器必须给出学习率。"""

        if self.optimizer == "auto" and self.learning_rate is not None:
            raise ValueError("optimizer=auto 时不能指定 learning_rate")
        if self.optimizer != "auto" and self.learning_rate is None:
            raise ValueError("显式 optimizer 必须指定 learning_rate")
        return self


class YoloXOptimizationParameters(TrainingParameterGroup):
    """YOLOX reference 调度参数。"""

    warmup_epochs: int = Field(default=5, ge=0, le=10_000)
    no_aug_epochs: int = Field(default=15, ge=0, le=10_000)
    min_lr_ratio: float = Field(default=0.05, ge=0.0, le=1.0, multiple_of=0.0001)
    ema: bool = True


class RfdetrOptimizationParameters(TrainingParameterGroup):
    """RF-DETR 优化器和梯度累计参数。"""

    learning_rate: float = Field(
        default=1e-4, ge=0.000001, le=1.0, multiple_of=0.000001
    )
    weight_decay: float = Field(default=1e-4, ge=0.0, le=1.0, multiple_of=0.0001)
    lr_scheduler: Literal["step", "cosine"] = "step"
    min_lr_ratio: float = Field(default=0.01, ge=0.0, le=1.0, multiple_of=0.0001)
    grad_accum_steps: int = Field(default=4, ge=1, le=1024)

    def to_execution_options(self) -> dict[str, object]:
        """step 调度不发送无效的 cosine 最小学习率。"""

        options = self.model_dump(exclude_none=True)
        if self.lr_scheduler != "cosine":
            options.pop("min_lr_ratio", None)
        return options


class DetectionEvaluationParameters(TrainingParameterGroup):
    """detection 类验证后处理参数。"""

    confidence_threshold: float = Field(
        default=0.001, ge=0.0, le=1.0, multiple_of=0.001
    )
    nms_threshold: float = Field(default=0.7, ge=0.0, le=1.0, multiple_of=0.01)

    def to_execution_options(self) -> dict[str, object]:
        """映射为 runner 已固定的字段名。"""

        return {
            "evaluation_confidence_threshold": self.confidence_threshold,
            "evaluation_nms_threshold": self.nms_threshold,
        }


class EndToEndDetectionEvaluationParameters(TrainingParameterGroup):
    """YOLO26 end-to-end detection 验证参数。"""

    confidence_threshold: float = Field(
        default=0.001, ge=0.0, le=1.0, multiple_of=0.001
    )

    def to_execution_options(self) -> dict[str, object]:
        """只发送 end-to-end 后处理实际使用的置信度阈值。"""

        return {"evaluation_confidence_threshold": self.confidence_threshold}


class YoloXDetectionEvaluationParameters(DetectionEvaluationParameters):
    """YOLOX detection 验证参数。"""

    confidence_threshold: float = Field(default=0.01, ge=0.0, le=1.0, multiple_of=0.01)
    nms_threshold: float = Field(default=0.65, ge=0.0, le=1.0, multiple_of=0.01)


class ObbEvaluationParameters(DetectionEvaluationParameters):
    """OBB 验证参数。"""

    confidence_threshold: float = Field(default=0.01, ge=0.0, le=1.0, multiple_of=0.01)


class EndToEndObbEvaluationParameters(EndToEndDetectionEvaluationParameters):
    """YOLO26 end-to-end OBB 验证参数。"""

    confidence_threshold: float = Field(default=0.01, ge=0.0, le=1.0, multiple_of=0.01)


class YoloMatchingParameters(TrainingParameterGroup):
    """YOLO 主线正样本匹配参数。"""

    topk: int = Field(default=10, ge=1, le=1000)
    alpha: float = Field(default=0.5, ge=0.0, le=100.0, multiple_of=0.1)
    beta: float = Field(default=6.0, ge=0.0, le=100.0, multiple_of=0.1)

    def to_execution_options(self) -> dict[str, object]:
        """映射为 runner 匹配字段。"""

        return {
            "assign_topk": self.topk,
            "assign_alpha": self.alpha,
            "assign_beta": self.beta,
        }


class RfdetrMatchingParameters(TrainingParameterGroup):
    """RF-DETR Hungarian matching 参数。"""

    class_cost: float = Field(default=2.0, ge=0.0, le=1000.0, multiple_of=0.1)
    bbox_cost: float = Field(default=5.0, ge=0.0, le=1000.0, multiple_of=0.1)
    giou_cost: float = Field(default=2.0, ge=0.0, le=1000.0, multiple_of=0.1)


class YoloDetectionLossParameters(TrainingParameterGroup):
    """YOLO detection 损失权重。"""

    class_weight: float = Field(default=0.5, ge=0.0, le=1000.0, multiple_of=0.1)
    box_weight: float = Field(default=7.5, ge=0.0, le=1000.0, multiple_of=0.1)
    dfl_weight: float = Field(default=1.5, ge=0.0, le=1000.0, multiple_of=0.1)

    def to_execution_options(self) -> dict[str, object]:
        """映射为 runner 损失字段。"""

        return {
            "class_loss_weight": self.class_weight,
            "box_loss_weight": self.box_weight,
            "dfl_loss_weight": self.dfl_weight,
        }


class Yolo26DetectionLossParameters(TrainingParameterGroup):
    """YOLO26 reg_max=1 detection 损失权重。"""

    class_weight: float = Field(default=0.5, ge=0.0, le=1000.0, multiple_of=0.1)
    box_weight: float = Field(default=7.5, ge=0.0, le=1000.0, multiple_of=0.1)
    l1_weight: float = Field(default=1.5, ge=0.0, le=1000.0, multiple_of=0.1)

    def to_execution_options(self) -> dict[str, object]:
        """映射为 YOLO26 Smooth L1 回归 gain 字段。"""

        return {
            "class_loss_weight": self.class_weight,
            "box_loss_weight": self.box_weight,
            "l1_loss_weight": self.l1_weight,
        }


class YoloSegmentationLossParameters(YoloDetectionLossParameters):
    """YOLO instance segmentation 损失权重。"""

    mask_weight: float = Field(default=7.5, ge=0.0, le=1000.0, multiple_of=0.1)

    def to_execution_options(self) -> dict[str, object]:
        """映射检测与 mask 损失字段。"""

        options = super().to_execution_options()
        options["mask_loss_weight"] = self.mask_weight
        return options


class Yolo26SegmentationLossParameters(Yolo26DetectionLossParameters):
    """YOLO26 instance segmentation 损失权重。"""

    mask_weight: float = Field(default=7.5, ge=0.0, le=1000.0, multiple_of=0.1)

    def to_execution_options(self) -> dict[str, object]:
        """映射 L1 回归与 mask 损失字段。"""

        options = super().to_execution_options()
        options["mask_loss_weight"] = self.mask_weight
        return options


class YoloPoseLossParameters(YoloDetectionLossParameters):
    """YOLO pose 损失权重。"""

    keypoint_weight: float = Field(default=12.0, ge=0.0, le=1000.0, multiple_of=0.1)

    def to_execution_options(self) -> dict[str, object]:
        """映射检测与关键点损失字段。"""

        options = super().to_execution_options()
        options["kpt_loss_weight"] = self.keypoint_weight
        return options


class Yolo26PoseLossParameters(Yolo26DetectionLossParameters):
    """YOLO26 pose 损失权重。"""

    keypoint_weight: float = Field(default=12.0, ge=0.0, le=1000.0, multiple_of=0.1)

    def to_execution_options(self) -> dict[str, object]:
        """映射 L1 回归与关键点损失字段。"""

        options = super().to_execution_options()
        options["kpt_loss_weight"] = self.keypoint_weight
        return options


class RfdetrDetectionLossParameters(TrainingParameterGroup):
    """RF-DETR detection 损失权重。"""

    class_weight: float = Field(default=1.0, ge=0.0, le=1000.0, multiple_of=0.1)
    bbox_weight: float = Field(default=5.0, ge=0.0, le=1000.0, multiple_of=0.1)
    giou_weight: float = Field(default=2.0, ge=0.0, le=1000.0, multiple_of=0.1)

    def to_execution_options(self) -> dict[str, object]:
        """映射为 RF-DETR runner 字段。"""

        return {
            "class_loss_weight": self.class_weight,
            "bbox_loss_weight": self.bbox_weight,
            "giou_loss_weight": self.giou_weight,
        }


class RfdetrSegmentationLossParameters(RfdetrDetectionLossParameters):
    """RF-DETR segmentation 损失权重。"""

    mask_ce_weight: float = Field(default=5.0, ge=0.0, le=1000.0, multiple_of=0.1)
    mask_dice_weight: float = Field(default=5.0, ge=0.0, le=1000.0, multiple_of=0.1)

    def to_execution_options(self) -> dict[str, object]:
        """映射 detection 与 mask 损失字段。"""

        options = super().to_execution_options()
        options.update(
            {
                "mask_ce_weight": self.mask_ce_weight,
                "mask_dice_weight": self.mask_dice_weight,
            }
        )
        return options


class RfdetrEvaluationParameters(TrainingParameterGroup):
    """RF-DETR 验证资源参数。"""

    max_detections: int = Field(default=500, ge=100, le=10_000)

    def to_execution_options(self) -> dict[str, object]:
        """映射为 RF-DETR runner 字段。"""

        return {"evaluation_max_detections": self.max_detections}


class RfdetrAdvancedParameters(TrainingParameterGroup):
    """RF-DETR 模型行为参数。"""

    use_ema: bool = True
    multi_scale: bool = True
    expanded_scales: bool = True


class OrderedFloatRangeParameters(TrainingParameterGroup):
    """带顺序校验的浮点闭区间基类。"""

    minimum: float
    maximum: float

    @model_validator(mode="after")
    def validate_order(self) -> "OrderedFloatRangeParameters":
        """校验区间顺序。"""

        if self.minimum > self.maximum:
            raise ValueError("minimum 不能大于 maximum")
        return self

    @property
    def pair(self) -> tuple[float, float]:
        """返回执行层二元区间。"""

        return (self.minimum, self.maximum)


class PositiveScaleRangeParameters(OrderedFloatRangeParameters):
    """Mosaic、MixUp 使用的正缩放区间。"""

    minimum: float = Field(ge=0.01, le=10.0, multiple_of=0.01)
    maximum: float = Field(ge=0.01, le=10.0, multiple_of=0.01)


class CropScaleRangeParameters(OrderedFloatRangeParameters):
    """classification 随机裁剪面积比例区间。"""

    minimum: float = Field(ge=0.08, le=1.0, multiple_of=0.01)
    maximum: float = Field(ge=0.08, le=1.0, multiple_of=0.01)


class AffineScaleRangeParameters(OrderedFloatRangeParameters):
    """classification 仿射缩放区间。"""

    minimum: float = Field(ge=0.1, le=2.0, multiple_of=0.01)
    maximum: float = Field(ge=0.1, le=2.0, multiple_of=0.01)


class GammaRangeParameters(OrderedFloatRangeParameters):
    """classification Gamma 区间。"""

    minimum: float = Field(ge=0.1, le=5.0, multiple_of=0.01)
    maximum: float = Field(ge=0.1, le=5.0, multiple_of=0.01)


class YoloTaskAugmentationParameters(TrainingParameterGroup):
    """YOLO 主线 detection/segmentation/pose/OBB 增强参数。"""

    enabled: bool = True
    horizontal_flip_probability: float = Field(
        default=0.5, ge=0.0, le=1.0, multiple_of=0.01
    )
    hue_gain: float = Field(default=0.015, ge=0.0, le=0.5, multiple_of=0.001)
    saturation_gain: float = Field(default=0.7, ge=0.0, le=1.0, multiple_of=0.01)
    value_gain: float = Field(default=0.4, ge=0.0, le=1.0, multiple_of=0.01)
    mosaic_probability: float = Field(default=1.0, ge=0.0, le=1.0, multiple_of=0.01)
    mixup_probability: float = Field(default=0.0, ge=0.0, le=1.0, multiple_of=0.01)
    affine_probability: float = Field(default=1.0, ge=0.0, le=1.0, multiple_of=0.01)
    rotation_degrees: float = Field(default=0.0, ge=0.0, le=180.0, multiple_of=0.1)
    translation_ratio: float = Field(default=0.1, ge=0.0, le=1.0, multiple_of=0.01)
    scale_ratio: float = Field(default=0.5, ge=0.0, le=10.0, multiple_of=0.01)
    shear_degrees: float = Field(default=0.0, ge=0.0, le=180.0, multiple_of=0.1)
    perspective_ratio: float = Field(default=0.0, ge=0.0, le=1.0, multiple_of=0.0001)
    close_mosaic_epochs: int = Field(default=10, ge=0, le=10_000)
    multi_scale_ratio: float = Field(default=0.0, ge=0.0, le=0.9, multiple_of=0.01)
    multi_scale_stride: int = Field(default=32, ge=1, le=1024)

    def to_execution_options(self) -> dict[str, object]:
        """映射并在关闭增强时生成确定性配置。"""

        if not self.enabled:
            return {
                "disable_augmentation": True,
                "flip_prob": 0.0,
                "hsv_h": 0.0,
                "hsv_s": 0.0,
                "hsv_v": 0.0,
                "mosaic_prob": 0.0,
                "mixup_prob": 0.0,
                "affine_prob": 0.0,
                "degrees": 0.0,
                "translate": 0.0,
                "scale": 0.0,
                "shear": 0.0,
                "perspective": 0.0,
                "close_mosaic": 0,
                "multi_scale": 0.0,
                "multi_scale_stride": self.multi_scale_stride,
            }
        return {
            "disable_augmentation": False,
            "flip_prob": self.horizontal_flip_probability,
            "hsv_h": self.hue_gain,
            "hsv_s": self.saturation_gain,
            "hsv_v": self.value_gain,
            "mosaic_prob": self.mosaic_probability,
            "mixup_prob": self.mixup_probability,
            "affine_prob": self.affine_probability,
            "degrees": self.rotation_degrees,
            "translate": self.translation_ratio,
            "scale": self.scale_ratio,
            "shear": self.shear_degrees,
            "perspective": self.perspective_ratio,
            "close_mosaic": self.close_mosaic_epochs,
            "multi_scale": self.multi_scale_ratio,
            "multi_scale_stride": self.multi_scale_stride,
        }


class YoloXAugmentationParameters(TrainingParameterGroup):
    """YOLOX detection 增强参数。"""

    enabled: bool = True
    horizontal_flip_probability: float = Field(
        default=0.5, ge=0.0, le=1.0, multiple_of=0.01
    )
    hsv_probability: float = Field(default=1.0, ge=0.0, le=1.0, multiple_of=0.01)
    mosaic_probability: float = Field(default=1.0, ge=0.0, le=1.0, multiple_of=0.01)
    mixup_probability: float = Field(default=1.0, ge=0.0, le=1.0, multiple_of=0.01)
    mixup_enabled: bool = True
    rotation_degrees: float = Field(default=10.0, ge=0.0, le=180.0, multiple_of=0.1)
    translation_ratio: float = Field(default=0.1, ge=0.0, le=1.0, multiple_of=0.01)
    shear_degrees: float = Field(default=2.0, ge=0.0, le=180.0, multiple_of=0.1)
    mosaic_scale: PositiveScaleRangeParameters = Field(
        default_factory=lambda: PositiveScaleRangeParameters(minimum=0.1, maximum=2.0)
    )
    mixup_scale: PositiveScaleRangeParameters = Field(
        default_factory=lambda: PositiveScaleRangeParameters(minimum=0.5, maximum=1.5)
    )
    multiscale_range: int = Field(default=5, ge=0, le=64)

    def to_execution_options(self) -> dict[str, object]:
        """映射为 YOLOX runner 配置。"""

        if not self.enabled:
            return {
                "flip_prob": 0.0,
                "hsv_prob": 0.0,
                "mosaic_prob": 0.0,
                "mixup_prob": 0.0,
                "enable_mixup": False,
                "degrees": 0.0,
                "translate": 0.0,
                "shear": 0.0,
                "multiscale_range": 0,
            }
        return {
            "flip_prob": self.horizontal_flip_probability,
            "hsv_prob": self.hsv_probability,
            "mosaic_prob": self.mosaic_probability,
            "mixup_prob": self.mixup_probability,
            "enable_mixup": self.mixup_enabled,
            "degrees": self.rotation_degrees,
            "translate": self.translation_ratio,
            "shear": self.shear_degrees,
            "mosaic_scale": self.mosaic_scale.pair,
            "mixup_scale": self.mixup_scale.pair,
            "multiscale_range": self.multiscale_range,
        }


class ClassificationAugmentationParameters(TrainingParameterGroup):
    """YOLO classification 图像增强参数。"""

    enabled: bool = True
    horizontal_flip_probability: float = Field(
        default=0.5, ge=0.0, le=1.0, multiple_of=0.01
    )
    crop_mode: Literal["none", "random_resized_crop"] = "random_resized_crop"
    crop_scale: CropScaleRangeParameters = Field(
        default_factory=lambda: CropScaleRangeParameters(minimum=0.5, maximum=1.0)
    )
    auto_augment: Literal["none", "randaugment", "autoaugment", "augmix"] = (
        "randaugment"
    )
    rotation_degrees: float = Field(default=0.0, ge=0.0, le=180.0, multiple_of=0.1)
    translation_ratio: float = Field(default=0.0, ge=0.0, le=0.5, multiple_of=0.01)
    affine_scale: AffineScaleRangeParameters = Field(
        default_factory=lambda: AffineScaleRangeParameters(minimum=1.0, maximum=1.0)
    )
    brightness_gain: float = Field(default=0.0, ge=0.0, le=1.0, multiple_of=0.01)
    contrast_gain: float = Field(default=0.0, ge=0.0, le=1.0, multiple_of=0.01)
    gamma: GammaRangeParameters = Field(
        default_factory=lambda: GammaRangeParameters(minimum=1.0, maximum=1.0)
    )
    hue_gain: float = Field(default=0.0, ge=0.0, le=0.5, multiple_of=0.001)
    saturation_gain: float = Field(default=0.0, ge=0.0, le=1.0, multiple_of=0.01)
    value_gain: float = Field(default=0.0, ge=0.0, le=1.0, multiple_of=0.01)
    random_erasing_probability: float = Field(
        default=0.4, ge=0.0, le=1.0, multiple_of=0.01
    )

    @model_validator(mode="after")
    def validate_conditional_fields(self) -> "ClassificationAugmentationParameters":
        """禁止提交会被自动增强策略忽略的非中性手工增强参数。"""

        if self.auto_augment != "none":
            manual_values = (
                self.rotation_degrees,
                self.translation_ratio,
                self.brightness_gain,
                self.contrast_gain,
                self.hue_gain,
                self.saturation_gain,
                self.value_gain,
            )
            if any(value != 0.0 for value in manual_values):
                raise ValueError("启用 auto_augment 时不能同时配置手工颜色或仿射增强")
            if self.affine_scale.pair != (1.0, 1.0) or self.gamma.pair != (1.0, 1.0):
                raise ValueError(
                    "启用 auto_augment 时 affine_scale 和 gamma 必须保持 1"
                )
        return self

    def to_execution_options(self) -> dict[str, object]:
        """映射为 classification augmentation runner 配置。"""

        if not self.enabled:
            return {"disable_augmentation": True}
        return {
            "disable_augmentation": False,
            "flip_prob": self.horizontal_flip_probability,
            "crop_mode": self.crop_mode,
            "crop_scale_min": self.crop_scale.minimum,
            "crop_scale_max": self.crop_scale.maximum,
            "auto_augment": self.auto_augment,
            "rotation_degrees": self.rotation_degrees,
            "translate_ratio": self.translation_ratio,
            "scale_min": self.affine_scale.minimum,
            "scale_max": self.affine_scale.maximum,
            "brightness_gain": self.brightness_gain,
            "contrast_gain": self.contrast_gain,
            "gamma_min": self.gamma.minimum,
            "gamma_max": self.gamma.maximum,
            "hue_gain": self.hue_gain,
            "saturation_gain": self.saturation_gain,
            "value_gain": self.value_gain,
            "random_erasing_prob": self.random_erasing_probability,
        }


class RfdetrAugmentationParameters(TrainingParameterGroup):
    """RF-DETR 受控增强预设。"""

    enabled: bool = True
    preset: Literal["default", "conservative", "aggressive", "aerial", "industrial"] = (
        "default"
    )
    scale_jitter: bool = True
    backend: Literal["cpu", "auto", "gpu"] = "cpu"

    def to_execution_options(self) -> dict[str, object]:
        """映射为 RF-DETR runner 配置。"""

        return {
            "disable_augmentation": not self.enabled,
            "rfdetr_augmentation_preset": self.preset,
            "scale_jitter": self.scale_jitter,
            "augmentation_backend": self.backend,
        }


class YoloXDataParameters(TrainingParameterGroup):
    """YOLOX 样本标签资源上限。"""

    max_labels_per_image: int = Field(default=120, ge=1, le=10_000)

    def to_execution_options(self) -> dict[str, object]:
        """映射为 YOLOX runner 字段。"""

        return {"max_labels": self.max_labels_per_image}


class YoloXDetectionTrainingParameters(StrictTrainingParameters):
    """YOLOX detection 完整公开参数。"""

    runtime: YoloXRuntimeParameters = Field(default_factory=YoloXRuntimeParameters)
    data: YoloXDataParameters = Field(default_factory=YoloXDataParameters)
    optimization: YoloXOptimizationParameters = Field(
        default_factory=YoloXOptimizationParameters
    )
    evaluation: YoloXDetectionEvaluationParameters = Field(
        default_factory=YoloXDetectionEvaluationParameters
    )
    augmentation: YoloXAugmentationParameters = Field(
        default_factory=YoloXAugmentationParameters
    )


class YoloDetectionTrainingParameters(StrictTrainingParameters):
    """YOLOv8/YOLO11/YOLO26 detection 完整公开参数。"""

    runtime: YoloRuntimeParameters = Field(default_factory=YoloRuntimeParameters)
    optimization: YoloOptimizationParameters = Field(
        default_factory=YoloOptimizationParameters
    )
    loss: YoloDetectionLossParameters = Field(
        default_factory=YoloDetectionLossParameters
    )
    matching: YoloMatchingParameters = Field(default_factory=YoloMatchingParameters)
    evaluation: DetectionEvaluationParameters = Field(
        default_factory=DetectionEvaluationParameters
    )
    augmentation: YoloTaskAugmentationParameters = Field(
        default_factory=YoloTaskAugmentationParameters
    )


class Yolo26DetectionTrainingParameters(YoloDetectionTrainingParameters):
    """YOLO26 end-to-end detection 完整公开参数。"""

    loss: Yolo26DetectionLossParameters = Field(
        default_factory=Yolo26DetectionLossParameters
    )
    evaluation: EndToEndDetectionEvaluationParameters = Field(
        default_factory=EndToEndDetectionEvaluationParameters
    )


class RfdetrDetectionTrainingParameters(StrictTrainingParameters):
    """RF-DETR detection 完整公开参数。"""

    runtime: RfdetrRuntimeParameters = Field(default_factory=RfdetrRuntimeParameters)
    optimization: RfdetrOptimizationParameters = Field(
        default_factory=RfdetrOptimizationParameters
    )
    loss: RfdetrDetectionLossParameters = Field(
        default_factory=RfdetrDetectionLossParameters
    )
    matching: RfdetrMatchingParameters = Field(default_factory=RfdetrMatchingParameters)
    evaluation: RfdetrEvaluationParameters = Field(
        default_factory=RfdetrEvaluationParameters
    )
    augmentation: RfdetrAugmentationParameters = Field(
        default_factory=RfdetrAugmentationParameters
    )
    advanced: RfdetrAdvancedParameters = Field(default_factory=RfdetrAdvancedParameters)


class YoloClassificationTrainingParameters(StrictTrainingParameters):
    """YOLO classification 完整公开参数。"""

    runtime: YoloRuntimeParameters = Field(default_factory=YoloRuntimeParameters)
    optimization: YoloOptimizationParameters = Field(
        default_factory=YoloOptimizationParameters
    )
    augmentation: ClassificationAugmentationParameters = Field(
        default_factory=ClassificationAugmentationParameters
    )


class YoloSegmentationTrainingParameters(StrictTrainingParameters):
    """YOLO instance segmentation 完整公开参数。"""

    runtime: YoloRuntimeParameters = Field(default_factory=YoloRuntimeParameters)
    optimization: YoloOptimizationParameters = Field(
        default_factory=YoloOptimizationParameters
    )
    loss: YoloSegmentationLossParameters = Field(
        default_factory=YoloSegmentationLossParameters
    )
    matching: YoloMatchingParameters = Field(default_factory=YoloMatchingParameters)
    evaluation: DetectionEvaluationParameters = Field(
        default_factory=DetectionEvaluationParameters
    )
    augmentation: YoloTaskAugmentationParameters = Field(
        default_factory=YoloTaskAugmentationParameters
    )


class Yolo26SegmentationTrainingParameters(YoloSegmentationTrainingParameters):
    """YOLO26 end-to-end instance segmentation 完整公开参数。"""

    loss: Yolo26SegmentationLossParameters = Field(
        default_factory=Yolo26SegmentationLossParameters
    )
    evaluation: EndToEndDetectionEvaluationParameters = Field(
        default_factory=EndToEndDetectionEvaluationParameters
    )


class RfdetrSegmentationTrainingParameters(StrictTrainingParameters):
    """RF-DETR instance segmentation 完整公开参数。"""

    runtime: RfdetrRuntimeParameters = Field(default_factory=RfdetrRuntimeParameters)
    optimization: RfdetrOptimizationParameters = Field(
        default_factory=RfdetrOptimizationParameters
    )
    loss: RfdetrSegmentationLossParameters = Field(
        default_factory=RfdetrSegmentationLossParameters
    )
    matching: RfdetrMatchingParameters = Field(default_factory=RfdetrMatchingParameters)
    evaluation: RfdetrEvaluationParameters = Field(
        default_factory=RfdetrEvaluationParameters
    )
    augmentation: RfdetrAugmentationParameters = Field(
        default_factory=RfdetrAugmentationParameters
    )
    advanced: RfdetrAdvancedParameters = Field(default_factory=RfdetrAdvancedParameters)


class YoloPoseTrainingParameters(StrictTrainingParameters):
    """YOLO pose 完整公开参数。"""

    runtime: YoloRuntimeParameters = Field(default_factory=YoloRuntimeParameters)
    optimization: YoloOptimizationParameters = Field(
        default_factory=YoloOptimizationParameters
    )
    loss: YoloPoseLossParameters = Field(default_factory=YoloPoseLossParameters)
    matching: YoloMatchingParameters = Field(default_factory=YoloMatchingParameters)
    evaluation: DetectionEvaluationParameters = Field(
        default_factory=DetectionEvaluationParameters
    )
    augmentation: YoloTaskAugmentationParameters = Field(
        default_factory=YoloTaskAugmentationParameters
    )


class Yolo26PoseTrainingParameters(YoloPoseTrainingParameters):
    """YOLO26 end-to-end pose 完整公开参数。"""

    loss: Yolo26PoseLossParameters = Field(
        default_factory=Yolo26PoseLossParameters
    )
    evaluation: EndToEndDetectionEvaluationParameters = Field(
        default_factory=EndToEndDetectionEvaluationParameters
    )


class YoloObbTrainingParameters(StrictTrainingParameters):
    """YOLO OBB 完整公开参数。"""

    runtime: YoloRuntimeParameters = Field(default_factory=YoloRuntimeParameters)
    optimization: YoloOptimizationParameters = Field(
        default_factory=YoloOptimizationParameters
    )
    evaluation: ObbEvaluationParameters = Field(default_factory=ObbEvaluationParameters)
    augmentation: YoloTaskAugmentationParameters = Field(
        default_factory=YoloTaskAugmentationParameters
    )


class Yolo26ObbTrainingParameters(YoloObbTrainingParameters):
    """YOLO26 end-to-end OBB 完整公开参数。"""

    evaluation: EndToEndObbEvaluationParameters = Field(
        default_factory=EndToEndObbEvaluationParameters
    )


DetectionTrainingParameters: TypeAlias = (
    YoloXDetectionTrainingParameters
    | YoloDetectionTrainingParameters
    | RfdetrDetectionTrainingParameters
)
SegmentationTrainingParameters: TypeAlias = (
    YoloSegmentationTrainingParameters | RfdetrSegmentationTrainingParameters
)
PoseTrainingParameters: TypeAlias = YoloPoseTrainingParameters | Yolo26PoseTrainingParameters
ObbTrainingParameters: TypeAlias = YoloObbTrainingParameters | Yolo26ObbTrainingParameters


TRAINING_PARAMETER_SCHEMA_BY_TASK_AND_MODEL: Final[
    dict[tuple[str, str], type[StrictTrainingParameters]]
] = {
    ("detection", "yolox"): YoloXDetectionTrainingParameters,
    ("detection", "yolov8"): YoloDetectionTrainingParameters,
    ("detection", "yolo11"): YoloDetectionTrainingParameters,
    ("detection", "yolo26"): Yolo26DetectionTrainingParameters,
    ("detection", "rfdetr"): RfdetrDetectionTrainingParameters,
    ("classification", "yolov8"): YoloClassificationTrainingParameters,
    ("classification", "yolo11"): YoloClassificationTrainingParameters,
    ("classification", "yolo26"): YoloClassificationTrainingParameters,
    ("segmentation", "yolov8"): YoloSegmentationTrainingParameters,
    ("segmentation", "yolo11"): YoloSegmentationTrainingParameters,
    ("segmentation", "yolo26"): Yolo26SegmentationTrainingParameters,
    ("segmentation", "rfdetr"): RfdetrSegmentationTrainingParameters,
    ("pose", "yolov8"): YoloPoseTrainingParameters,
    ("pose", "yolo11"): YoloPoseTrainingParameters,
    ("pose", "yolo26"): Yolo26PoseTrainingParameters,
    ("obb", "yolov8"): YoloObbTrainingParameters,
    ("obb", "yolo11"): YoloObbTrainingParameters,
    ("obb", "yolo26"): Yolo26ObbTrainingParameters,
}


def get_training_parameter_schema(
    *, task_type: str, model_type: str
) -> type[StrictTrainingParameters]:
    """读取已登记的任务/模型训练参数 schema。"""

    key = (str(task_type).strip().lower(), str(model_type).strip().lower())
    schema = TRAINING_PARAMETER_SCHEMA_BY_TASK_AND_MODEL.get(key)
    if schema is None:
        raise ValueError("指定 task_type/model_type 没有训练参数协议")
    return schema


def build_detection_training_parameters(
    *, model_type: str, value: object | None
) -> DetectionTrainingParameters:
    """按 detection model_type 构造唯一参数 schema。"""

    schema = get_training_parameter_schema(task_type="detection", model_type=model_type)
    return schema.model_validate({} if value is None else value)


def build_segmentation_training_parameters(
    *, model_type: str, value: object | None
) -> SegmentationTrainingParameters:
    """按 segmentation model_type 构造唯一参数 schema。"""

    schema = get_training_parameter_schema(
        task_type="segmentation", model_type=model_type
    )
    return schema.model_validate({} if value is None else value)


def build_pose_training_parameters(
    *, model_type: str, value: object | None
) -> PoseTrainingParameters:
    """按 pose model_type 构造唯一参数 schema。"""

    schema = get_training_parameter_schema(task_type="pose", model_type=model_type)
    return schema.model_validate({} if value is None else value)


def build_obb_training_parameters(
    *, model_type: str, value: object | None
) -> ObbTrainingParameters:
    """按 OBB model_type 构造唯一参数 schema。"""

    schema = get_training_parameter_schema(task_type="obb", model_type=model_type)
    return schema.model_validate({} if value is None else value)


__all__ = [
    "DetectionTrainingParameters",
    "ObbTrainingParameters",
    "PoseTrainingParameters",
    "TRAINING_PARAMETER_SCHEMA_BY_TASK_AND_MODEL",
    "RfdetrDetectionTrainingParameters",
    "RfdetrSegmentationTrainingParameters",
    "SegmentationTrainingParameters",
    "YoloClassificationTrainingParameters",
    "Yolo26DetectionTrainingParameters",
    "Yolo26ObbTrainingParameters",
    "Yolo26PoseTrainingParameters",
    "Yolo26SegmentationTrainingParameters",
    "YoloDetectionTrainingParameters",
    "YoloObbTrainingParameters",
    "YoloPoseTrainingParameters",
    "YoloSegmentationTrainingParameters",
    "YoloXDetectionTrainingParameters",
    "build_detection_training_parameters",
    "build_obb_training_parameters",
    "build_pose_training_parameters",
    "build_segmentation_training_parameters",
    "get_training_parameter_schema",
]
