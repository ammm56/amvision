"""同机点云 PREPARE 与平台生成的输入定位；不改变 LocalBuffer ABI。"""

from typing import Literal

from pydantic import model_validator

from backend.contracts.buffers import BufferRef
from backend.contracts.workflows.metrology import Contract, Identifier
from backend.contracts.workflows.point_cloud import CloudBufferDescriptor, Sha256


CLOUD_PREPARE_FORMAT = "amvision.workflow-trigger-cloud-prepare.v1"
CLOUD_INPUT_FORMAT = "amvision.workflow-trigger-cloud-input.v1"
CLOUD_BUFFER_MEDIA_TYPE = "application/vnd.amvision.point-cloud-buffer"


class WorkflowTriggerCloudPrepareV1(Contract):
    """调用方只提交固定布局；定位和释放权限始终由平台分配。"""

    format_id: Literal[CLOUD_PREPARE_FORMAT] = CLOUD_PREPARE_FORMAT
    trigger_source_id: Identifier
    event_id: Identifier
    event_payload_key: Identifier
    cloud: CloudBufferDescriptor


class WorkflowTriggerCloudInputV1(Contract):
    """平台在交接后注入 binding 的只读定位，不是公开 JSON 上传入口。"""

    format_id: Literal[CLOUD_INPUT_FORMAT] = CLOUD_INPUT_FORMAT
    descriptor: CloudBufferDescriptor
    descriptor_sha256: Sha256
    buffer_ref: BufferRef

    @model_validator(mode="after")
    def check_buffer(self):
        """点云不得携带图片维度或与固定布局不同的有效载荷长度。"""
        ref = self.buffer_ref
        if (
            ref.content_length != self.descriptor.content_length
            or ref.media_type != CLOUD_BUFFER_MEDIA_TYPE
            or not ref.readonly
            or ref.shape
            or any(
                value is not None for value in (ref.dtype, ref.layout, ref.pixel_format)
            )
        ):
            raise ValueError("点云 BufferRef 与固定布局不一致")
        return self
