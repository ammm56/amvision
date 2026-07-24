"""把统一来源标识写入支持内嵌 metadata 的模型格式。"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from backend.service.domain.models.model_artifact_provenance import (
    MODEL_ARTIFACT_COPYRIGHT_NOTICE,
    MODEL_ARTIFACT_PRODUCT_LINE,
    MODEL_ARTIFACT_PRODUCT_NAME,
    MODEL_ARTIFACT_PRODUCER,
    MODEL_ARTIFACT_SOURCE_NAMES,
    MODEL_ARTIFACT_TRADEMARK,
    serialize_model_artifact_provenance,
)


ONNX_PROVENANCE_METADATA_KEY = "amvision.provenance"
ONNX_PRODUCER_METADATA_KEY = "amvision.producer"
ONNX_TRADEMARK_METADATA_KEY = "amvision.trademark"
ONNX_PRODUCT_LINE_METADATA_KEY = "amvision.product_line"
ONNX_PRODUCT_NAME_METADATA_KEY = "amvision.product_name"
ONNX_SOURCE_NAMES_METADATA_KEY = "amvision.source_names"
ONNX_COPYRIGHT_METADATA_KEY = "amvision.copyright"
OPENVINO_PROVENANCE_RT_INFO_PATH = ("amvision", "model_artifact_provenance")


def write_onnx_model_artifact_provenance(
    *,
    onnx_module: object,
    model_path: Path,
    provenance: Mapping[str, object],
) -> None:
    """把来源标识写入 ONNX metadata_props，不改变图结构和推理输入输出。"""

    onnx_model = onnx_module.load(str(model_path))
    metadata_values = {
        ONNX_PROVENANCE_METADATA_KEY: serialize_model_artifact_provenance(
            provenance
        ),
        ONNX_PRODUCER_METADATA_KEY: MODEL_ARTIFACT_PRODUCER,
        ONNX_TRADEMARK_METADATA_KEY: MODEL_ARTIFACT_TRADEMARK,
        ONNX_PRODUCT_LINE_METADATA_KEY: MODEL_ARTIFACT_PRODUCT_LINE,
        ONNX_PRODUCT_NAME_METADATA_KEY: MODEL_ARTIFACT_PRODUCT_NAME,
        ONNX_SOURCE_NAMES_METADATA_KEY: ", ".join(
            MODEL_ARTIFACT_SOURCE_NAMES
        ),
        ONNX_COPYRIGHT_METADATA_KEY: MODEL_ARTIFACT_COPYRIGHT_NOTICE,
    }
    for key, value in metadata_values.items():
        _set_onnx_metadata_value(
            onnx_model=onnx_model,
            key=key,
            value=value,
        )
    onnx_module.save(onnx_model, str(model_path))


def attach_openvino_model_artifact_provenance(
    *,
    openvino_model: object,
    provenance: Mapping[str, object],
) -> None:
    """把来源标识写入 OpenVINO rt_info，不参与模型执行。"""

    openvino_model.set_rt_info(
        serialize_model_artifact_provenance(provenance),
        list(OPENVINO_PROVENANCE_RT_INFO_PATH),
    )


def _set_onnx_metadata_value(
    *,
    onnx_model: object,
    key: str,
    value: str,
) -> None:
    """新增或覆盖一个 ONNX metadata_props 字段。"""

    existing = next(
        (item for item in onnx_model.metadata_props if item.key == key),
        None,
    )
    if existing is not None:
        existing.value = value
        return
    metadata_item = onnx_model.metadata_props.add()
    metadata_item.key = key
    metadata_item.value = value


__all__ = [
    "ONNX_PROVENANCE_METADATA_KEY",
    "ONNX_PRODUCER_METADATA_KEY",
    "ONNX_TRADEMARK_METADATA_KEY",
    "ONNX_PRODUCT_LINE_METADATA_KEY",
    "ONNX_PRODUCT_NAME_METADATA_KEY",
    "ONNX_SOURCE_NAMES_METADATA_KEY",
    "ONNX_COPYRIGHT_METADATA_KEY",
    "OPENVINO_PROVENANCE_RT_INFO_PATH",
    "write_onnx_model_artifact_provenance",
    "attach_openvino_model_artifact_provenance",
]
