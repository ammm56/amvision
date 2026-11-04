"""计算法向的字段与来源契约；外部 normals 不自动获得计算质量声明。"""

from enum import IntEnum
from hashlib import sha256
from typing import Annotated, Literal

from pydantic import Field, model_validator

from backend.contracts.workflows.cloud_normals import (
    EstimateNormalsParameters,
    NormalOrientation,
)
from backend.contracts.workflows.metrology import Contract, Identifier
from backend.contracts.workflows.point_cloud import (
    CloudField,
    LengthUnit,
    PositiveCount,
    Sha256,
    canonical_cloud_json,
)


class NormalReason(IntEnum):
    """逐点固定原因，轴有效与有符号方向分别声明。"""

    VALID = 0
    INSUFFICIENT_SUPPORT = 1
    DEGENERATE_SUPPORT = 2
    NUMERIC_FAILURE = 3
    QUALITY_FAILED = 4
    ORIENTATION_AMBIGUOUS = 5


NORMAL_STATES = ("normal_valid", "normal_oriented", "normal_reason")
NORMAL_DIAGNOSTICS = (
    "normal_neighbors",
    "normal_rms",
    "normal_gap",
    "normal_variation",
)
NORMAL_FIELDS = ("normals", *NORMAL_STATES, *NORMAL_DIAGNOSTICS)


class EstimateNormalsMethod(Contract):
    """原估计参数不可变；后续变换不重写原计算定义。"""

    method_id: Literal["estimate-normals"]
    method_version: Annotated[int, Field(strict=True, ge=1, le=1)]
    parameters: EstimateNormalsParameters
    parameters_sha256: Sha256

    @model_validator(mode="after")
    def check_digest(self):
        """独立持久保存时同样核对参数正文。"""
        if (
            sha256(
                canonical_cloud_json(self.parameters.model_dump(mode="json"))
            ).hexdigest()
            != self.parameters_sha256
        ):
            raise ValueError("法向方法参数摘要不一致")
        return self


class NormalSupport(Contract):
    """曾参与估计的运行身份，仅追溯，不授予历史数组读取权。"""

    run_id: Identifier
    observation_id: Identifier
    cloud_id: Identifier
    revision: PositiveCount


class CloudNormalInfo(Contract):
    """原计算证据和当前空间定义，裁剪不意味着重新估计。"""

    method: EstimateNormalsMethod
    support: NormalSupport
    frame_id: Identifier
    length_unit: LengthUnit
    orientation: NormalOrientation

    def fields(self, dtype):
        """位置精度决定法向/诊断浮点位宽，状态字段独立于位置 validity。"""
        result = [
            CloudField(
                name="normals", semantic="normal", dtype=dtype, components=3, unit="1"
            )
        ]
        result.extend(
            CloudField(
                name=name, semantic="scalar", dtype="uint8", components=1, unit=None
            )
            for name in NORMAL_STATES
        )
        if self.method.parameters.diagnostics:
            result.extend(
                CloudField(
                    name=name,
                    semantic="scalar",
                    dtype="uint32" if name == "normal_neighbors" else dtype,
                    components=1,
                    unit=self.length_unit if name == "normal_rms" else None,
                )
                for name in NORMAL_DIAGNOSTICS
            )
        return tuple(result)

    def check_fields(self, fields, spatial, *, generated):
        """不允许漏状态、窄化精度或混入伪造的生成点属性。"""
        by_name = {field.name: field for field in fields}
        if "positions" not in by_name or (self.frame_id, self.length_unit) != (
            spatial.frame_id,
            spatial.length_unit,
        ):
            raise ValueError("法向计算说明与当前点云空间不一致")
        expected = {
            field.name: field for field in self.fields(by_name["positions"].dtype)
        }
        actual = {
            name: field for name, field in by_name.items() if name in NORMAL_FIELDS
        }
        if set(actual) != set(expected) or any(
            any(
                getattr(actual[name], key) != getattr(field, key)
                for key in ("semantic", "dtype", "components", "unit")
            )
            for name, field in expected.items()
        ):
            raise ValueError("计算法向字段或状态不完整")
        if generated and set(by_name) != {"positions", *expected}:
            raise ValueError("生成点只能携带坐标及明确计算的法向字段")
