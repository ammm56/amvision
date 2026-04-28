"""YOLOX 模型应用服务接口定义。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class YoloXPretrainedImportRequest:
    """描述一次预训练模型导入请求。

    字段：
    - project_id：所属项目 id。
    - model_name：登记到平台的模型名。
    - source_uri：预训练模型来源 URI。
    - model_scale：模型 scale。
    - task_family：任务类型。
    - labels_file_id：类别映射文件 id。
    - metadata：附加元数据。
    """

    project_id: str
    model_name: str
    source_uri: str
    model_scale: str
    task_family: str = "detection"
    labels_file_id: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class YoloXTrainingOutputRegistration:
    """描述训练输出登记请求。

    字段：
    - project_id：所属项目 id。
    - training_task_id：训练任务 id。
    - model_name：登记到平台的模型名。
    - model_scale：模型 scale。
    - dataset_version_id：训练使用的 DatasetVersion id。
    - checkpoint_file_id：checkpoint 文件 id。
    - labels_file_id：标签文件 id。
    - metrics_file_id：指标文件 id。
    - metadata：附加元数据。
    """

    project_id: str
    training_task_id: str
    model_name: str
    model_scale: str
    dataset_version_id: str
    checkpoint_file_id: str
    labels_file_id: str | None = None
    metrics_file_id: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)


class YoloXModelService(Protocol):
    """YOLOX 模型登记接口。"""

    def import_pretrained(self, request: YoloXPretrainedImportRequest) -> str:
        """导入预训练模型并返回登记后的模型版本 id。

        参数：
        - request：预训练模型导入请求。

        返回：
        - 新登记的 ModelVersion id。
        """

        ...

    def register_training_output(self, request: YoloXTrainingOutputRegistration) -> str:
        """登记训练输出并返回新的模型版本 id。

        参数：
        - request：训练输出登记请求。

        返回：
        - 新登记的 ModelVersion id。
        """

        ...