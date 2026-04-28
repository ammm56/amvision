"""YOLOX 转换 worker 接口定义。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class YoloXConversionRunRequest:
    """描述一次 YOLOX 转换执行请求。

    字段：
    - conversion_task_id：转换任务 id。
    - source_model_version_id：来源 ModelVersion id。
    - source_checkpoint_uri：来源 checkpoint 的 URI。
    - target_formats：目标输出格式列表。
    - output_object_prefix：输出目录前缀。
    - metadata：附加元数据。
    """

    conversion_task_id: str
    source_model_version_id: str
    source_checkpoint_uri: str
    target_formats: tuple[str, ...]
    output_object_prefix: str
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class YoloXConversionOutput:
    """描述单个转换输出文件。

    字段：
    - target_format：目标格式。
    - object_uri：输出文件 URI。
    - file_type：登记到平台的 file type。
    """

    target_format: str
    object_uri: str
    file_type: str


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