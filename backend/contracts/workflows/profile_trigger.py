"""扫描轮廓复用既有 LocalBuffer 握手，固定完整行表和标定。"""

from typing import Literal

from pydantic import model_validator

from backend.contracts.buffers import BufferRef
from backend.contracts.workflows.metrology import Contract, Identifier
from backend.contracts.workflows.point_cloud import Sha256
from backend.contracts.workflows.profile3d import ProfileBufferDescriptor

PROFILE_PREPARE_FORMAT = "amvision.workflow-trigger-profile-prepare.v1"
PROFILE_INPUT_FORMAT = "amvision.workflow-trigger-profile-input.v1"
PROFILE_BUFFER_MEDIA_TYPE = "application/vnd.amvision.profile-buffer"
PROFILE_PAYLOAD_TYPE = "calibrated-profiles.v1"


class WorkflowTriggerProfilePrepareV1(Contract):
    """分配前固定轮廓、原始行表、标定和目标 binding。"""

    format_id: Literal[PROFILE_PREPARE_FORMAT] = PROFILE_PREPARE_FORMAT
    trigger_source_id: Identifier
    event_id: Identifier
    event_payload_key: Identifier
    profiles: ProfileBufferDescriptor


class WorkflowTriggerProfileInputV1(Contract):
    """由平台生成且需要本次运行私有交接身份的只读输入。"""

    format_id: Literal[PROFILE_INPUT_FORMAT] = PROFILE_INPUT_FORMAT
    descriptor: ProfileBufferDescriptor
    descriptor_sha256: Sha256
    buffer_ref: BufferRef

    @model_validator(mode="after")
    def check_buffer(self):
        """轮廓不能冒充图片、写定位或另一种长度的数组。"""
        ref = self.buffer_ref
        if (
            ref.content_length != self.descriptor.content_length
            or ref.media_type != PROFILE_BUFFER_MEDIA_TYPE
            or not ref.readonly
            or ref.shape
            or any(v is not None for v in (ref.dtype, ref.layout, ref.pixel_format))
        ):
            raise ValueError("轮廓 BufferRef 与固定布局不一致")
        return self
