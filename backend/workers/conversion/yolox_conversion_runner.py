"""YOLOX 转换 worker 接口与 ONNX/OpenVINO 实现。"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
import sys
from typing import Protocol

from backend.service.application.conversions.yolox_conversion_planner import YoloXConversionStep
from backend.service.application.errors import InvalidRequestError, ServiceConfigurationError
from backend.service.application.runtime.yolox_predictor import PyTorchYoloXRuntimeSession
from backend.service.application.runtime.yolox_runtime_target import RuntimeTargetSnapshot
from backend.service.domain.files.yolox_file_types import (
    YOLOX_ONNX_FILE,
    YOLOX_ONNX_OPTIMIZED_FILE,
    YOLOX_OPENVINO_IR_FILE,
)
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


_OPENVINO_IR_PRECISION_OPTION_KEY = "openvino_ir_precision"
_SUPPORTED_OPENVINO_IR_BUILD_PRECISIONS = frozenset({"fp32", "fp16"})
_OPENVINO_IR_BUILD_SCRIPT = """
from pathlib import Path
import sys

from openvino import convert_model, save_model

source_path = Path(sys.argv[1]).resolve()
output_path = Path(sys.argv[2]).resolve()
build_precision = sys.argv[3].strip().lower()
if build_precision not in {"fp32", "fp16"}:
    raise ValueError(f"unsupported openvino_ir_precision: {build_precision}")
output_path.parent.mkdir(parents=True, exist_ok=True)
openvino_model = convert_model(str(source_path))
save_model(openvino_model, str(output_path), compress_to_fp16=(build_precision == "fp16"))
""".strip()


@dataclass(frozen=True)
class YoloXConversionRunRequest:
    """描述一次 YOLOX 转换执行请求。

    字段：
    - conversion_task_id：转换任务 id。
    - source_runtime_target：来源 ModelVersion 解析得到的 PyTorch runtime 快照。
    - target_formats：目标输出格式列表。
    - plan_steps：已经固化的转换步骤图谱。
    - output_object_prefix：输出目录前缀。
    - metadata：附加元数据。
    """

    conversion_task_id: str
    source_runtime_target: RuntimeTargetSnapshot
    target_formats: tuple[str, ...]
    plan_steps: tuple[YoloXConversionStep, ...]
    output_object_prefix: str
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class YoloXConversionOutput:
    """描述单个转换输出文件。

    字段：
    - target_format：目标格式。
    - object_uri：输出文件 URI。
    - file_type：登记到平台的 file type。
    - metadata：输出元数据摘要。
    """

    target_format: str
    object_uri: str
    file_type: str
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class YoloXConversionRunResult:
    """描述一次 YOLOX 转换执行结果。

    字段：
    - conversion_task_id：转换任务 id。
    - outputs：转换输出文件列表。
    - metadata：附加元数据。
    """

    conversion_task_id: str
    outputs: tuple[YoloXConversionOutput, ...]
    metadata: dict[str, object] = field(default_factory=dict)


class YoloXConversionRunner(Protocol):
    """执行 YOLOX 导出与转换任务的 worker 接口。"""

    def run_conversion(self, request: YoloXConversionRunRequest) -> YoloXConversionRunResult:
        """执行转换并返回结果。

        参数：
        - request：转换执行请求。

        返回：
        - 转换执行结果。
        """

        ...


class LocalYoloXConversionRunner:
    """使用本地文件存储执行 YOLOX ONNX/OpenVINO 转换链。"""

    def __init__(self, *, dataset_storage: LocalDatasetStorage) -> None:
        """初始化本地转换 runner。

        参数：
        - dataset_storage：本地文件存储服务。
        """

        self.dataset_storage = dataset_storage

    def run_conversion(self, request: YoloXConversionRunRequest) -> YoloXConversionRunResult:
        """执行当前已接通的 ONNX/OpenVINO 转换链并返回结果。

        参数：
        - request：转换执行请求。

        返回：
        - YoloXConversionRunResult：转换执行结果。
        """

        if not request.plan_steps:
            raise InvalidRequestError("转换计划 steps 不能为空")
        session = PyTorchYoloXRuntimeSession.load(
            dataset_storage=self.dataset_storage,
            runtime_target=request.source_runtime_target,
        )
        onnx_module, onnxruntime_module, onnx_simplify = _import_onnx_dependencies()
        base_name = _build_output_base_name(request.source_runtime_target)
        onnx_object_key = f"{request.output_object_prefix}/artifacts/builds/{base_name}.onnx"
        optimized_object_key = f"{request.output_object_prefix}/artifacts/builds/{base_name}.optimized.onnx"
        openvino_object_key = f"{request.output_object_prefix}/artifacts/builds/{base_name}.openvino.xml"
        openvino_ir_build_precision = _resolve_openvino_ir_build_precision(request.metadata)
        executed_step_kinds: list[str] = []
        validation_summary: dict[str, object] = {}
        onnx_output: YoloXConversionOutput | None = None
        optimized_output: YoloXConversionOutput | None = None
        openvino_output: YoloXConversionOutput | None = None

        for step in request.plan_steps:
            executed_step_kinds.append(step.kind)
            if step.kind == "export-onnx":
                export_summary = self._export_onnx(
                    session=session,
                    output_object_key=onnx_object_key,
                    onnx_module=onnx_module,
                )
                onnx_output = YoloXConversionOutput(
                    target_format="onnx",
                    object_uri=onnx_object_key,
                    file_type=YOLOX_ONNX_FILE,
                    metadata=export_summary,
                )
                continue
            if step.kind == "validate-onnx":
                validation_summary = self._validate_onnx(
                    session=session,
                    onnx_object_key=onnx_object_key,
                    onnx_module=onnx_module,
                    onnxruntime_module=onnxruntime_module,
                )
                if onnx_output is not None:
                    onnx_output = YoloXConversionOutput(
                        target_format=onnx_output.target_format,
                        object_uri=onnx_output.object_uri,
                        file_type=onnx_output.file_type,
                        metadata={**onnx_output.metadata, "validation_summary": validation_summary},
                    )
                continue
            if step.kind == "optimize-onnx":
                if onnx_output is None:
                    raise ServiceConfigurationError("optimize-onnx 缺少 export-onnx 输出")
                optimize_summary = self._optimize_onnx(
                    source_object_key=onnx_object_key,
                    output_object_key=optimized_object_key,
                    onnx_module=onnx_module,
                    onnx_simplify=onnx_simplify,
                )
                optimized_output = YoloXConversionOutput(
                    target_format="onnx-optimized",
                    object_uri=optimized_object_key,
                    file_type=YOLOX_ONNX_OPTIMIZED_FILE,
                    metadata={
                        **optimize_summary,
                        "validation_summary": validation_summary,
                        "source_object_uri": onnx_object_key,
                    },
                )
                continue
            if step.kind == "build-openvino-ir":
                if optimized_output is None:
                    raise ServiceConfigurationError("build-openvino-ir 缺少 optimize-onnx 输出")
                build_summary = self._build_openvino_ir(
                    source_object_key=optimized_object_key,
                    output_object_key=openvino_object_key,
                    build_precision=openvino_ir_build_precision,
                )
                openvino_output = YoloXConversionOutput(
                    target_format="openvino-ir",
                    object_uri=openvino_object_key,
                    file_type=YOLOX_OPENVINO_IR_FILE,
                    metadata={
                        **build_summary,
                        "validation_summary": validation_summary,
                        "source_object_uri": optimized_object_key,
                    },
                )
                continue
            raise InvalidRequestError(
                "当前 conversion runner 不支持指定步骤",
                details={"step_kind": step.kind},
            )

        outputs: list[YoloXConversionOutput] = []
        if onnx_output is not None:
            outputs.append(onnx_output)
        if optimized_output is not None:
            outputs.append(optimized_output)
        if openvino_output is not None:
            outputs.append(openvino_output)
        return YoloXConversionRunResult(
            conversion_task_id=request.conversion_task_id,
            outputs=tuple(outputs),
            metadata={
                "phase": _resolve_conversion_phase(request.target_formats),
                "executed_step_kinds": executed_step_kinds,
                "validation_summary": validation_summary,
                "conversion_options": _build_conversion_options_metadata(
                    target_formats=request.target_formats,
                    openvino_ir_build_precision=openvino_ir_build_precision,
                ),
            },
        )

    def _export_onnx(
        self,
        *,
        session: PyTorchYoloXRuntimeSession,
        output_object_key: str,
        onnx_module: object,
    ) -> dict[str, object]:
        """把 PyTorch checkpoint 导出为 ONNX。"""

        del onnx_module
        output_path = self.dataset_storage.resolve(output_object_key)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        dummy_input = session.imports.torch.randn(
            1,
            3,
            session.runtime_target.input_size[0],
            session.runtime_target.input_size[1],
            device=session.device_name,
            dtype=session.imports.torch.float32,
        )
        with session.imports.torch.no_grad():
            session.imports.torch.onnx.export(
                session.model,
                dummy_input,
                str(output_path),
                export_params=True,
                opset_version=17,
                do_constant_folding=True,
                input_names=["images"],
                output_names=["predictions"],
            )
        return {
            "stage": "export-onnx",
            "object_uri": output_object_key,
            "opset_version": 17,
            "input_size": list(session.runtime_target.input_size),
            "exporter_mode": "legacy-torch-onnx-export",
        }

    def _validate_onnx(
        self,
        *,
        session: PyTorchYoloXRuntimeSession,
        onnx_object_key: str,
        onnx_module: object,
        onnxruntime_module: object,
    ) -> dict[str, object]:
        """执行 ONNX 合法性和数值校验。"""

        onnx_path = self.dataset_storage.resolve(onnx_object_key)
        onnx_model = onnx_module.load(str(onnx_path))
        onnx_module.checker.check_model(onnx_model)

        dummy_input = session.imports.torch.randn(
            1,
            3,
            session.runtime_target.input_size[0],
            session.runtime_target.input_size[1],
            device=session.device_name,
            dtype=session.imports.torch.float32,
        )
        with session.imports.torch.no_grad():
            torch_outputs = _normalize_model_outputs(session.model(dummy_input), session.imports)
        ort_session = onnxruntime_module.InferenceSession(
            str(onnx_path),
            providers=["CPUExecutionProvider"],
        )
        ort_outputs = ort_session.run(
            None,
            {ort_session.get_inputs()[0].name: dummy_input.detach().cpu().numpy()},
        )
        summary = _summarize_numeric_validation(
            np_module=session.imports.np,
            torch_outputs=torch_outputs,
            ort_outputs=ort_outputs,
        )
        if not bool(summary["allclose"]):
            raise ServiceConfigurationError(
                "ONNX 数值校验失败",
                details=dict(summary),
            )
        return summary

    def _optimize_onnx(
        self,
        *,
        source_object_key: str,
        output_object_key: str,
        onnx_module: object,
        onnx_simplify: object,
    ) -> dict[str, object]:
        """执行 ONNX 简化优化并写回独立输出。"""

        source_path = self.dataset_storage.resolve(source_object_key)
        optimized_path = self.dataset_storage.resolve(output_object_key)
        optimized_path.parent.mkdir(parents=True, exist_ok=True)
        source_model = onnx_module.load(str(source_path))
        simplified_model, check_passed = onnx_simplify(source_model)
        if not check_passed:
            raise ServiceConfigurationError("ONNX simplify 校验失败")
        onnx_module.checker.check_model(simplified_model)
        onnx_module.save(simplified_model, str(optimized_path))
        return {
            "stage": "optimize-onnx",
            "object_uri": output_object_key,
            "source_object_uri": source_object_key,
            "optimizer": "onnxsim",
        }

    def _build_openvino_ir(
        self,
        *,
        source_object_key: str,
        output_object_key: str,
        build_precision: str,
    ) -> dict[str, object]:
        """把 optimized ONNX 转换为 OpenVINO IR。

        参数：
        - source_object_key：来源 optimized ONNX object key。
        - output_object_key：目标 OpenVINO XML object key。
	- build_precision：OpenVINO IR 权重压缩策略。

        返回：
        - dict[str, object]：OpenVINO IR 构建摘要。
        """

        source_path = self.dataset_storage.resolve(source_object_key)
        output_path = self.dataset_storage.resolve(output_object_key)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        compress_to_fp16 = build_precision == "fp16"
        completed_process = subprocess.run(
            [
                sys.executable,
                "-c",
                _OPENVINO_IR_BUILD_SCRIPT,
                str(source_path),
                str(output_path),
                build_precision,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if completed_process.returncode != 0:
            raise ServiceConfigurationError(
                "OpenVINO IR 构建失败",
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
                "OpenVINO IR 构建未生成完整的 xml/bin 产物",
                details={
                    "output_object_uri": output_object_key,
                    "weights_object_uri": _resolve_openvino_weights_object_key(output_object_key),
                },
            )
        return {
            "stage": "build-openvino-ir",
            "object_uri": output_object_key,
            "source_object_uri": source_object_key,
            "weights_object_uri": _resolve_openvino_weights_object_key(output_object_key),
            "build_precision": build_precision,
            "compress_to_fp16": compress_to_fp16,
            "execution_mode": "subprocess-openvino-convert-model",
        }


def _resolve_openvino_ir_build_precision(metadata: dict[str, object]) -> str:
    """从 worker metadata 中解析 OpenVINO IR 构建精度策略。

    参数：
    - metadata：转换执行请求附加元数据。

    返回：
    - str：OpenVINO IR 构建精度；当前支持 fp32 或 fp16。
    """

    raw_precision = metadata.get(_OPENVINO_IR_PRECISION_OPTION_KEY)
    if raw_precision is None:
        return "fp32"
    if isinstance(raw_precision, str):
        normalized_precision = raw_precision.strip().lower()
        if normalized_precision in _SUPPORTED_OPENVINO_IR_BUILD_PRECISIONS:
            return normalized_precision
    raise InvalidRequestError(
        "openvino_ir_precision 必须是 fp32 或 fp16",
        details={_OPENVINO_IR_PRECISION_OPTION_KEY: raw_precision},
    )


def _build_conversion_options_metadata(
    *,
    target_formats: tuple[str, ...],
    openvino_ir_build_precision: str,
) -> dict[str, object]:
    """根据目标格式生成转换报告中的附加策略摘要。

    参数：
    - target_formats：当前转换目标格式列表。
    - openvino_ir_build_precision：OpenVINO IR 构建精度策略。

    返回：
    - dict[str, object]：转换策略摘要。
    """

    if "openvino-ir" not in target_formats:
        return {}
    return {_OPENVINO_IR_PRECISION_OPTION_KEY: openvino_ir_build_precision}


def _import_onnx_dependencies() -> tuple[object, object, object]:
    """导入 ONNX phase-1 所需依赖。"""

    try:
        import onnx
        import onnxruntime
        from onnxsim import simplify
    except ImportError as error:
        raise ServiceConfigurationError("当前环境缺少 ONNX phase-1 所需依赖") from error
    return onnx, onnxruntime, simplify


def _build_output_base_name(runtime_target: RuntimeTargetSnapshot) -> str:
    """根据来源模型信息构建稳定输出文件名前缀。"""

    model_name = runtime_target.model_name.replace(" ", "-").lower() or "yolox"
    model_scale = runtime_target.model_scale.strip().lower() or "unknown"
    return f"{model_name}-{model_scale}"


def _resolve_conversion_phase(target_formats: tuple[str, ...]) -> str:
    """根据目标格式集合返回当前转换阶段标识。"""

    if "openvino-ir" in target_formats:
        return "phase-2-openvino-ir"
    return "phase-1-onnx"


def _resolve_openvino_weights_object_key(output_object_key: str) -> str:
    """根据 OpenVINO XML object key 推导同名 bin object key。"""

    return PurePosixPath(output_object_key).with_suffix(".bin").as_posix()


def _normalize_model_outputs(model_outputs: object, imports: object) -> list[object]:
    """把模型输出规整为 numpy 数组列表。"""

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
        "当前模型输出格式不受支持",
        details={"output_type": model_outputs.__class__.__name__},
    )


def _summarize_numeric_validation(
    *,
    np_module: object,
    torch_outputs: list[object],
    ort_outputs: list[object],
) -> dict[str, object]:
    """计算 PyTorch 与 ONNX 输出的数值差异摘要。"""

    if len(torch_outputs) != len(ort_outputs):
        raise ServiceConfigurationError(
            "ONNX 输出数量与 PyTorch 不一致",
            details={"torch_output_count": len(torch_outputs), "ort_output_count": len(ort_outputs)},
        )
    max_abs_diff = 0.0
    mean_abs_diff = 0.0
    compared_output_count = 0
    for torch_output, ort_output in zip(torch_outputs, ort_outputs, strict=True):
        if tuple(torch_output.shape) != tuple(ort_output.shape):
            raise ServiceConfigurationError(
                "ONNX 输出形状与 PyTorch 不一致",
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