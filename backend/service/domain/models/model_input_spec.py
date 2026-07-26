"""模型输入尺寸、张量和预处理契约。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


TensorLayout = Literal["NCHW"]
InputPreprocessKind = Literal["letterbox", "resize-center-crop"]
InputNormalizationKind = Literal["zero-to-one", "imagenet"]


@dataclass(frozen=True)
class SpatialSize:
    """使用明确 width/height 字段描述二维空间尺寸。"""

    width: int
    height: int

    def __post_init__(self) -> None:
        """校验尺寸必须为正整数。"""

        if int(self.width) <= 0 or int(self.height) <= 0:
            raise ValueError("SpatialSize width 和 height 必须大于 0")

    @property
    def hw(self) -> tuple[int, int]:
        """返回张量和模型 core 使用的 ``(height, width)``。"""

        return (int(self.height), int(self.width))

    @property
    def wh(self) -> tuple[int, int]:
        """返回 OpenCV 使用的 ``(width, height)``。"""

        return (int(self.width), int(self.height))

    def to_payload(self) -> dict[str, int]:
        """序列化为不存在顺序歧义的公开对象。"""

        return {"width": int(self.width), "height": int(self.height)}

    @classmethod
    def from_payload(cls, value: object, *, field_name: str = "input_size") -> "SpatialSize":
        """从明确的 width/height 对象解析尺寸。

        断代升级后不接受二元素数组或 tuple，避免重新引入尺寸顺序猜测。
        """

        if not isinstance(value, dict):
            raise ValueError(f"{field_name} 必须是包含 width 和 height 的对象")
        width = value.get("width")
        height = value.get("height")
        if (
            not isinstance(width, int)
            or isinstance(width, bool)
            or not isinstance(height, int)
            or isinstance(height, bool)
        ):
            raise ValueError(f"{field_name}.width 和 {field_name}.height 必须是整数")
        return cls(width=width, height=height)


@dataclass(frozen=True)
class ModelInputSpec:
    """描述 ModelVersion 与 ModelBuild 共享的完整输入契约。"""

    spatial_size: SpatialSize
    layout: TensorLayout = "NCHW"
    dtype: str = "float32"
    color_space: str = "RGB"
    preprocess: InputPreprocessKind = "letterbox"
    normalization: InputNormalizationKind = "zero-to-one"
    contract_version: int = 1

    def __post_init__(self) -> None:
        """校验当前平台支持的固定契约字段。"""

        if self.layout != "NCHW":
            raise ValueError("当前模型输入只支持 NCHW layout")
        if self.dtype != "float32":
            raise ValueError("当前模型输入只支持 float32 dtype")
        if self.color_space != "RGB":
            raise ValueError("当前模型输入只支持 RGB color_space")
        if int(self.contract_version) != 1:
            raise ValueError("当前模型输入契约只支持 version 1")

    @property
    def tensor_shape(self) -> tuple[int, int, int, int]:
        """返回 batch=1 的 NCHW 输入形状。"""

        height, width = self.spatial_size.hw
        return (1, 3, height, width)

    def to_payload(self) -> dict[str, object]:
        """序列化为 ModelVersion/ModelBuild 可持久化结构。"""

        return {
            "contract_version": int(self.contract_version),
            "spatial_size": self.spatial_size.to_payload(),
            "tensor_layout": self.layout,
            "tensor_shape": list(self.tensor_shape),
            "dtype": self.dtype,
            "color_space": self.color_space,
            "preprocess": self.preprocess,
            "normalization": self.normalization,
        }

    @classmethod
    def from_payload(
        cls,
        value: object,
        *,
        field_name: str = "model_input_spec",
    ) -> "ModelInputSpec":
        """从持久化对象解析完整模型输入契约。"""

        if not isinstance(value, dict):
            raise ValueError(f"{field_name} 必须是对象")
        resolved = cls(
            spatial_size=SpatialSize.from_payload(
                value.get("spatial_size"),
                field_name=f"{field_name}.spatial_size",
            ),
            layout=_require_literal(value, "tensor_layout", {"NCHW"}, field_name),
            dtype=_require_string(value, "dtype", field_name),
            color_space=_require_string(value, "color_space", field_name),
            preprocess=_require_literal(
                value,
                "preprocess",
                {"letterbox", "resize-center-crop"},
                field_name,
            ),
            normalization=_require_literal(
                value,
                "normalization",
                {"zero-to-one", "imagenet"},
                field_name,
            ),
            contract_version=_require_int(value, "contract_version", field_name),
        )
        tensor_shape = value.get("tensor_shape")
        if (
            not isinstance(tensor_shape, list)
            or any(
                not isinstance(item, int) or isinstance(item, bool)
                for item in tensor_shape
            )
            or tuple(tensor_shape) != resolved.tensor_shape
        ):
            raise ValueError(
                f"{field_name}.tensor_shape 必须与 spatial_size 对应的 NCHW 形状一致"
            )
        return resolved


def build_yolo_model_input_spec(
    *,
    spatial_size: SpatialSize,
    task_type: str,
) -> ModelInputSpec:
    """按 YOLO task 构造运行时输入规格。"""

    normalized_task = task_type.strip().lower()
    is_classification = normalized_task == "classification"
    return ModelInputSpec(
        spatial_size=spatial_size,
        preprocess="resize-center-crop" if is_classification else "letterbox",
        normalization="imagenet" if is_classification else "zero-to-one",
    )


def resolve_yolo_default_spatial_size(*, task_type: str) -> SpatialSize:
    """返回 YOLO 主线 task 的平台默认输入尺寸。"""

    if task_type.strip().lower() == "classification":
        return SpatialSize(width=224, height=224)
    return SpatialSize(width=640, height=640)


def serialize_spatial_size_hw(
    value: tuple[int, int] | None,
) -> dict[str, int] | None:
    """把内部 ``(height, width)`` 转为明确的公开尺寸对象。"""

    if value is None:
        return None
    return SpatialSize(width=int(value[1]), height=int(value[0])).to_payload()


def deserialize_spatial_size_hw(
    value: object,
    *,
    field_name: str = "input_size",
) -> tuple[int, int] | None:
    """把可选公开尺寸对象转为内部 ``(height, width)``。"""

    if value is None:
        return None
    return SpatialSize.from_payload(value, field_name=field_name).hw


def _require_string(payload: dict[str, Any], key: str, field_name: str) -> str:
    """读取必填非空字符串。"""

    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name}.{key} 必须是非空字符串")
    return value.strip()


def _require_int(payload: dict[str, Any], key: str, field_name: str) -> int:
    """读取必填整数。"""

    value = payload.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{field_name}.{key} 必须是整数")
    return int(value)


def _require_literal(
    payload: dict[str, Any],
    key: str,
    allowed: set[str],
    field_name: str,
) -> Any:
    """读取并校验字符串枚举。"""

    value = _require_string(payload, key, field_name)
    if value not in allowed:
        raise ValueError(f"{field_name}.{key} 不受支持: {value}")
    return value
