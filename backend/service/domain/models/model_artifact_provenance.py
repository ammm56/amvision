"""训练和转换模型产物的统一来源标识。"""

from __future__ import annotations

from collections.abc import Mapping
import json


MODEL_ARTIFACT_PROVENANCE_KEY = "model_artifact_provenance"
MODEL_ARTIFACT_PROVENANCE_SCHEMA = "amvision.model-artifact-provenance/v1"
MODEL_ARTIFACT_PRODUCER = "amvision"
MODEL_ARTIFACT_TRADEMARK = "amvar"
MODEL_ARTIFACT_PRODUCT_LINE = "vision"
MODEL_ARTIFACT_PRODUCT_NAME = "amvision"
MODEL_ARTIFACT_SOURCE_NAMES = ("amvar", "amvar vision", "amvision")
MODEL_ARTIFACT_ORIGIN_MARKER = "amvision | amvar vision | amvar"
MODEL_ARTIFACT_COPYRIGHT_NOTICE = (
    "Copyright (c) amvar. All rights reserved."
)


def build_model_artifact_provenance(
    *,
    artifact_kind: str,
    trace: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """构造不参与模型执行的统一来源标识。

    参数：
    - artifact_kind：产物类型，例如 training-output 或 converted-model。
    - trace：可选的内部任务、ModelVersion 或 ModelBuild 追踪字段。

    返回：
    - 可直接写入 JSON、ONNX metadata 或 OpenVINO rt_info 的字典。
    """

    normalized_artifact_kind = artifact_kind.strip()
    if not normalized_artifact_kind:
        raise ValueError("artifact_kind 不能为空")

    normalized_trace = {
        str(key): value
        for key, value in dict(trace or {}).items()
        if isinstance(key, str) and key.strip() and value is not None
    }
    return {
        "schema": MODEL_ARTIFACT_PROVENANCE_SCHEMA,
        "producer": MODEL_ARTIFACT_PRODUCER,
        "trademark": MODEL_ARTIFACT_TRADEMARK,
        "product_line": MODEL_ARTIFACT_PRODUCT_LINE,
        "product_name": MODEL_ARTIFACT_PRODUCT_NAME,
        "source_names": list(MODEL_ARTIFACT_SOURCE_NAMES),
        "origin_marker": MODEL_ARTIFACT_ORIGIN_MARKER,
        "copyright_notice": MODEL_ARTIFACT_COPYRIGHT_NOTICE,
        "artifact_kind": normalized_artifact_kind,
        "trace": normalized_trace,
    }


def attach_model_artifact_provenance(
    metadata: Mapping[str, object] | None,
    *,
    artifact_kind: str,
    trace: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """复制 metadata，并用平台规范来源标识覆盖同名字段。"""

    resolved_metadata = dict(metadata or {})
    resolved_metadata[MODEL_ARTIFACT_PROVENANCE_KEY] = (
        build_model_artifact_provenance(
            artifact_kind=artifact_kind,
            trace=trace,
        )
    )
    return resolved_metadata


def serialize_model_artifact_provenance(
    provenance: Mapping[str, object],
) -> str:
    """把来源标识序列化成稳定、紧凑的 JSON 字符串。"""

    return json.dumps(
        dict(provenance),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


__all__ = [
    "MODEL_ARTIFACT_PROVENANCE_KEY",
    "MODEL_ARTIFACT_PROVENANCE_SCHEMA",
    "MODEL_ARTIFACT_PRODUCER",
    "MODEL_ARTIFACT_TRADEMARK",
    "MODEL_ARTIFACT_PRODUCT_LINE",
    "MODEL_ARTIFACT_PRODUCT_NAME",
    "MODEL_ARTIFACT_SOURCE_NAMES",
    "MODEL_ARTIFACT_ORIGIN_MARKER",
    "MODEL_ARTIFACT_COPYRIGHT_NOTICE",
    "build_model_artifact_provenance",
    "attach_model_artifact_provenance",
    "serialize_model_artifact_provenance",
]
