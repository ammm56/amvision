"""有界三维显示附件；只保存数值证据，不携点云访问引用。"""

from typing import Annotated, Literal, Self
from pydantic import Field, StrictBool, model_validator
from backend.contracts.workflows.geometry3d import (
    Point3,
    PlaneGeometry,
    RigidMatrix3d,
    Roi3d,
)
from backend.contracts.workflows.geometry3d_quality import (
    GeometryQuality,
    check_plane_metrics,
    check_frame_metrics,
)
from backend.contracts.workflows.metrology import Contract, Identifier, unique_ids
from backend.contracts.workflows.point_cloud import LengthUnit, JsonCount


class SupportBounds(Contract):
    """真实支持点的轴对齐边界，仅限制显示范围，不代表表面拓扑。"""

    min: Point3
    max: Point3

    @model_validator(mode="after")
    def check_order(self) -> Self:
        """平面允许零厚度，不接受倒置边界。"""
        if any(a > b for a, b in zip(self.min, self.max)):
            raise ValueError("支持边界倒置")
        return self


class PlaneDisplay(Contract):
    """平面显示和质量摘要，不包含运行 support 或方法权限。"""

    feature_id: Identifier
    valid: StrictBool
    reason: Identifier | None
    geometry: PlaneGeometry | None
    support_bounds: SupportBounds | None
    support_point_count: JsonCount | None
    quality: GeometryQuality


class FrameDisplay(Contract):
    """失败坐标只显示状态；有效矩阵仍明确 source/target。"""

    pose_id: Identifier
    state: Literal[
        "found", "not_found", "ambiguous", "underconstrained", "insufficient_quality"
    ]
    reason: Identifier | None
    source_frame_id: Identifier
    target_frame_id: Identifier
    transform: RigidMatrix3d | None
    quality: GeometryQuality


class GeometryPreview(Contract):
    """与显示点云同观测同空间的有限几何集合。"""

    format_id: Literal["amvision.geometry-preview.v1"] = "amvision.geometry-preview.v1"
    observation_id: Identifier
    frame_id: Identifier
    length_unit: LengthUnit
    rois: Annotated[tuple[Roi3d, ...], Field(max_length=8192)]
    planes: Annotated[tuple[PlaneDisplay, ...], Field(max_length=8192)]
    frame: FrameDisplay | None

    @model_validator(mode="after")
    def check_identity(self) -> Self:
        """拒绝错单位、跨观测、重复 ID 和旧失败矩阵。"""
        unique_ids([r.roi_id for r in self.rois], "rois")
        unique_ids([p.feature_id for p in self.planes], "planes")
        for roi in self.rois:
            if (roi.frame_id, roi.length_unit) != (self.frame_id, self.length_unit):
                raise ValueError("ROI 显示空间不一致")
        for plane in self.planes:
            check_plane_metrics(plane.quality, self.length_unit)
            if plane.valid != (plane.geometry is not None) or plane.valid != (
                plane.reason is None
            ):
                raise ValueError("平面显示有效性不一致")
            if plane.valid != plane.quality.usable:
                raise ValueError("平面显示与质量状态不一致")
            count = next(
                m for m in plane.quality.metrics.items if m.item_id == "inlier_count"
            )
            if count.value != plane.support_point_count or (
                plane.support_bounds is not None
            ) != bool(plane.support_point_count):
                raise ValueError("平面显示支持计数或边界不一致")
            if plane.quality.metrics.observation_id != self.observation_id:
                raise ValueError("平面显示观测不一致")
        if self.frame:
            frame = self.frame
            check_frame_metrics(frame.quality)
            if (frame.state == "found") != frame.quality.usable:
                raise ValueError("坐标显示与质量状态不一致")
            if self.frame_id not in (frame.source_frame_id, frame.target_frame_id):
                raise ValueError("坐标显示空间不一致")
            if frame.quality.metrics.observation_id != self.observation_id:
                raise ValueError("坐标显示观测不一致")
            if (frame.state == "found") != (frame.transform is not None) or (
                frame.state == "found"
            ) != (frame.reason is None):
                raise ValueError("坐标显示状态不一致")
            if frame.transform and (
                frame.transform.observation_id,
                frame.transform.length_unit,
                frame.transform.source_frame_id,
                frame.transform.target_frame_id,
            ) != (
                self.observation_id,
                self.length_unit,
                frame.source_frame_id,
                frame.target_frame_id,
            ):
                raise ValueError("坐标显示变换身份不一致")
        return self
