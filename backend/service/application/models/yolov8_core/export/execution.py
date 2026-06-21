"""YOLOv8 导出执行边界。"""

from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path, PurePosixPath
import subprocess
from typing import Callable

from backend.service.application.errors import ServiceConfigurationError
from backend.service.application.models.export.onnx_export import export_torch_model_to_onnx
from backend.service.application.models.yolov8_core.export.plan import YoloV8ExportTaskPlan
from backend.service.application.models.yolov8_core.export.segmentation import (
    normalize_yolov8_segmentation_export_outputs,
)

YOLOV8_OPENVINO_IR_BUILD_SCRIPT_FILE = "build_openvino_ir.py"
YOLOV8_TENSORRT_ENGINE_BUILD_SCRIPT_FILE = "build_tensorrt_engine.py"

ConversionScriptRunner = Callable[..., subprocess.CompletedProcess[str]]


def export_yolov8_onnx_model(
    *,
    session: object,
    output_path: Path,
    output_object_key: str,
    export_plan: YoloV8ExportTaskPlan,
) -> dict[str, object]:
    """按 YOLOv8 export plan 把 PyTorch 模型导出为 ONNX。"""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    dummy_input = _build_yolov8_dummy_input(session=session)
    with session.imports.torch.no_grad():
        with use_yolov8_model_export_mode(
            session.model,
            enabled=export_plan.export_mode_enabled,
        ):
            export_torch_model_to_onnx(
                torch_module=session.imports.torch,
                model=session.model,
                model_args=(dummy_input,),
                output_path=output_path,
                opset_version=export_plan.onnx_opset_version,
                input_names=export_plan.input_names,
                output_names=export_plan.output_names,
            )
    return {
        "stage": "export-onnx",
        "object_uri": output_object_key,
        "opset_version": export_plan.onnx_opset_version,
        "input_size": list(session.runtime_target.input_size),
        "exporter_mode": export_plan.exporter_mode,
        "input_names": list(export_plan.input_names),
        "output_names": list(export_plan.output_names),
        "task_type": session.runtime_target.task_type,
    }


def validate_yolov8_onnx_model(
    *,
    session: object,
    onnx_path: Path,
    onnx_module: object,
    onnxruntime_module: object,
    export_plan: YoloV8ExportTaskPlan,
) -> dict[str, object]:
    """校验 YOLOv8 ONNX 文件合法性并和 PyTorch 输出做数值对比。"""

    onnx_model = onnx_module.load(str(onnx_path))
    onnx_module.checker.check_model(onnx_model)

    dummy_input = _build_yolov8_dummy_input(session=session)
    with session.imports.torch.no_grad():
        with use_yolov8_model_export_mode(
            session.model,
            enabled=export_plan.export_mode_enabled,
        ):
            torch_outputs = normalize_yolov8_export_model_outputs(
                session.model(dummy_input),
                session.imports,
            )
    _validate_yolov8_task_export_outputs(
        task_type=export_plan.task_type,
        outputs=torch_outputs,
    )
    ort_session = onnxruntime_module.InferenceSession(
        str(onnx_path),
        providers=["CPUExecutionProvider"],
    )
    ort_outputs = ort_session.run(
        list(export_plan.output_names),
        {ort_session.get_inputs()[0].name: dummy_input.detach().cpu().numpy()},
    )
    _validate_yolov8_task_export_outputs(
        task_type=export_plan.task_type,
        outputs=ort_outputs,
    )
    summary = summarize_yolov8_onnx_numeric_validation(
        np_module=session.imports.np,
        torch_outputs=torch_outputs,
        ort_outputs=ort_outputs,
    )
    if not bool(summary["allclose"]):
        raise ServiceConfigurationError(
            "YOLOv8 ONNX 数值校验失败",
            details=dict(summary),
        )
    return summary


def build_yolov8_openvino_ir_model(
    *,
    source_path: Path,
    output_path: Path,
    source_object_key: str,
    output_object_key: str,
    build_precision: str,
    run_conversion_script: ConversionScriptRunner,
) -> dict[str, object]:
    """把 YOLOv8 optimized ONNX 转换为 OpenVINO IR 并返回构建摘要。"""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    compress_to_fp16 = build_precision == "fp16"
    completed_process = run_conversion_script(
        script_file_name=YOLOV8_OPENVINO_IR_BUILD_SCRIPT_FILE,
        args=[str(source_path), str(output_path), build_precision],
    )
    if completed_process.returncode != 0:
        raise ServiceConfigurationError(
            "YOLOv8 OpenVINO IR 构建失败",
            details={
                "source_object_uri": source_object_key,
                "output_object_uri": output_object_key,
                "stdout": completed_process.stdout.strip(),
                "stderr": completed_process.stderr.strip(),
            },
        )

    weights_path = output_path.with_suffix(".bin")
    if not output_path.is_file() or not weights_path.is_file():
        raise ServiceConfigurationError(
            "YOLOv8 OpenVINO IR 构建未生成完整的 xml/bin 产物",
            details={
                "output_object_uri": output_object_key,
                "weights_object_uri": resolve_yolov8_openvino_weights_object_key(
                    output_object_key
                ),
            },
        )
    return {
        "stage": "build-openvino-ir",
        "object_uri": output_object_key,
        "source_object_uri": source_object_key,
        "weights_object_uri": resolve_yolov8_openvino_weights_object_key(output_object_key),
        "build_precision": build_precision,
        "compress_to_fp16": compress_to_fp16,
        "execution_mode": "subprocess-openvino-convert-model",
    }


def build_yolov8_tensorrt_engine_model(
    *,
    source_path: Path,
    output_path: Path,
    source_object_key: str,
    output_object_key: str,
    build_precision: str,
    run_conversion_script: ConversionScriptRunner,
) -> dict[str, object]:
    """把 YOLOv8 optimized ONNX 转换为 TensorRT engine 并返回构建摘要。"""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    completed_process = run_conversion_script(
        script_file_name=YOLOV8_TENSORRT_ENGINE_BUILD_SCRIPT_FILE,
        args=[str(source_path), str(output_path), build_precision],
    )
    if completed_process.returncode != 0:
        raise ServiceConfigurationError(
            "YOLOv8 TensorRT engine 构建失败",
            details={
                "source_object_uri": source_object_key,
                "output_object_uri": output_object_key,
                "stdout": completed_process.stdout.strip(),
                "stderr": completed_process.stderr.strip(),
            },
        )
    if not output_path.is_file():
        raise ServiceConfigurationError(
            "YOLOv8 TensorRT engine 构建未生成 engine 产物",
            details={"output_object_uri": output_object_key},
        )
    build_summary = {
        "stage": "build-tensorrt-engine",
        "object_uri": output_object_key,
        "source_object_uri": source_object_key,
        "build_precision": build_precision,
        "execution_mode": "subprocess-tensorrt-build-engine",
        "engine_file_bytes": output_path.stat().st_size,
    }
    stdout_payload = _parse_yolov8_last_json_line(completed_process.stdout)
    if stdout_payload is not None:
        build_summary.update(dict(stdout_payload))
    return build_summary


def normalize_yolov8_export_model_outputs(model_outputs: object, imports: object) -> list[object]:
    """把 YOLOv8 PyTorch 模型输出规整为 numpy 数组列表。"""

    if hasattr(model_outputs, "detach"):
        return [model_outputs.detach().cpu().numpy()]
    if isinstance(model_outputs, (list, tuple)):
        normalized_outputs: list[object] = []
        for item in model_outputs:
            if hasattr(item, "detach"):
                normalized_outputs.append(item.detach().cpu().numpy())
        if normalized_outputs:
            return normalized_outputs
    raise ServiceConfigurationError(
        "当前 YOLOv8 模型输出格式不受支持",
        details={"output_type": model_outputs.__class__.__name__},
    )


def summarize_yolov8_onnx_numeric_validation(
    *,
    np_module: object,
    torch_outputs: list[object],
    ort_outputs: list[object],
) -> dict[str, object]:
    """计算 YOLOv8 PyTorch 与 ONNX 输出的数值差异摘要。"""

    if len(torch_outputs) != len(ort_outputs):
        raise ServiceConfigurationError(
            "YOLOv8 ONNX 输出数量与 PyTorch 不一致",
            details={
                "torch_output_count": len(torch_outputs),
                "ort_output_count": len(ort_outputs),
            },
        )
    max_abs_diff = 0.0
    mean_abs_diff = 0.0
    compared_output_count = 0
    for torch_output, ort_output in zip(torch_outputs, ort_outputs, strict=True):
        if tuple(torch_output.shape) != tuple(ort_output.shape):
            raise ServiceConfigurationError(
                "YOLOv8 ONNX 输出形状与 PyTorch 不一致",
                details={
                    "torch_shape": list(torch_output.shape),
                    "ort_shape": list(ort_output.shape),
                },
            )
        abs_diff = np_module.abs(torch_output - ort_output)
        max_abs_diff = max(max_abs_diff, float(np_module.max(abs_diff)))
        mean_abs_diff += float(np_module.mean(abs_diff))
        compared_output_count += 1
    mean_abs_diff = mean_abs_diff / max(1, compared_output_count)
    allclose = all(
        bool(np_module.allclose(torch_output, ort_output, rtol=1e-3, atol=1e-4))
        for torch_output, ort_output in zip(torch_outputs, ort_outputs, strict=True)
    )
    return {
        "stage": "validate-onnx",
        "allclose": allclose,
        "max_abs_diff": max_abs_diff,
        "mean_abs_diff": mean_abs_diff,
        "output_count": compared_output_count,
    }


def resolve_yolov8_openvino_weights_object_key(output_object_key: str) -> str:
    """根据 YOLOv8 OpenVINO XML object key 推导同名 bin object key。"""

    return PurePosixPath(output_object_key).with_suffix(".bin").as_posix()


@contextmanager
def use_yolov8_model_export_mode(model: object, *, enabled: bool):
    """临时切换 YOLOv8 模型内部 export 标志，保证导出和校验输出语义一致。"""

    if not enabled:
        yield
        return
    toggled_modules: list[tuple[object, bool]] = []
    modules = getattr(model, "modules", None)
    if callable(modules):
        for module in modules():
            export_flag = getattr(module, "export", None)
            if isinstance(export_flag, bool):
                toggled_modules.append((module, export_flag))
                setattr(module, "export", True)
    try:
        yield
    finally:
        for module, original_value in toggled_modules:
            setattr(module, "export", original_value)


def _build_yolov8_dummy_input(*, session: object) -> object:
    """按 runtime target 的输入尺寸生成 YOLOv8 导出和校验使用的 dummy input。"""

    return session.imports.torch.randn(
        1,
        3,
        session.runtime_target.input_size[0],
        session.runtime_target.input_size[1],
        device=session.device_name,
        dtype=session.imports.torch.float32,
    )


def _validate_yolov8_task_export_outputs(*, task_type: str, outputs: list[object]) -> None:
    """按 task_type 校验 YOLOv8 导出输出数量和语义。"""

    if task_type == "segmentation":
        normalize_yolov8_segmentation_export_outputs(outputs=outputs)


def _parse_yolov8_last_json_line(stdout: str) -> dict[str, object] | None:
    """从标准输出最后一个非空行解析 JSON 对象。"""

    stdout_lines = [line.strip() for line in stdout.splitlines() if line.strip()]
    if not stdout_lines:
        return None
    try:
        payload = json.loads(stdout_lines[-1])
    except json.JSONDecodeError:
        return None
    if isinstance(payload, dict):
        return {str(key): value for key, value in payload.items()}
    return None


__all__ = [
    "ConversionScriptRunner",
    "build_yolov8_openvino_ir_model",
    "build_yolov8_tensorrt_engine_model",
    "export_yolov8_onnx_model",
    "normalize_yolov8_export_model_outputs",
    "resolve_yolov8_openvino_weights_object_key",
    "summarize_yolov8_onnx_numeric_validation",
    "use_yolov8_model_export_mode",
    "validate_yolov8_onnx_model",
]
