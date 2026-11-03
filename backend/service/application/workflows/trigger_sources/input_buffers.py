"""在现有 Trigger 状态机内区分图片和点云，不复制分配或停止逻辑。"""

from backend.contracts.workflows.local_shared_memory_trigger import (
    WorkflowTriggerPrepareV1,
)
from backend.contracts.workflows.point_cloud_trigger import (
    CLOUD_BUFFER_MEDIA_TYPE,
    WorkflowTriggerCloudInputV1,
    WorkflowTriggerCloudPrepareV1,
)
from backend.service.application.errors import (
    InvalidRequestError,
    ServiceConfigurationError,
)


def buffer_metadata(prepare):
    """只返回 Broker 已支持的表示属性；点云布局不冒充 image shape。"""
    if isinstance(prepare, WorkflowTriggerPrepareV1):
        return prepare.image.model_dump(exclude={"event_payload_key", "content_length"})
    if isinstance(prepare, WorkflowTriggerCloudPrepareV1):
        return dict(
            media_type=CLOUD_BUFFER_MEDIA_TYPE,
            shape=(),
            dtype=None,
            layout=None,
            pixel_format=None,
        )
    raise InvalidRequestError("未知 Trigger PREPARE 类型")


def buffer_length(prepare):
    """分配长度只取自已验证的 PREPARE。"""
    return (
        prepare.cloud.content_length
        if isinstance(prepare, WorkflowTriggerCloudPrepareV1)
        else prepare.image.content_length
    )


def input_payload(prepare, buffer_ref):
    """构造一次固定布局的输入值，不采用 REQUEST 中的替代描述。"""
    if isinstance(prepare, WorkflowTriggerCloudPrepareV1):
        from backend.service.application.workflows.point_cloud.local_array import (
            cloud_descriptor_sha256,
        )

        return prepare.event_payload_key, WorkflowTriggerCloudInputV1(
            descriptor=prepare.cloud,
            descriptor_sha256=cloud_descriptor_sha256(prepare.cloud),
            buffer_ref=buffer_ref,
        ).model_dump(mode="json")
    return prepare.image.event_payload_key, {
        "transport_kind": "buffer",
        "media_type": prepare.image.media_type,
        "buffer_ref": buffer_ref.model_dump(mode="json"),
    }


def validate_cloud_prepare(prepare, source, policy):
    """分配前核对固定的公开 binding 和显式容量，不创建等待队列。"""
    if not isinstance(prepare, WorkflowTriggerCloudPrepareV1):
        return
    if policy is None:
        raise ServiceConfigurationError("3D Metrology 未配置运行策略，不能分配点云输入")
    if prepare.cloud.content_length > min(
        policy.io.max_decoded_bytes, policy.io.max_live_array_bytes
    ):
        raise InvalidRequestError("点云输入超过显式数组预算")
    types = source.metadata.get("validated_workflow_input_payload_types", {})
    mapped = [
        binding
        for binding, rule in source.input_binding_mapping.items()
        if isinstance(rule, dict)
        and rule.get("source") == f"payload.{prepare.event_payload_key}"
    ]
    if not mapped or any(
        types.get(binding) != "point-cloud-ref.v1" for binding in mapped
    ):
        raise InvalidRequestError("点云 PREPARE 未映射到已发布的同机数组 binding")
