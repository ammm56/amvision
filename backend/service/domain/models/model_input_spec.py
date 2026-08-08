"""模型输入尺寸、张量和预处理契约。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


TensorLayout = Literal["NCHW"]
InputPreprocessKind = Literal[
    "letterbox",
    "yolox-top-left-letterbox",
    "resize",
    "resize-center-crop",
]
InputNormalizationKind = Literal["none", "zero-to-one", "imagenet"]
InputInterpolationKind = Literal["bilinear"]

MAX_MODEL_INPUT_DIMENSION = 8192
MAX_MODEL_INPUT_PIXELS = 16_777_216


@dataclass(frozen=True)
class SpatialSize:
    """使用明确 width/height 字段描述二维空间尺寸。"""

    width: int
    height: int

    def __post_init__(self) -> None:
        """校验尺寸类型和有界像素规模。"""

        if (
            not isinstance(self.width, int)
            or isinstance(self.width, bool)
            or not isinstance(self.height, int)
            or isinstance(self.height, bool)
        ):
            raise ValueError("SpatialSize width 和 height 必须是整数")
        if self.width <= 0 or self.height <= 0:
            raise ValueError("SpatialSize width 和 height 必须大于 0")
        if (
            self.width > MAX_MODEL_INPUT_DIMENSION
            or self.height > MAX_MODEL_INPUT_DIMENSION
        ):
            raise ValueError(
                f"SpatialSize 单边不能超过 {MAX_MODEL_INPUT_DIMENSION} 像素"
            )
        if self.width * self.height > MAX_MODEL_INPUT_PIXELS:
            raise ValueError(f"SpatialSize 总像素不能超过 {MAX_MODEL_INPUT_PIXELS}")

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
    def from_payload(
        cls, value: object, *, field_name: str = "input_size"
    ) -> "SpatialSize":
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
    interpolation: InputInterpolationKind = "bilinear"
    padding_value: int | None = 114
    center: bool = True
    scaleup: bool = True
    auto: bool = False
    stride: int | None = 32
    postprocess_contract: str = "yolo-v1"
    preprocess_contract_version: int = 1
    postprocess_contract_version: int = 1
    contract_version: int = 2

    def __post_init__(self) -> None:
        """校验当前平台支持的固定契约字段。"""

        if self.layout != "NCHW":
            raise ValueError("当前模型输入只支持 NCHW layout")
        if self.dtype != "float32":
            raise ValueError("当前模型输入只支持 float32 dtype")
        if self.color_space != "RGB":
            raise ValueError("当前模型输入只支持 RGB color_space")
        if self.interpolation != "bilinear":
            raise ValueError("当前模型输入只支持 bilinear interpolation")
        if self.padding_value is not None and not 0 <= int(self.padding_value) <= 255:
            raise ValueError("padding_value 必须位于 0 到 255")
        if self.stride is not None and int(self.stride) <= 0:
            raise ValueError("stride 必须大于 0")
        if not self.postprocess_contract.strip():
            raise ValueError("postprocess_contract 不能为空")
        if int(self.preprocess_contract_version) != 1:
            raise ValueError("当前预处理契约只支持 version 1")
        if int(self.postprocess_contract_version) != 1:
            raise ValueError("当前后处理契约只支持 version 1")
        if int(self.contract_version) != 2:
            raise ValueError("当前模型输入契约只支持 version 2")
        self._validate_preprocess_semantics()

    def _validate_preprocess_semantics(self) -> None:
        """校验不同模型族预处理所需的固定语义。"""

        if self.preprocess in {"letterbox", "yolox-top-left-letterbox"}:
            if self.padding_value is None or self.stride is None:
                raise ValueError("LetterBox 输入契约必须声明 padding_value 和 stride")
            if self.preprocess == "yolox-top-left-letterbox" and self.center:
                raise ValueError("YOLOX LetterBox 必须使用左上角对齐")
            return
        if self.padding_value is not None or self.stride is not None or self.auto:
            raise ValueError("resize 输入契约不得声明 padding 或 stride/auto")
        if self.preprocess == "resize" and self.center:
            raise ValueError("固定 resize 输入契约不得声明 center")

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
            "interpolation": self.interpolation,
            "padding_value": self.padding_value,
            "center": bool(self.center),
            "scaleup": bool(self.scaleup),
            "auto": bool(self.auto),
            "stride": self.stride,
            "postprocess_contract": self.postprocess_contract,
            "preprocess_contract_version": int(self.preprocess_contract_version),
            "postprocess_contract_version": int(self.postprocess_contract_version),
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
                {
                    "letterbox",
                    "yolox-top-left-letterbox",
                    "resize",
                    "resize-center-crop",
                },
                field_name,
            ),
            normalization=_require_literal(
                value,
                "normalization",
                {"none", "zero-to-one", "imagenet"},
                field_name,
            ),
            interpolation=_require_literal(
                value,
                "interpolation",
                {"bilinear"},
                field_name,
            ),
            padding_value=_require_optional_int(value, "padding_value", field_name),
            center=_require_bool(value, "center", field_name),
            scaleup=_require_bool(value, "scaleup", field_name),
            auto=_require_bool(value, "auto", field_name),
            stride=_require_optional_int(value, "stride", field_name),
            postprocess_contract=_require_string(
                value,
                "postprocess_contract",
                field_name,
            ),
            preprocess_contract_version=_require_int(
                value,
                "preprocess_contract_version",
                field_name,
            ),
            postprocess_contract_version=_require_int(
                value,
                "postprocess_contract_version",
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
        padding_value=None if is_classification else 114,
        center=True,
        scaleup=True,
        auto=False,
        stride=None if is_classification else 32,
        postprocess_contract=(
            "yolo-classification-v1"
            if is_classification
            else f"yolo-{normalized_task}-v1"
        ),
    )


def build_platform_model_input_spec(
    *,
    model_type: str,
    spatial_size: SpatialSize,
    task_type: str,
) -> ModelInputSpec:
    """按平台模型族和任务构造唯一输入、预处理与后处理契约。"""

    normalized_model_type = model_type.strip().lower()
    if normalized_model_type in {"yolov8", "yolo11", "yolo26"}:
        return build_yolo_model_input_spec(
            spatial_size=spatial_size,
            task_type=task_type,
        )
    if normalized_model_type == "yolox":
        return ModelInputSpec(
            spatial_size=spatial_size,
            preprocess="yolox-top-left-letterbox",
            normalization="none",
            padding_value=114,
            center=False,
            scaleup=True,
            auto=False,
            stride=32,
            postprocess_contract="yolox-detection-v1",
        )
    if normalized_model_type == "rfdetr":
        return ModelInputSpec(
            spatial_size=spatial_size,
            preprocess="resize",
            normalization="imagenet",
            padding_value=None,
            center=False,
            scaleup=True,
            auto=False,
            stride=None,
            postprocess_contract=f"rfdetr-{task_type.strip().lower()}-v1",
        )
    raise ValueError(f"不支持构造输入契约的 model_type: {model_type}")


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


def _require_optional_int(
    payload: dict[str, Any],
    key: str,
    field_name: str,
) -> int | None:
    """读取可选整数。"""

    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{field_name}.{key} 必须是整数或 null")
    return int(value)


def _require_bool(payload: dict[str, Any], key: str, field_name: str) -> bool:
    """读取必填布尔值。"""

    value = payload.get(key)
    if not isinstance(value, bool):
        raise ValueError(f"{field_name}.{key} 必须是布尔值")
    return value


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
