"""最小模型对象定义。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


# 最小支持的模型版本来源类型。
ModelVersionSourceKind = Literal["pretrained-reference", "training-output"]
ModelScopeKind = Literal["project", "platform-base"]

PROJECT_MODEL_SCOPE: ModelScopeKind = "project"
PLATFORM_BASE_MODEL_SCOPE: ModelScopeKind = "platform-base"


@dataclass(frozen=True)
class Model:
    """描述平台中的最小 Model 对象。

    字段：
    - model_id：Model id。
    - project_id：所属项目 id；平台基础模型时为空。
    - scope_kind：模型作用域类型，显式区分 Project 内 Model 与平台基础模型。
    - model_name：模型名。
    - model_type：模型类型名称。
    - task_type：任务类型。
    - model_scale：模型 scale。
    - labels_file_id：标签文件 id。
    - metadata：附加元数据。
    """

    model_id: str
    project_id: str | None
    model_name: str
    model_type: str
    task_type: str
    model_scale: str
    scope_kind: ModelScopeKind = PROJECT_MODEL_SCOPE
    labels_file_id: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ModelVersion:
    """描述平台中的最小 ModelVersion 对象。

    字段：
    - model_version_id：ModelVersion id。
    - model_id：所属 Model id。
    - source_kind：版本来源类型。
    - dataset_version_id：关联的 DatasetVersion id。
    - training_task_id：关联的训练任务 id。
    - parent_version_id：父 ModelVersion id。
    - file_ids：关联的文件 id 列表。
    - metadata：附加元数据。
    """

    model_version_id: str
    model_id: str
    source_kind: ModelVersionSourceKind
    dataset_version_id: str | None = None
    training_task_id: str | None = None
    parent_version_id: str | None = None
    file_ids: tuple[str, ...] = ()
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ModelBuild:
    """描述平台中的最小 ModelBuild 对象。

    字段：
    - model_build_id：ModelBuild id。
    - model_id：所属 Model id。
    - source_model_version_id：来源 ModelVersion id。
    - build_format：build 格式。
    - runtime_profile_id：关联的 RuntimeProfile id。
    - conversion_task_id：关联的转换任务 id。
    - file_ids：关联的文件 id 列表。
    - metadata：附加元数据。
    """

    model_build_id: str
    model_id: str
    source_model_version_id: str
    build_format: str
    runtime_profile_id: str | None = None
    conversion_task_id: str | None = None
    file_ids: tuple[str, ...] = ()
    metadata: dict[str, object] = field(default_factory=dict)