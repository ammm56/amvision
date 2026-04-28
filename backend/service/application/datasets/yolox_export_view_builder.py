"""YOLOX 训练导出视图构建接口定义。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class YoloXExportViewRequest:
    """描述一次 YOLOX 导出视图构建请求。

    字段：
    - project_id：所属项目 id。
    - dataset_id：数据集 id。
    - dataset_version_id：导出来源的 DatasetVersion id。
    - export_profile：导出 profile id。
    - output_object_prefix：导出目录前缀。
    - category_names：类别名列表。
    - include_test_split：是否包含 test split。
    """

    project_id: str
    dataset_id: str
    dataset_version_id: str
    export_profile: str = "coco-detection-v1"
    output_object_prefix: str = ""
    category_names: tuple[str, ...] = ()
    include_test_split: bool = True


@dataclass(frozen=True)
class YoloXExportViewManifest:
    """描述导出视图构建后的 manifest。

    字段：
    - dataset_version_id：导出来源的 DatasetVersion id。
    - export_profile：使用的导出 profile。
    - manifest_object_key：导出 manifest 的 object key。
    - split_names：导出的 split 名称列表。
    - sample_count：样本总数。
    - category_names：类别名列表。
    - extra_metadata：附加元数据。
    """

    dataset_version_id: str
    export_profile: str
    manifest_object_key: str
    split_names: tuple[str, ...]
    sample_count: int
    category_names: tuple[str, ...] = ()
    extra_metadata: dict[str, object] = field(default_factory=dict)


class YoloXExportViewBuilder(Protocol):
    """把 DatasetVersion 导出为 YOLOX 可消费训练视图的接口。"""

    def build_export_view(self, request: YoloXExportViewRequest) -> YoloXExportViewManifest:
        """构建训练导出视图。

        参数：
        - request：导出视图构建请求。

        返回：
        - 导出后的 manifest。
        """

        ...