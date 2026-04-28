"""最小 ModelFile 对象定义。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ModelFile:
    """描述模型链路中的最小文件记录。

    字段：
    - file_id：文件记录 id。
    - project_id：所属项目 id。
    - model_id：所属 Model id。
    - model_version_id：所属 ModelVersion id。
    - model_build_id：所属 ModelBuild id。
    - file_type：文件类型。
    - logical_name：文件逻辑名。
    - storage_uri：文件存储位置。
    - metadata：附加元数据。
    """

    file_id: str
    project_id: str
    model_id: str
    file_type: str
    logical_name: str
    storage_uri: str
    model_version_id: str | None = None
    model_build_id: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)