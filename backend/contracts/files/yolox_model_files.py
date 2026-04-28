"""YOLOX 模型文件命名与描述规则。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class YoloXFileNamingContext:
    """描述默认文件名生成所需的上下文。

    字段：
    - project_id：所属项目 id。
    - model_name：模型名称。
    - model_scale：模型 scale。
    - source_version：来源 ModelVersion 标识。
    - file_kind：文件类型。
    - suffix：文件后缀名。
    """

    project_id: str
    model_name: str
    model_scale: str
    source_version: str
    file_kind: str
    suffix: str


@dataclass(frozen=True)
class YoloXFileDescriptor:
    """描述一个已登记的 YOLOX 文件对象。

    字段：
    - file_kind：文件类型。
    - logical_name：文件逻辑名。
    - object_key：ObjectStore 中的 object key。
    - source_model_version_id：来源 ModelVersion id。
    - metadata：附加元数据。
    """

    file_kind: str
    logical_name: str
    object_key: str
    source_model_version_id: str
    metadata: dict[str, object] = field(default_factory=dict)


def build_default_file_name(context: YoloXFileNamingContext) -> str:
    """生成 YOLOX 文件的默认文件名。

    参数：
    - context：文件命名上下文。

    返回：
    - 默认文件名字符串。
    """

    return f"{context.model_name}_{context.model_scale}_{context.file_kind}.{context.suffix}"