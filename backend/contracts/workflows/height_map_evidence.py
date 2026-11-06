"""高度图持久证据与固定数组布局；附属于实际参与计算的点云资产。"""

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from backend.contracts.workflows.height_map3d import HeightMapParameters, PoseGridFrame
from backend.contracts.workflows.metrology import Contract, Finite
from backend.contracts.workflows.point_cloud import JsonCount
from backend.contracts.workflows.pose3d_operations import PoseEvidence


class HeightMapEvidence(Contract):
    """不含运行句柄；位姿是本次计算证据，不授权后续运行复用历史 Pose。"""

    format_id: Literal["amvision.height-map.v1"] = "amvision.height-map.v1"
    parameters: HeightMapParameters
    pose: PoseEvidence | None
    input_count: JsonCount
    vertex_kind: Literal["source", "generated"]
    dtype: Literal["float32", "float64"]
    outside_count: JsonCount
    occupied_count: JsonCount
    max_rounding_error: Annotated[Finite, Field(ge=0)]

    @model_validator(mode="after")
    def check_counts(self) -> Self:
        """方法、位姿、计数与贡献关系必须一致，空格不是零高度。"""
        frame = self.parameters.frame
        if isinstance(frame, PoseGridFrame):
            if (
                self.pose is None
                or self.pose.state != "found"
                or (self.pose.pose_id, self.pose.target_frame_id, self.pose.length_unit)
                != (frame.pose_id, frame.target_frame_id, self.parameters.length_unit)
            ):
                raise ValueError("高度图位姿证据不一致")
        elif self.pose is not None:
            raise ValueError("当前坐标高度图不能携带 Pose")
        members = self.input_count - self.outside_count
        if members < 0 or self.occupied_count > min(
            members, self.parameters.cell_count()
        ):
            raise ValueError("高度图格数或贡献记录数不一致")
        if (members == 0) != (self.occupied_count == 0):
            raise ValueError("高度图非空格必须有贡献记录")
        return self

    def layout(self):
        """LE 连续数组，顺序固定；生成点没有唯一原始行号。"""
        cells = self.parameters.cell_count()
        members = self.input_count - self.outside_count
        result = [
            (name, self.dtype, cells) for name in ("heights", "minimum", "maximum")
        ]
        result += [
            ("counts", "uint64", cells),
            ("member_offsets", "uint64", cells + 1),
            ("input_rows", "uint64", members),
        ]
        if self.vertex_kind == "source":
            result.append(("source_rows", "uint64", members))
        return tuple(result)

    def byte_length(self):
        """精确长度包含所有空格与成员，不根据压缩比估计容量。"""
        return sum(
            count * (4 if dtype == "float32" else 8)
            for _, dtype, count in self.layout()
        )
