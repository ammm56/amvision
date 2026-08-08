"""YOLO core export 执行边界测试。"""

from __future__ import annotations

from pathlib import Path
import subprocess
from types import SimpleNamespace

import numpy as np
import pytest

from backend.service.application.errors import ServiceConfigurationError
from backend.service.application.models.yolo_core_common.export import (
    YOLO_OPENVINO_IR_BUILD_SCRIPT_FILE,
    YOLO_TENSORRT_ENGINE_BUILD_SCRIPT_FILE,
    build_yolo_openvino_ir,
    build_yolo_tensorrt_engine,
    resolve_yolo_openvino_weights_object_key,
    summarize_yolo_onnx_numeric_validation,
    validate_yolo_converted_input_tensor,
    validate_yolo_onnx_graph_output_contract,
)
from backend.service.application.models.yolo11_core.export import (
    build_yolo11_export_task_plan,
    build_yolo11_openvino_ir,
    build_yolo11_tensorrt_engine,
)
from backend.service.application.models.yolo26_core.export import (
    build_yolo26_export_task_plan,
    build_yolo26_openvino_ir,
    build_yolo26_tensorrt_engine,
)
from backend.service.application.models.yolov8_core.export import (
    build_yolov8_export_task_plan,
    build_yolov8_openvino_ir,
    build_yolov8_tensorrt_engine,
)
from backend.service.domain.models.model_input_spec import (
    SpatialSize,
    build_platform_model_input_spec,
)


def test_yolo_openvino_build_helper_reports_xml_and_bin_outputs(tmp_path: Path) -> None:
    """验证 OpenVINO 构建 helper 只依赖脚本 runner 并检查 xml/bin 产物。"""

    source_path = tmp_path / "model.optimized.onnx"
    output_path = tmp_path / "model.openvino.xml"
    source_path.write_bytes(b"fake-onnx")

    def fake_script_runner(
        *,
        script_file_name: str,
        args: list[str],
    ) -> subprocess.CompletedProcess[str]:
        """模拟 OpenVINO 子进程构建。"""

        assert script_file_name == YOLO_OPENVINO_IR_BUILD_SCRIPT_FILE
        assert args == [str(source_path), str(output_path), "fp16"]
        output_path.write_text("<xml />", encoding="utf-8")
        output_path.with_suffix(".bin").write_bytes(b"fake-bin")
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=(
                '{"input_name":"images","input_shape":[1,3,256,384],'
                '"input_dtype":"f32"}\n'
            ),
            stderr="",
        )

    summary = build_yolo_openvino_ir(
        source_path=source_path,
        output_path=output_path,
        source_object_key="runs/model.optimized.onnx",
        output_object_key="runs/model.openvino.xml",
        build_precision="fp16",
        run_conversion_script=fake_script_runner,
    )

    assert summary["stage"] == "build-openvino-ir"
    assert summary["weights_object_uri"] == "runs/model.openvino.bin"
    assert summary["compress_to_fp16"] is True
    assert summary["input_shape"] == [1, 3, 256, 384]
    assert resolve_yolo_openvino_weights_object_key("runs/model.openvino.xml") == (
        "runs/model.openvino.bin"
    )


def test_yolo_tensorrt_build_helper_parses_stdout_payload(tmp_path: Path) -> None:
    """验证 TensorRT 构建 helper 会检查 engine 产物并解析 stdout JSON。"""

    source_path = tmp_path / "model.optimized.onnx"
    output_path = tmp_path / "model.tensorrt.engine"
    source_path.write_bytes(b"fake-onnx")

    def fake_script_runner(
        *,
        script_file_name: str,
        args: list[str],
    ) -> subprocess.CompletedProcess[str]:
        """模拟 TensorRT 子进程构建。"""

        assert script_file_name == YOLO_TENSORRT_ENGINE_BUILD_SCRIPT_FILE
        assert args == [str(source_path), str(output_path), "fp32"]
        output_path.write_bytes(b"fake-engine")
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=(
                '{"builder":"fake-tensorrt","input_name":"images",'
                '"input_shape":[1,3,256,384],"input_dtype":"DataType.FLOAT"}\n'
            ),
            stderr="",
        )

    summary = build_yolo_tensorrt_engine(
        source_path=source_path,
        output_path=output_path,
        source_object_key="runs/model.optimized.onnx",
        output_object_key="runs/model.tensorrt.engine",
        build_precision="fp32",
        run_conversion_script=fake_script_runner,
    )

    assert summary["stage"] == "build-tensorrt-engine"
    assert summary["engine_file_bytes"] == len(b"fake-engine")
    assert summary["builder"] == "fake-tensorrt"
    assert summary["input_shape"] == [1, 3, 256, 384]


def test_yolo_onnx_output_contract_rejects_training_intermediate_tensors() -> None:
    """验证公开 predictions 之外的训练中间输出不能流入转换和部署。"""

    onnx_model = SimpleNamespace(
        graph=SimpleNamespace(
            output=(
                SimpleNamespace(name="predictions"),
                SimpleNamespace(name="raw_head_feature"),
            )
        )
    )

    with pytest.raises(ServiceConfigurationError, match="输出与任务公开契约"):
        validate_yolo_onnx_graph_output_contract(
            onnx_model=onnx_model,
            expected_output_names=("predictions",),
        )


@pytest.mark.parametrize(
    "build_export_plan",
    (
        build_yolov8_export_task_plan,
        build_yolo11_export_task_plan,
        build_yolo26_export_task_plan,
    ),
)
@pytest.mark.parametrize(
    "task_type",
    ("detection", "classification", "segmentation", "pose", "obb"),
)
def test_yolo_export_plans_only_emit_deployment_outputs(
    build_export_plan: object,
    task_type: str,
) -> None:
    """验证三代五任务均开启纯部署输出模式。"""

    plan = build_export_plan(task_type=task_type, target_formats=("onnx",))

    assert plan.export_mode_enabled is True


@pytest.mark.parametrize(
    "build_openvino_ir",
    (
        build_yolov8_openvino_ir,
        build_yolo11_openvino_ir,
        build_yolo26_openvino_ir,
    ),
)
def test_yolo_generation_openvino_entrypoints_return_real_input_tensor(
    tmp_path: Path,
    build_openvino_ir: object,
) -> None:
    """三代 YOLO 的公开 OpenVINO 入口统一返回子进程读取的真实张量。"""

    source_path = tmp_path / "model.optimized.onnx"
    output_path = tmp_path / "model.openvino.xml"
    source_path.write_bytes(b"fake-onnx")

    def fake_script_runner(
        *, script_file_name: str, args: list[str]
    ) -> subprocess.CompletedProcess[str]:
        """模拟生成完整 IR 和真实输入摘要。"""

        assert script_file_name == YOLO_OPENVINO_IR_BUILD_SCRIPT_FILE
        output_path.write_text("<xml />", encoding="utf-8")
        output_path.with_suffix(".bin").write_bytes(b"fake-bin")
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=(
                '{"input_name":"images","input_shape":[1,3,256,384],'
                '"input_dtype":"float32"}\n'
            ),
            stderr="",
        )

    summary = build_openvino_ir(
        source_path=source_path,
        output_path=output_path,
        source_object_key="runs/model.optimized.onnx",
        output_object_key="runs/model.openvino.xml",
        build_precision="fp32",
        run_conversion_script=fake_script_runner,
    )

    assert summary["input_name"] == "images"
    assert summary["input_shape"] == [1, 3, 256, 384]
    assert summary["input_dtype"] == "float32"


@pytest.mark.parametrize(
    "build_tensorrt_engine",
    (
        build_yolov8_tensorrt_engine,
        build_yolo11_tensorrt_engine,
        build_yolo26_tensorrt_engine,
    ),
)
def test_yolo_generation_tensorrt_entrypoints_return_real_input_tensor(
    tmp_path: Path,
    build_tensorrt_engine: object,
) -> None:
    """三代 YOLO 的公开 TensorRT 入口统一返回网络解析后的真实张量。"""

    source_path = tmp_path / "model.optimized.onnx"
    output_path = tmp_path / "model.tensorrt.engine"
    source_path.write_bytes(b"fake-onnx")

    def fake_script_runner(
        *, script_file_name: str, args: list[str]
    ) -> subprocess.CompletedProcess[str]:
        """模拟生成 engine 和真实输入摘要。"""

        assert script_file_name == YOLO_TENSORRT_ENGINE_BUILD_SCRIPT_FILE
        output_path.write_bytes(b"fake-engine")
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=(
                '{"input_name":"images","input_shape":[1,3,256,384],'
                '"input_dtype":"DataType.FLOAT"}\n'
            ),
            stderr="",
        )

    summary = build_tensorrt_engine(
        source_path=source_path,
        output_path=output_path,
        source_object_key="runs/model.optimized.onnx",
        output_object_key="runs/model.tensorrt.engine",
        build_precision="fp32",
        run_conversion_script=fake_script_runner,
    )

    assert summary["input_name"] == "images"
    assert summary["input_shape"] == [1, 3, 256, 384]
    assert summary["input_dtype"] == "DataType.FLOAT"


def test_yolo_numeric_validation_summary_accepts_close_outputs() -> None:
    """验证 ONNX 数值校验摘要能处理多输出。"""

    torch_outputs = [
        np.array([[1.0, 2.0]], dtype=np.float32),
        np.array([[3.0]], dtype=np.float32),
    ]
    ort_outputs = [
        np.array([[1.00001, 2.00001]], dtype=np.float32),
        np.array([[3.00001]], dtype=np.float32),
    ]

    summary = summarize_yolo_onnx_numeric_validation(
        np_module=np,
        torch_outputs=torch_outputs,
        ort_outputs=ort_outputs,
    )

    assert summary["stage"] == "validate-onnx"
    assert summary["allclose"] is True
    assert summary["output_count"] == 2


@pytest.mark.parametrize(
    "artifact_format",
    ("onnx", "onnx-optimized", "openvino-ir", "tensorrt-engine"),
)
def test_non_square_converted_input_tensor_matches_source_contract(
    artifact_format: str,
) -> None:
    """每种转换产物都以自身真实 NCHW 形状核对非方形输入契约。"""

    input_tensor = {
        "name": "images",
        "layout": "NCHW",
        "shape": [1, 3, 256, 384],
        "dtype": "float32",
    }
    model_input_spec = {
        "tensor_layout": "NCHW",
        "tensor_shape": [1, 3, 256, 384],
        "dtype": "float32",
    }

    assert (
        validate_yolo_converted_input_tensor(
            input_tensor=input_tensor,
            model_input_spec_payload=model_input_spec,
            artifact_format=artifact_format,
        )
        == input_tensor
    )


def test_non_square_converted_input_tensor_rejects_width_height_swap() -> None:
    """真实产物一旦把 H/W 交换，登记和部署前立即失败。"""

    with pytest.raises(ServiceConfigurationError, match="输入形状"):
        validate_yolo_converted_input_tensor(
            input_tensor={
                "name": "images",
                "layout": "NCHW",
                "shape": [1, 3, 384, 256],
                "dtype": "float32",
            },
            model_input_spec_payload={
                "tensor_layout": "NCHW",
                "tensor_shape": [1, 3, 256, 384],
                "dtype": "float32",
            },
            artifact_format="tensorrt-engine",
        )


@pytest.mark.parametrize("model_type", ("yolov8", "yolo11", "yolo26"))
@pytest.mark.parametrize(
    "task_type",
    ("detection", "classification", "segmentation", "pose", "obb"),
)
@pytest.mark.parametrize(
    "artifact_format",
    ("onnx", "openvino-ir", "tensorrt-engine"),
)
def test_three_generation_five_task_non_square_conversion_contract_matrix(
    model_type: str,
    task_type: str,
    artifact_format: str,
) -> None:
    """三代五任务三种部署格式均保持同一非方形真实输入张量。"""

    model_input_spec = build_platform_model_input_spec(
        model_type=model_type,
        spatial_size=SpatialSize(width=384, height=256),
        task_type=task_type,
    ).to_payload()
    input_tensor = {
        "name": "images",
        "layout": "NCHW",
        "shape": [1, 3, 256, 384],
        "dtype": "float32",
    }

    validated = validate_yolo_converted_input_tensor(
        input_tensor=input_tensor,
        model_input_spec_payload=model_input_spec,
        artifact_format=artifact_format,
    )

    assert validated["shape"] == [1, 3, 256, 384]
