"""失败 engine 的隔离、完整性、预算与 staging 清理回归。"""

import json
from pathlib import Path

import numpy as np
import pytest

from backend.service.application.conversions.publication import cleanup_aborted_conversion_staging
from backend.service.application.conversions.runtime.numeric_failure_evidence import preserve_conversion_failure
from backend.service.application.errors import ServiceConfigurationError
from backend.service.infrastructure.object_store.local_dataset_storage import DatasetStorageSettings, LocalDatasetStorage


def test_tensorrt_numeric_failure_reports_actual_validation_stage(tmp_path, monkeypatch):
    """共享 TopK/ONNX 辅助规则不能把 TensorRT 错误阶段标为 ONNX 转换。"""
    import onnx
    from onnx import TensorProto, helper
    from backend.service.application.models import tensorrt_artifact_validation as validation
    graph = helper.make_graph([helper.make_node("Identity", ["image"], ["output"])], "test",
        [helper.make_tensor_value_info("image", TensorProto.FLOAT, [1, 3, 2, 2])],
        [helper.make_tensor_value_info("output", TensorProto.FLOAT, [1, 3, 2, 2])])
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 17)])
    model.ir_version = 10
    source = tmp_path / "source.onnx"
    onnx.save(model, source)
    monkeypatch.setattr(validation, "execute_validation_engine", lambda **_: {"output": np.zeros((1, 3, 2, 2), dtype=np.float32)})
    with pytest.raises(ServiceConfigurationError) as raised:
        validation.validate_tensorrt_engine_against_onnx(source_path=source, engine=None, builder=None,
            network=None, config=None, runtime=None, trt=None, build_precision="fp32")
    assert raised.value.details["stage"] == "validate-tensorrt"
    assert raised.value.details["target_runtime"] == "tensorrt"
    assert raised.value.details["passed"] is False


def test_engine_buffer_without_len_is_preserved(tmp_path):
    """模拟 IHostMemory 的 buffer-only 语义，nbytes 预算不能调用 len。"""
    class BufferWithoutLength(np.ndarray):
        """仍提供 buffer 协议，但拒绝 Python 序列长度。"""
        def __len__(self):
            raise TypeError("no len")
    engine = np.arange(16, dtype=np.uint8).view(BufferWithoutLength)
    source = tmp_path / "source.onnx"
    source.write_bytes(b"onnx")
    evidence = preserve_conversion_failure(source_path=source, output_path=tmp_path / "model.engine",
        engine_bytes=engine, observations={"observed_engine": memoryview(engine)}, error=RuntimeError("numeric"),
        precision="fp16", runtime_version="test")
    assert "capture_error" not in evidence
    root = Path(evidence["directory"])
    assert (root / "rejected-engine.bin").read_bytes() == bytes(range(16))
    assert (root / "observed-000.bin").read_bytes() == bytes(range(16))


def test_evidence_survives_aborted_staging_cleanup(tmp_path: Path) -> None:
    """走正式清理函数后仍可读取拒绝的 engine 和数值数组。"""
    storage = LocalDatasetStorage(DatasetStorageSettings(root_dir=str(tmp_path)))
    output = tmp_path / "task-runs/conversion/task-test/attempts/attempt-test/staging/artifacts/builds/model.engine"
    output.parent.mkdir(parents=True)
    source = output.with_suffix(".onnx")
    source.write_bytes(b"onnx")
    error = ServiceConfigurationError("numeric", details={"passed": False})
    value = np.arange(12, dtype=np.float32).reshape(1, 3, 2, 2)
    evidence = preserve_conversion_failure(source_path=source, output_path=output, engine_bytes=b"rejected",
                                        observations={"input": value}, error=error,
                                        precision="fp32", runtime_version="test")
    cleanup_aborted_conversion_staging(dataset_storage=storage, task_id="task-test",
                                       conversion_attempt_id="attempt-test", publication_token="test")
    directory = Path(evidence["directory"])
    manifest = json.loads((directory / "manifest.json").read_text())
    assert manifest["published"] is False
    assert (directory / "rejected-engine.bin").read_bytes() == b"rejected"
    np.testing.assert_array_equal(np.load(directory / "array-000.npy", allow_pickle=False), value)
    assert not output.exists()


def test_evidence_budget_and_capture_error_do_not_hide_numeric_failure(tmp_path: Path) -> None:
    """预算不足显式记录省略；不可写时返回保存错误而非替换原始错误。"""
    source = tmp_path / "source.onnx"
    source.write_bytes(b"onnx")
    args = dict(source_path=source, output_path=tmp_path / "model.engine", engine_bytes=b"engine",
                observations={"input": np.ones((1, 10))}, error=RuntimeError("numeric"),
                precision="fp32", runtime_version="test", maximum_bytes=6)
    evidence = preserve_conversion_failure(**args)
    manifest = json.loads(Path(evidence["manifest"]).read_text())
    assert evidence["saved_bytes"] <= 6
    assert manifest["error"]["message"] == "numeric"
    assert manifest["files"][1]["reason"] == "binary_budget_exceeded"
    blocked = tmp_path / "blocked"
    blocked.write_bytes(b"not a directory")
    args["output_path"] = blocked / "model.engine"
    assert "capture_error" in preserve_conversion_failure(**args)
