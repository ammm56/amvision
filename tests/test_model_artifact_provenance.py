"""模型产物来源标识的领域与格式写入测试。"""

from __future__ import annotations

import json
from pathlib import Path

from backend.service.application.models.model_artifact_metadata import (
    ONNX_COPYRIGHT_METADATA_KEY,
    ONNX_PRODUCT_LINE_METADATA_KEY,
    ONNX_PRODUCT_NAME_METADATA_KEY,
    ONNX_PRODUCER_METADATA_KEY,
    ONNX_PROVENANCE_METADATA_KEY,
    ONNX_SOURCE_NAMES_METADATA_KEY,
    ONNX_TRADEMARK_METADATA_KEY,
    OPENVINO_PROVENANCE_RT_INFO_PATH,
    attach_openvino_model_artifact_provenance,
    write_onnx_model_artifact_provenance,
)
from backend.service.domain.models.model_artifact_provenance import (
    MODEL_ARTIFACT_COPYRIGHT_NOTICE,
    MODEL_ARTIFACT_ORIGIN_MARKER,
    MODEL_ARTIFACT_PRODUCT_LINE,
    MODEL_ARTIFACT_PRODUCT_NAME,
    MODEL_ARTIFACT_PRODUCER,
    MODEL_ARTIFACT_PROVENANCE_KEY,
    MODEL_ARTIFACT_PROVENANCE_SCHEMA,
    MODEL_ARTIFACT_SOURCE_NAMES,
    MODEL_ARTIFACT_TRADEMARK,
    attach_model_artifact_provenance,
    build_model_artifact_provenance,
)


def test_build_model_artifact_provenance_contains_stable_origin_fields() -> None:
    """验证统一来源结构包含固定品牌、版权和任务追踪字段。"""

    provenance = build_model_artifact_provenance(
        artifact_kind="training-output",
        trace={"training_task_id": "task-1", "ignored": None},
    )

    assert provenance == {
        "schema": MODEL_ARTIFACT_PROVENANCE_SCHEMA,
        "producer": MODEL_ARTIFACT_PRODUCER,
        "trademark": MODEL_ARTIFACT_TRADEMARK,
        "product_line": MODEL_ARTIFACT_PRODUCT_LINE,
        "product_name": MODEL_ARTIFACT_PRODUCT_NAME,
        "source_names": list(MODEL_ARTIFACT_SOURCE_NAMES),
        "origin_marker": MODEL_ARTIFACT_ORIGIN_MARKER,
        "copyright_notice": MODEL_ARTIFACT_COPYRIGHT_NOTICE,
        "artifact_kind": "training-output",
        "trace": {"training_task_id": "task-1"},
    }


def test_attach_model_artifact_provenance_overrides_untrusted_marker() -> None:
    """验证调用方不能用自定义同名字段覆盖平台规范来源标识。"""

    metadata = attach_model_artifact_provenance(
        {
            "metric": 0.9,
            MODEL_ARTIFACT_PROVENANCE_KEY: {"producer": "other"},
        },
        artifact_kind="converted-model",
    )

    assert metadata["metric"] == 0.9
    assert metadata[MODEL_ARTIFACT_PROVENANCE_KEY]["producer"] == "amvision"


def test_write_onnx_model_artifact_provenance_writes_searchable_fields(
    tmp_path: Path,
) -> None:
    """验证 ONNX metadata 同时包含规范 JSON 和可直接检索的品牌字段。"""

    model = _FakeOnnxModel()
    onnx_module = _FakeOnnxModule(model)
    model_path = tmp_path / "model.onnx"
    provenance = build_model_artifact_provenance(
        artifact_kind="converted-model",
        trace={"conversion_task_id": "conversion-1"},
    )

    write_onnx_model_artifact_provenance(
        onnx_module=onnx_module,
        model_path=model_path,
        provenance=provenance,
    )

    metadata = {item.key: item.value for item in model.metadata_props}
    assert json.loads(metadata[ONNX_PROVENANCE_METADATA_KEY]) == provenance
    assert metadata[ONNX_PRODUCER_METADATA_KEY] == "amvision"
    assert metadata[ONNX_TRADEMARK_METADATA_KEY] == "amvar"
    assert metadata[ONNX_PRODUCT_LINE_METADATA_KEY] == "vision"
    assert metadata[ONNX_PRODUCT_NAME_METADATA_KEY] == "amvision"
    assert (
        metadata[ONNX_SOURCE_NAMES_METADATA_KEY]
        == "amvar, amvar vision, amvision"
    )
    assert metadata[ONNX_COPYRIGHT_METADATA_KEY] == MODEL_ARTIFACT_COPYRIGHT_NOTICE
    assert onnx_module.saved_path == model_path


def test_attach_openvino_model_artifact_provenance_writes_rt_info() -> None:
    """验证 OpenVINO 来源标识写入独立 rt_info 路径。"""

    model = _FakeOpenVinoModel()
    provenance = build_model_artifact_provenance(
        artifact_kind="converted-model",
    )

    attach_openvino_model_artifact_provenance(
        openvino_model=model,
        provenance=provenance,
    )

    assert model.path == list(OPENVINO_PROVENANCE_RT_INFO_PATH)
    assert json.loads(model.value) == provenance


class _FakeOnnxMetadataItem:
    """最小 ONNX metadata item。"""

    def __init__(self) -> None:
        self.key = ""
        self.value = ""


class _FakeOnnxMetadataList(list):
    """提供 protobuf repeated field 的 add 接口。"""

    def add(self) -> _FakeOnnxMetadataItem:
        """新增并返回 metadata item。"""

        item = _FakeOnnxMetadataItem()
        self.append(item)
        return item


class _FakeOnnxModel:
    """最小 ONNX model。"""

    def __init__(self) -> None:
        self.metadata_props = _FakeOnnxMetadataList()


class _FakeOnnxModule:
    """记录 ONNX load/save 调用。"""

    def __init__(self, model: _FakeOnnxModel) -> None:
        self.model = model
        self.saved_path: Path | None = None

    def load(self, path: str) -> _FakeOnnxModel:
        """返回固定模型。"""

        del path
        return self.model

    def save(self, model: _FakeOnnxModel, path: str) -> None:
        """记录保存目标。"""

        assert model is self.model
        self.saved_path = Path(path)


class _FakeOpenVinoModel:
    """记录 OpenVINO set_rt_info 调用。"""

    def __init__(self) -> None:
        self.value = ""
        self.path: list[str] = []

    def set_rt_info(self, value: str, path: list[str]) -> None:
        """记录来源标识和值路径。"""

        self.value = value
        self.path = path
