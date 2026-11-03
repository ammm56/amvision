"""三维节点显式资源策略；None 表示未启用，不生成生产默认数值。"""

from typing import Annotated
from backend.contracts.workflows.metrology import Contract, Finite
from backend.contracts.workflows.point_cloud import PositiveCount
from pydantic import Field, model_validator
from backend.service.application.workflows.point_cloud.policy import PointCloudIoPolicy
from backend.service.application.workflows.documents.cloud_resource_blobs import (
    CloudAssetPolicy,
)


class CloudPreviewPolicy(Contract):
    """显示点、二进制、JSON 和临时分配分别限额。"""

    max_points: PositiveCount
    max_data_bytes: PositiveCount
    max_body_bytes: PositiveCount
    max_working_bytes: PositiveCount


class PreviewFilePolicy(Contract):
    """Preview 暂存磁盘预算；所有值必须显式填写，不占图片 SHM 配额。"""

    session_bytes: PositiveCount
    total_bytes: PositiveCount

    @model_validator(mode="after")
    def check_limits(self):
        """总配额不能小于单会话配额。"""
        if self.total_bytes < self.session_bytes:
            raise ValueError("Preview 文件总预算不能小于单会话预算")
        return self


class CloudRendererPolicy(Contract):
    """浏览器受管 CPU/GPU 缓冲和画布预算；误差以源坐标单位计。"""

    max_points: PositiveCount
    max_data_bytes: PositiveCount
    max_cpu_bytes: PositiveCount
    max_gpu_bytes: PositiveCount
    max_canvas_pixels: PositiveCount
    max_position_error: Annotated[Finite, Field(gt=0)]


class PointCloudExecutionPolicy(Contract):
    """完整内部策略由服务配置装配，节点参数不能覆盖它。"""

    io: PointCloudIoPolicy
    preview: CloudPreviewPolicy
    max_asset_bytes: PositiveCount
    max_archive_bytes: PositiveCount
    max_export_bytes: PositiveCount
    preview_files: PreviewFilePolicy | None = None
    renderer: CloudRendererPolicy | None = None

    def assets(self) -> CloudAssetPolicy:
        """沿既有资源服务创建同一有界读写策略。"""
        return CloudAssetPolicy(
            max_asset_bytes=self.max_asset_bytes,
            max_archive_bytes=self.max_archive_bytes,
            chunk_bytes=min(
                self.io.chunk_bytes, self.max_asset_bytes, self.max_archive_bytes
            ),
        )
