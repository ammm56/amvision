"""训练任务公共执行策略请求模型。

该模块只描述跨模型共享的训练生命周期参数。模型 loss、matching、增强和
DataLoader 细节仍由按模型/任务拆分的 ``parameters`` schema 负责。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.service.api.rest.v1.routes.model_input_schemas import SpatialSizeRequest


class TrainingBatchPolicyRequest(BaseModel):
    """训练 batch 解析策略。"""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    mode: Literal["auto", "fixed"] = "auto"
    size: int | None = Field(default=None, ge=1, le=4096)
    target_memory_fraction: float = Field(
        default=0.6,
        ge=0.1,
        le=0.95,
        multiple_of=0.01,
    )
    minimum_size: int = Field(default=1, ge=1, le=4096)
    maximum_size: int | None = Field(default=None, ge=1, le=4096)
    recover_on_oom: bool = True
    max_oom_retries: int = Field(default=3, ge=0, le=10)

    @model_validator(mode="after")
    def validate_policy(self) -> "TrainingBatchPolicyRequest":
        """拒绝会被执行器静默忽略的 batch 参数组合。"""

        if self.mode == "fixed" and self.size is None:
            raise ValueError("batch.mode=fixed 时必须提供 batch.size")
        if self.mode == "auto" and self.size is not None:
            raise ValueError("batch.mode=auto 时不能提供 batch.size")
        if self.maximum_size is not None and self.maximum_size < self.minimum_size:
            raise ValueError("batch.maximum_size 不能小于 batch.minimum_size")
        if self.size is not None:
            if self.size < self.minimum_size:
                raise ValueError("batch.size 不能小于 batch.minimum_size")
            if self.maximum_size is not None and self.size > self.maximum_size:
                raise ValueError("batch.size 不能大于 batch.maximum_size")
        return self


class TrainingAmpPolicyRequest(BaseModel):
    """训练 Automatic Mixed Precision 策略。"""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    mode: Literal["auto", "enabled", "disabled"] = "auto"
    dtype: Literal["auto", "fp16", "bf16"] = "auto"

    @model_validator(mode="after")
    def validate_policy(self) -> "TrainingAmpPolicyRequest":
        """关闭 AMP 时禁止提交没有执行含义的 dtype。"""

        if self.mode == "disabled" and self.dtype != "auto":
            raise ValueError("amp.mode=disabled 时 amp.dtype 必须为 auto")
        return self


class TrainingCheckpointPolicyRequest(BaseModel):
    """训练 checkpoint 周期与保留策略。"""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    interval_epochs: int = Field(default=5, ge=1, le=10_000)
    keep_periodic: int = Field(default=2, ge=1, le=100)


class TrainingValidationPolicyRequest(BaseModel):
    """训练期 validation 调度策略。"""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    interval_epochs: int = Field(default=5, ge=1, le=10_000)


class TrainingExecutionPolicyRequest(BaseModel):
    """所有训练任务共享的执行策略。"""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    max_epochs: int = Field(default=100, ge=1, le=10_000)
    input_size: SpatialSizeRequest | None = None
    batch: TrainingBatchPolicyRequest = Field(
        default_factory=TrainingBatchPolicyRequest
    )
    amp: TrainingAmpPolicyRequest = Field(default_factory=TrainingAmpPolicyRequest)
    checkpoint: TrainingCheckpointPolicyRequest = Field(
        default_factory=TrainingCheckpointPolicyRequest
    )
    validation: TrainingValidationPolicyRequest = Field(
        default_factory=TrainingValidationPolicyRequest
    )

    def to_execution_options(self) -> dict[str, object]:
        """展开为训练执行层使用的公共 option。"""

        return {
            "batch_mode": self.batch.mode,
            "batch_target_memory_fraction": self.batch.target_memory_fraction,
            "batch_minimum_size": self.batch.minimum_size,
            "batch_maximum_size": self.batch.maximum_size,
            "batch_recover_on_oom": self.batch.recover_on_oom,
            "batch_oom_max_retries": self.batch.max_oom_retries,
            "amp_mode": self.amp.mode,
            "amp_dtype": self.amp.dtype,
            "checkpoint_interval": self.checkpoint.interval_epochs,
            "checkpoint_keep_periodic": self.checkpoint.keep_periodic,
            "evaluation_interval": self.validation.interval_epochs,
        }

    @property
    def fixed_batch_size(self) -> int | None:
        """返回固定 batch；自动模式返回空值。"""

        return self.batch.size if self.batch.mode == "fixed" else None

    @property
    def requested_precision(self) -> str | None:
        """返回旧执行 DTO 暂时使用的 precision 提示。

        真正 dtype 由训练 worker 根据设备和 AMP 能力再次解析。这里不把 auto
        提前固化为 FP32，避免 API 层吞掉自动混合精度语义。
        """

        if self.amp.mode == "disabled":
            return "fp32"
        if self.amp.mode == "enabled" and self.amp.dtype == "fp16":
            return "fp16"
        if self.amp.mode == "enabled" and self.amp.dtype == "bf16":
            return "bf16"
        return None


def merge_training_execution_options(
    *,
    execution: TrainingExecutionPolicyRequest,
    model_options: dict[str, object],
) -> dict[str, object]:
    """合并公共执行参数和模型参数，并拒绝字段覆盖。"""

    execution_options = execution.to_execution_options()
    duplicates = execution_options.keys() & model_options.keys()
    if duplicates:
        raise ValueError(f"公共执行参数与模型参数重复: {sorted(duplicates)}")
    return {**model_options, **execution_options}


__all__ = [
    "TrainingAmpPolicyRequest",
    "TrainingBatchPolicyRequest",
    "TrainingCheckpointPolicyRequest",
    "TrainingExecutionPolicyRequest",
    "TrainingValidationPolicyRequest",
    "merge_training_execution_options",
]
