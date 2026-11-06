"""标定栅格沿既有 LocalBuffer 握手传递，不使用普通图片协议。"""

from typing import Literal

from pydantic import model_validator

from backend.contracts.buffers import BufferRef
from backend.contracts.workflows.metrology import Contract, Identifier
from backend.contracts.workflows.point_cloud import Sha256
from backend.contracts.workflows.raster3d import RasterBufferDescriptor

RASTER_PREPARE_FORMAT = "amvision.workflow-trigger-raster-prepare.v1"
RASTER_INPUT_FORMAT = "amvision.workflow-trigger-raster-input.v1"
RASTER_BUFFER_MEDIA_TYPE = "application/vnd.amvision.raster-buffer"
RASTER_PAYLOAD_TYPE = "calibrated-raster.v1"


class WorkflowTriggerRasterPrepareV1(Contract):
    """完整布局与标定在分配前验证；REQUEST 不能替换。"""

    format_id: Literal[RASTER_PREPARE_FORMAT] = RASTER_PREPARE_FORMAT
    trigger_source_id: Identifier
    event_id: Identifier
    event_payload_key: Identifier
    raster: RasterBufferDescriptor


class WorkflowTriggerRasterInputV1(Contract):
    """平台生成的只读定位，必须同时具有当前运行的私有交接身份。"""

    format_id: Literal[RASTER_INPUT_FORMAT] = RASTER_INPUT_FORMAT
    descriptor: RasterBufferDescriptor
    descriptor_sha256: Sha256
    buffer_ref: BufferRef

    @model_validator(mode="after")
    def check_buffer(self):
        """拒绝长度不同、可写定位和图片属性，不隐式转换标量 dtype。"""
        ref = self.buffer_ref
        if (
            ref.content_length != self.descriptor.content_length
            or ref.media_type != RASTER_BUFFER_MEDIA_TYPE
            or not ref.readonly
            or ref.shape
            or any(
                value is not None for value in (ref.dtype, ref.layout, ref.pixel_format)
            )
        ):
            raise ValueError("标定栅格 BufferRef 与固定布局不一致")
        return self
