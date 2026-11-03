"""边界同次调试契约；不作为量测输入或普通点云资产的一部分。"""

from typing import Annotated, Literal, Self

from pydantic import Field, StrictBool, model_validator

from backend.contracts.workflows.evaluation3d import EvaluationPlane3d
from backend.contracts.workflows.metrology import Contract, Identifier, Finite
from backend.contracts.workflows.point_cloud import JsonCount, Sha256


class BoundaryDebugReference(Contract):
    """仅在当前 Scope 内可解析，节点调用身份与特征身份同时校验。"""

    format_id: Literal["amvision.boundary-debug-ref.v1"] = (
        "amvision.boundary-debug-ref.v1"
    )
    capture_id: Identifier
    run_id: Identifier
    node_id: Identifier
    invocation_id: Identifier
    observation_id: Identifier
    feature_id: Identifier
    parameters_sha256: Sha256


class DebugArray(Contract):
    """小端紧凑二进制段，offset/count 不允许由浏览器猜测。"""

    name: Identifier
    dtype: Literal["float32", "float64", "uint8", "uint64", "int64"]
    components: Annotated[int, Field(strict=True, ge=1, le=4)]
    count: JsonCount
    offset: JsonCount
    byte_length: JsonCount


class DebugBinary(Contract):
    """沿原 Preview 正文传输的有界二进制，不另开网络或资源服务。"""

    encoding: Literal["base64"] = "base64"
    checksum_algorithm: Literal["sha256"] = "sha256"
    checksum: Sha256
    content_length: JsonCount
    content: str
    fields: Annotated[tuple[DebugArray, ...], Field(max_length=48)]

    @model_validator(mode="after")
    def check_layout(self) -> Self:
        """描述符精确覆盖正文；摘要和数组内容由有界解码入口检查。"""
        widths = {"float32": 4, "float64": 8, "uint8": 1, "uint64": 8, "int64": 8}
        end, names = 0, set()
        for field in self.fields:
            width = widths[field.dtype]
            offset = (end + width - 1) // width * width
            if (
                field.name in names
                or field.offset != offset
                or field.byte_length != field.count * field.components * width
            ):
                raise ValueError("调试数组布局不一致")
            names.add(field.name)
            end = field.offset + field.byte_length
        if end != self.content_length or len(self.content) != 4 * ((end + 2) // 3):
            raise ValueError("调试正文长度不一致")
        return self


class DebugGrid(Contract):
    """实际分箱布局，U 主序；种子和分区方法来自原配方。"""

    origin: tuple[Finite, Finite]
    step: Annotated[Finite, Field(gt=0)]
    shape: tuple[
        Annotated[int, Field(strict=True, gt=0)],
        Annotated[int, Field(strict=True, gt=0)],
    ]
    seed_min: tuple[Finite, Finite]
    seed_max: tuple[Finite, Finite]
    selection: Literal["grid-connected", "distance-connected"]
    selected_component: int | None


class BoundaryDebugDisplay(Contract):
    """冻结显示与运行引用分开；失败阶段的证据不冒充有效边界。"""

    format_id: Literal["amvision.boundary-debug.v1"] = "amvision.boundary-debug.v1"
    identity: BoundaryDebugReference
    state: Literal["ready", "unavailable", "not-executed"]
    reason: Identifier | None
    failure_field: Identifier | None = None
    required_bytes: JsonCount | None = None
    stage: Literal["input", "grid", "candidates", "selection", "complete"]
    selection_complete: StrictBool
    measurement_reason: Identifier | None
    evaluation: EvaluationPlane3d | None
    grid: DebugGrid | None
    target_ids: Annotated[tuple[Identifier, ...], Field(max_length=8192)]
    data: DebugBinary | None

    @model_validator(mode="after")
    def check_state(self) -> Self:
        """部分阶段可看但不能声称选择完成；不可用时不携旧正文。"""
        if len(set(self.target_ids)) != len(self.target_ids):
            raise ValueError("调试目标 ID 重复")
        if self.state == "ready":
            if (
                self.data is None
                or self.evaluation is None
                or self.reason is not None
                or self.stage == "input"
            ):
                raise ValueError("调试成功正文不完整")
        elif self.data is not None or self.reason is None:
            raise ValueError("不可用调试不能携带正文")
        if self.selection_complete and self.stage not in {"selection", "complete"}:
            raise ValueError("未执行选择阶段不能声称选择完成")
        return self
