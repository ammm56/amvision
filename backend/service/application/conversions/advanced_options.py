"""解析转换适配器支持的导出选项。"""

from dataclasses import dataclass

from backend.service.application.errors import InvalidRequestError


YOLO_ONNX_OPSETS = (18, 19)


def resolve_conversion_onnx_opset(options: dict[str, object], *, supported: tuple[int, ...]) -> int | None:
    """验证可选 Opset，旧任务使用各适配器原默认值。"""
    value = options.get("onnx_opset_version")
    if value is None:
        return None
    if type(value) is not int or value not in supported:
        raise InvalidRequestError("当前转换适配器不支持指定 ONNX Opset", details={"supported": supported})
    return value


def uses_conversion_dynamic_batch(
    options: dict[str, object], *, model_type: str, task_type: str, targets: tuple[str, ...],
) -> bool:
    """只有经过双批次数值核对的 YOLO11 detection ONNX 可使用动态批次。"""
    if is_tensorrt_int8_request(options, model_type=model_type, task_type=task_type, targets=targets):
        return False
    if is_openvino_int8_request(options, model_type=model_type, task_type=task_type, targets=targets):
        return False
    if any(options.get(key) is not None for key in ("input_profile", "workspace_gib", "int8_calibration", "int8_validation")):
        raise InvalidRequestError("请选择支持校准的 INT8 转换目标")
    mode = options.get("input_shape_mode", "static")
    if mode is None or mode == "static":
        return False
    if mode == "dynamic-batch" and (model_type, task_type, targets) == ("yolo11", "detection", ("onnx",)):
        return True
    raise InvalidRequestError("当前模型与目标格式不支持所选输入模式")


@dataclass(frozen=True)
class Int8SampleOptions:
    """校准集和独立校验集的导出 ID 及样本数量。"""

    calibration_export_id: str
    calibration_count: int
    validation_export_id: str
    validation_count: int


@dataclass(frozen=True)
class TensorRtInt8Options(Int8SampleOptions):
    """动态 NCHW profile、显存预算及两组样本来源。"""

    shapes: tuple[tuple[int, int, int, int], ...]
    workspace_gib: int


def is_openvino_int8_request(
    options: dict[str, object], *, model_type: str, task_type: str, targets: tuple[str, ...],
) -> bool:
    """限定已接通的 OpenVINO 量化来源和固定输入。"""
    if str(options.get("openvino_ir_precision", "")).strip().lower() != "int8":
        return False
    if (model_type, task_type, targets) != ("yolo11", "detection", ("openvino-ir",)):
        raise InvalidRequestError("OpenVINO INT8 目前只支持 YOLO11 目标检测")
    if options.get("input_shape_mode", "static") != "static" or any(
        options.get(key) is not None for key in ("input_profile", "workspace_gib")
    ):
        raise InvalidRequestError("OpenVINO INT8 使用固定输入，不接受动态 profile 或 Workspace")
    return True


def is_tensorrt_int8_request(
    options: dict[str, object], *, model_type: str, task_type: str, targets: tuple[str, ...],
) -> bool:
    """限定动态 INT8 的已接通来源和目标，已有 FP32/FP16 保持原规则。"""
    precision = options.get("tensorrt_engine_precision")
    if not isinstance(precision, str) or precision.strip().lower() != "int8":
        return False
    if (model_type, task_type, targets) != ("yolo11", "detection", ("tensorrt-engine",)):
        raise InvalidRequestError("TensorRT INT8 目前只支持 YOLO11 目标检测")
    if options.get("input_shape_mode") != "dynamic":
        raise InvalidRequestError("TensorRT INT8 需要动态输入 profile")
    return True


def parse_tensorrt_int8_options(options: dict[str, object]) -> TensorRtInt8Options:
    """解析固定批次校准所需的动态 profile 和样本参数。"""
    profile = options.get("input_profile")
    if not isinstance(profile, dict) or set(profile) != {"min", "opt", "max"}:
        raise InvalidRequestError("请填写 min、opt、max 三组 NCHW 输入形状")
    shapes = []
    for key in ("min", "opt", "max"):
        shape = profile[key]
        if (
            not isinstance(shape, list) or len(shape) != 4 or any(type(item) is not int for item in shape)
            or not 1 <= shape[0] <= 4 or shape[1] != 3
            or any(not 64 <= size <= 1280 or size % 32 for size in shape[2:])
        ):
            raise InvalidRequestError("N 需为 1–4，C 为 3，H 和 W 需为 64–1280 内的 32 倍数")
        shapes.append(tuple(shape))
    low, nominal, high = shapes
    if any(not a <= b <= c for a, b, c in zip(low, nominal, high, strict=True)):
        raise InvalidRequestError("输入形状的每个维度必须满足 min ≤ opt ≤ max")
    if nominal[0] != 1 or low[2:] == high[2:]:
        raise InvalidRequestError("INT8 校准的 opt 批次必须为 1，H 或 W 至少一项必须具有范围")
    workspace = options.get("workspace_gib", 4)
    if type(workspace) is not int or not 1 <= workspace <= 8:
        raise InvalidRequestError("workspace 上限必须是 1–8 GB 的整数")
    return TensorRtInt8Options(*_int8_samples(options), tuple(shapes), workspace)


def parse_openvino_int8_options(options: dict[str, object]) -> Int8SampleOptions:
    """解析 OpenVINO INT8 的两组公开样本请求。"""
    return Int8SampleOptions(*_int8_samples(options))


def _int8_samples(options: dict[str, object]) -> tuple[str, int, str, int]:
    """读取两个后端共用的样本选项。"""
    calibration = _read_export_sample_request(options.get("int8_calibration"), "校准", 200)
    validation = _read_export_sample_request(options.get("int8_validation"), "校验", 100)
    return (*calibration, *validation)


def _read_export_sample_request(value: object, label: str, limit: int) -> tuple[str, int]:
    """读取公开的数据导出 ID 和样本数，不接受磁盘路径。"""
    if not isinstance(value, dict) or set(value) != {"dataset_export_id", "sample_count"}:
        raise InvalidRequestError(f"请选择{label}数据并填写样本数量")
    export_id, count = value["dataset_export_id"], value["sample_count"]
    if not isinstance(export_id, str) or not export_id.strip():
        raise InvalidRequestError(f"请选择{label}数据集导出")
    if type(count) is not int or not 1 <= count <= limit:
        raise InvalidRequestError(f"{label}样本数量必须在 1–{limit} 范围内")
    return export_id.strip(), count
