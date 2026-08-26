"""Workflow Trigger 输出选择、图片规范化与 cleanup 前 owner handoff。"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from time import monotonic_ns
from typing import Literal
from zlib import crc32

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.contracts.buffers import BufferRef, FrameRef
from backend.contracts.buffers.lease_ownership import LeaseOwnershipReceipt
from backend.nodes.runtime_support import (
    IMAGE_TRANSPORT_BUFFER,
    IMAGE_TRANSPORT_FRAME,
    IMAGE_TRANSPORT_LOCAL_PATH,
    IMAGE_TRANSPORT_MEMORY,
    IMAGE_TRANSPORT_STORAGE,
    ExecutionImageRegistry,
    build_storage_image_payload,
    require_image_payload,
)
from backend.service.application.errors import (
    EphemeralImageRefInJsonResultError,
    InvalidRequestError,
    ServiceConfigurationError,
)
from backend.service.application.images.image_matrix import (
    normalize_image_payload_metadata,
)
from backend.service.application.workflows.execution_cleanup import (
    WORKFLOW_EXECUTION_CLEANUP_KIND_LOCAL_BUFFER_LEASE,
    list_registered_execution_cleanups,
    register_local_buffer_lease_cleanup,
)
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)


WORKFLOW_OUTPUT_DELIVERY_PLAN_METADATA_KEY = "workflow_output_delivery_plan"
WORKFLOW_OUTPUT_DELIVERY_PLAN_FORMAT = "amvision.workflow-output-delivery-plan.v1"
TRIGGER_RESPONSE_PLAN_METADATA_KEY = "trigger_response_plan"
TRIGGER_RESPONSE_PLAN_FORMAT = "amvision.trigger-response-plan.v1"
PREPARED_TRIGGER_RESULT_FORMAT = "amvision.prepared-trigger-result.v1"

AttachmentDeliveryKind = Literal["none", "local-buffer", "zeromq-frame", "object-store"]


class TriggerResponseBindingPlan(BaseModel):
    """固定一个公开输出 binding 的 payload 类型和交付分类。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    binding_id: str
    payload_type_id: str
    result_kind: Literal["json", "image-attachment"]

    @model_validator(mode="after")
    def validate_binding(self) -> TriggerResponseBindingPlan:
        """拒绝空 binding identity，并固定图片 payload 分类。"""

        if not self.binding_id.strip() or not self.payload_type_id.strip():
            raise ValueError("Trigger response binding identity 不能为空")
        expected_kind = (
            "image-attachment"
            if self.payload_type_id in {"image-ref.v1", "image-refs.v1"}
            else "json"
        )
        if self.result_kind != expected_kind:
            raise ValueError("Trigger response binding result_kind 与 payload type 不一致")
        return self


class TriggerResponsePlan(BaseModel):
    """固定 Trigger 配置、Runtime revision 与公开输出契约的不可变响应计划。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    format_id: Literal[TRIGGER_RESPONSE_PLAN_FORMAT] = TRIGGER_RESPONSE_PLAN_FORMAT
    trigger_source_id: str
    trigger_kind: str
    workflow_runtime_id: str
    workflow_runtime_revision_id: str
    workflow_app_version_id: str
    workflow_runtime_generation: int = Field(ge=1)
    expected_snapshot_fingerprint: str
    contract_fingerprint: str
    plan_generation: int = Field(ge=1)
    plan_fingerprint: str
    submit_mode: Literal["sync", "async"]
    result_mode: Literal["sync-reply", "accepted-then-query", "event-only"]
    ack_policy: Literal["ack-after-run-created", "ack-after-run-finished"]
    reply_timeout_seconds: int | None = Field(default=None, gt=0)
    response_ack_timeout_seconds: float | None = Field(default=None, gt=0)
    result_bindings: tuple[TriggerResponseBindingPlan, ...] = ()
    attachment_delivery_kind: AttachmentDeliveryKind = "none"
    adapter_capability_revision: str

    @model_validator(mode="after")
    def validate_plan(self) -> TriggerResponsePlan:
        """校验不可变 identity、交付能力和 fingerprint。"""

        for field_name in (
            "trigger_source_id",
            "trigger_kind",
            "workflow_runtime_id",
            "workflow_runtime_revision_id",
            "workflow_app_version_id",
            "expected_snapshot_fingerprint",
            "contract_fingerprint",
            "plan_fingerprint",
            "adapter_capability_revision",
        ):
            if not str(getattr(self, field_name)).strip():
                raise ValueError(f"{field_name} 不能为空")
        binding_ids = tuple(item.binding_id for item in self.result_bindings)
        if len(binding_ids) != len(set(binding_ids)):
            raise ValueError("Trigger response plan binding 不能重复")
        has_images = any(
            item.result_kind == "image-attachment" for item in self.result_bindings
        )
        if self.result_mode == "event-only":
            if self.result_bindings or self.attachment_delivery_kind != "none":
                raise ValueError("event-only response plan 不能选择结果")
        elif self.result_mode == "accepted-then-query":
            expected_delivery = "object-store" if has_images else "none"
            if self.attachment_delivery_kind != expected_delivery:
                raise ValueError("accepted-then-query 图片必须使用 ObjectStore")
        elif has_images and self.attachment_delivery_kind == "none":
            raise ValueError("同步图片结果缺少 attachment delivery capability")
        elif not has_images and self.attachment_delivery_kind != "none":
            raise ValueError("没有图片 binding 时不能配置 attachment delivery")
        if self.trigger_kind == "local-shared-memory":
            if self.submit_mode != "sync" or self.reply_timeout_seconds is None:
                raise ValueError(
                    "local-shared-memory response plan 必须固定同步请求 timeout"
                )
            if self.response_ack_timeout_seconds is None:
                raise ValueError(
                    "local-shared-memory response plan 必须固定 ACK timeout"
                )
        elif self.response_ack_timeout_seconds is not None:
            raise ValueError(
                "非 local-shared-memory response plan 不能携带私有 ACK timeout"
            )
        expected_fingerprint = _build_trigger_response_plan_fingerprint(
            self.model_dump(mode="json", exclude={"plan_fingerprint"})
        )
        if self.plan_fingerprint != expected_fingerprint:
            raise ValueError("Trigger response plan fingerprint 不匹配")
        return self


def build_trigger_response_plan(
    *,
    trigger_source_id: str,
    trigger_kind: str,
    workflow_runtime_id: str,
    workflow_runtime_revision_id: str,
    workflow_app_version_id: str,
    workflow_runtime_generation: int,
    expected_snapshot_fingerprint: str,
    contract_fingerprint: str,
    submit_mode: str,
    result_mode: str,
    ack_policy: str,
    reply_timeout_seconds: int | None,
    response_ack_timeout_seconds: float | None = None,
    selected_output_payload_types: dict[str, str],
    previous_plan: object = None,
) -> TriggerResponsePlan:
    """按已发布公开契约构造响应计划，并仅在内容变化时推进 generation。"""

    bindings = tuple(
        TriggerResponseBindingPlan(
            binding_id=binding_id,
            payload_type_id=payload_type_id,
            result_kind=(
                "image-attachment"
                if payload_type_id in {"image-ref.v1", "image-refs.v1"}
                else "json"
            ),
        )
        for binding_id, payload_type_id in selected_output_payload_types.items()
    )
    has_images = any(item.result_kind == "image-attachment" for item in bindings)
    delivery_kind, capability_revision = _resolve_current_response_capability(
        trigger_kind=trigger_kind,
        result_mode=result_mode,
        has_images=has_images,
    )
    previous = _try_parse_trigger_response_plan(previous_plan)
    candidate: dict[str, object] = {
        "format_id": TRIGGER_RESPONSE_PLAN_FORMAT,
        "trigger_source_id": trigger_source_id,
        "trigger_kind": trigger_kind,
        "workflow_runtime_id": workflow_runtime_id,
        "workflow_runtime_revision_id": workflow_runtime_revision_id,
        "workflow_app_version_id": workflow_app_version_id,
        "workflow_runtime_generation": workflow_runtime_generation,
        "expected_snapshot_fingerprint": expected_snapshot_fingerprint,
        "contract_fingerprint": contract_fingerprint,
        "plan_generation": 1,
        "submit_mode": submit_mode,
        "result_mode": result_mode,
        "ack_policy": ack_policy,
        "reply_timeout_seconds": reply_timeout_seconds,
        "response_ack_timeout_seconds": response_ack_timeout_seconds,
        "result_bindings": [item.model_dump(mode="json") for item in bindings],
        "attachment_delivery_kind": delivery_kind,
        "adapter_capability_revision": capability_revision,
    }
    comparable = dict(candidate)
    comparable.pop("plan_generation")
    previous_comparable = (
        previous.model_dump(
            mode="json",
            exclude={"plan_generation", "plan_fingerprint"},
        )
        if previous is not None
        else None
    )
    generation = (
        previous.plan_generation
        if previous_comparable == comparable
        else ((previous.plan_generation + 1) if previous is not None else 1)
    )
    candidate["plan_generation"] = generation
    candidate["plan_fingerprint"] = _build_trigger_response_plan_fingerprint(
        candidate
    )
    return TriggerResponsePlan.model_validate(candidate)


def build_workflow_output_delivery_plan(
    response_plan: TriggerResponsePlan,
    *,
    response_owner_kind: str | None = None,
    response_owner_id: str | None = None,
    deadline_ns: int | None = None,
) -> WorkflowOutputDeliveryPlan:
    """从固定 response plan 派生 Worker cleanup 前使用的最小计划。"""

    delivery_kind = response_plan.attachment_delivery_kind
    if delivery_kind == "zeromq-frame":
        # ZeroMQ frame 仍需先由 LocalBuffer 固定图片生命周期；adapter 只借用 view。
        delivery_kind = "local-buffer"
    if delivery_kind != "local-buffer":
        response_owner_kind = None
        response_owner_id = None
        deadline_ns = None
    return WorkflowOutputDeliveryPlan(
        result_mode=response_plan.result_mode,
        result_bindings=tuple(
            item.binding_id for item in response_plan.result_bindings
        ),
        attachment_delivery_kind=delivery_kind,
        response_owner_kind=response_owner_kind,
        response_owner_id=response_owner_id,
        deadline_ns=deadline_ns,
    )


def require_trigger_response_plan(metadata: dict[str, object]) -> TriggerResponsePlan:
    """从 TriggerSource metadata 读取并严格校验固定响应计划。"""

    raw_plan = metadata.get(TRIGGER_RESPONSE_PLAN_METADATA_KEY)
    if not isinstance(raw_plan, dict):
        raise ServiceConfigurationError("TriggerSource 缺少固定 TriggerResponsePlan")
    return TriggerResponsePlan.model_validate(raw_plan)


class WorkflowOutputDeliveryPlan(BaseModel):
    """固定一次 Run 在 worker cleanup 前必须完成的输出交付规则。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    format_id: Literal[WORKFLOW_OUTPUT_DELIVERY_PLAN_FORMAT] = (
        WORKFLOW_OUTPUT_DELIVERY_PLAN_FORMAT
    )
    result_mode: Literal["sync-reply", "accepted-then-query", "event-only"]
    result_bindings: tuple[str, ...] = ()
    attachment_delivery_kind: AttachmentDeliveryKind = "none"
    response_owner_kind: str | None = None
    response_owner_id: str | None = None
    deadline_ns: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_plan(self) -> WorkflowOutputDeliveryPlan:
        """校验 binding 唯一性和 LocalBuffer owner 三元组。"""

        normalized = tuple(item.strip() for item in self.result_bindings)
        if any(not item for item in normalized):
            raise ValueError("result_bindings 不能为空字符串")
        if len(normalized) != len(set(normalized)):
            raise ValueError("result_bindings 不能重复")
        if self.result_mode == "event-only" and self.result_bindings:
            raise ValueError("event-only 输出计划不能选择结果 binding")
        if (
            self.result_mode == "accepted-then-query"
            and self.attachment_delivery_kind != "object-store"
        ):
            raise ValueError("accepted-then-query 输出计划必须使用 ObjectStore")
        owner_values = (
            self.response_owner_kind,
            self.response_owner_id,
            self.deadline_ns,
        )
        if self.attachment_delivery_kind == "local-buffer":
            if not all(owner_values):
                raise ValueError("LocalBuffer 输出计划缺少 response owner 或 deadline")
        elif any(value is not None for value in owner_values):
            raise ValueError("非 LocalBuffer 输出计划不能携带 response owner")
        return self


class PreparedLogicalAttachment(BaseModel):
    """描述公开 binding/item 到物理图片 payload 的有序映射。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    attachment_id: str
    binding_id: str
    item_index: int = Field(ge=0)
    binding_payload_type_id: Literal["image-ref.v1", "image-refs.v1"]
    payload_type_id: Literal["image-ref.v1"] = "image-ref.v1"
    payload_id: str


class PreparedPhysicalPayload(BaseModel):
    """描述 worker 已固定生命周期的一份去重物理图片表示。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    payload_id: str
    delivery_kind: Literal["local-buffer", "object-store"]
    media_type: str
    content_length: int = Field(gt=0)
    checksum_algorithm: Literal["crc32", "sha256"]
    checksum: str
    width: int | None = Field(default=None, gt=0)
    height: int | None = Field(default=None, gt=0)
    shape: tuple[int, ...] = ()
    dtype: str | None = None
    layout: str | None = None
    pixel_format: str | None = None
    buffer_ref: dict[str, object] | None = None
    ownership_receipt: dict[str, object] | None = None
    object_locator: dict[str, object] | None = None

    @model_validator(mode="after")
    def validate_locator(self) -> PreparedPhysicalPayload:
        """确保物理 payload 只携带当前 delivery kind 的 locator。"""

        if self.delivery_kind == "local-buffer":
            if self.buffer_ref is None or self.ownership_receipt is None:
                raise ValueError("LocalBuffer payload 缺少 ref 或 ownership receipt")
            if self.object_locator is not None:
                raise ValueError("LocalBuffer payload 不能携带 object locator")
        elif self.object_locator is None:
            raise ValueError("ObjectStore payload 缺少 locator")
        return self


class PreparedTriggerResult(BaseModel):
    """worker 返回 adapter 前的协议中立结构化结果与图片附件。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    format_id: Literal[PREPARED_TRIGGER_RESULT_FORMAT] = PREPARED_TRIGGER_RESULT_FORMAT
    selected_results: dict[str, object] = Field(default_factory=dict)
    attachments: tuple[PreparedLogicalAttachment, ...] = ()
    physical_payloads: tuple[PreparedPhysicalPayload, ...] = ()


def build_public_prepared_result_payload(
    prepared_result: PreparedTriggerResult,
) -> dict[str, object]:
    """移除 owner/guard 私有字段，只公开图片定位与表示信息。"""

    def build_physical_payload(item: PreparedPhysicalPayload) -> dict[str, object]:
        """构造单个公开物理 payload，不泄露 owner handoff receipt。"""

        return {
            "payload_id": item.payload_id,
            "delivery_kind": item.delivery_kind,
            "media_type": item.media_type,
            "content_length": item.content_length,
            "checksum_algorithm": item.checksum_algorithm,
            "checksum": item.checksum,
            "width": item.width,
            "height": item.height,
            "shape": list(item.shape),
            "dtype": item.dtype,
            "layout": item.layout,
            "pixel_format": item.pixel_format,
            "buffer_ref": dict(item.buffer_ref or {}),
            "object_locator": dict(item.object_locator or {}),
        }

    return {
        "results": dict(prepared_result.selected_results),
        "attachments": [item.model_dump(mode="json") for item in prepared_result.attachments],
        "payloads": [
            build_physical_payload(item)
            for item in prepared_result.physical_payloads
        ],
    }


def list_prepared_result_ownership_receipts(
    prepared_result: PreparedTriggerResult,
) -> tuple[LeaseOwnershipReceipt, ...]:
    """读取只供 backend 生命周期管理使用的 output receipt。"""

    return tuple(
        LeaseOwnershipReceipt.model_validate(item.ownership_receipt)
        for item in prepared_result.physical_payloads
        if isinstance(item.ownership_receipt, dict)
    )


@dataclass(frozen=True)
class _PendingPhysicalPayload:
    """transfer 前的内部图片表示。"""

    payload_id: str
    buffer_ref: BufferRef
    receipt: LeaseOwnershipReceipt
    media_type: str
    checksum: str
    width: int | None = None
    height: int | None = None
    shape: tuple[int, ...] = ()
    dtype: str | None = None
    layout: str | None = None
    pixel_format: str | None = None


@dataclass(frozen=True)
class _PreparedObjectPayload:
    """描述已发布的不可变 ObjectStore 图片。"""

    payload_id: str
    media_type: str
    content_length: int
    checksum_algorithm: str
    checksum: str
    object_locator: dict[str, object]
    width: int | None = None
    height: int | None = None
    shape: tuple[int, ...] = ()
    dtype: str | None = None
    layout: str | None = None
    pixel_format: str | None = None


def prepare_trigger_result_before_cleanup(
    *,
    outputs: dict[str, object],
    output_payload_types: dict[str, str],
    execution_metadata: dict[str, object],
    dataset_storage: LocalDatasetStorage,
    local_buffer_client: object | None,
) -> PreparedTriggerResult | None:
    """按固定计划选择输出，并在 Run cleanup 前原子 handoff 图片。"""

    raw_plan = execution_metadata.get(WORKFLOW_OUTPUT_DELIVERY_PLAN_METADATA_KEY)
    if raw_plan is None:
        return None
    plan = WorkflowOutputDeliveryPlan.model_validate(raw_plan)
    if plan.result_mode == "event-only":
        return PreparedTriggerResult()
    missing_bindings = [item for item in plan.result_bindings if item not in outputs]
    if missing_bindings:
        raise InvalidRequestError(
            "Workflow Trigger 选择的结果 binding 不存在",
            details={"missing_output_binding_ids": missing_bindings},
        )

    selected_results: dict[str, object] = {}
    attachments: list[PreparedLogicalAttachment] = []
    pending_payloads: list[_PendingPhysicalPayload] = []
    object_payloads: list[_PreparedObjectPayload] = []
    physical_index: dict[tuple[object, ...], str] = {}
    receipt_index = _build_receipt_index(execution_metadata)
    image_bindings: list[
        tuple[str, str, tuple[dict[str, object], ...]]
    ] = []

    for binding_id in plan.result_bindings:
        payload_type_id = output_payload_types.get(binding_id)
        value = outputs[binding_id]
        if payload_type_id == "image-ref.v1":
            image_items = (require_image_payload(value),)
        elif payload_type_id == "image-refs.v1":
            image_items = _require_image_refs_items(value, binding_id=binding_id)
        else:
            _reject_ephemeral_refs(value, binding_id=binding_id)
            selected_results[binding_id] = value
            continue
        image_bindings.append((binding_id, payload_type_id, image_items))

    if image_bindings and plan.attachment_delivery_kind not in {
        "local-buffer",
        "object-store",
    }:
        raise InvalidRequestError(
            "当前 Trigger 不支持选择图片结果 binding",
            details={
                "binding_ids": [item[0] for item in image_bindings],
                "attachment_delivery_kind": plan.attachment_delivery_kind,
            },
        )
    if (
        image_bindings
        and plan.attachment_delivery_kind == "local-buffer"
        and local_buffer_client is None
    ):
        raise ServiceConfigurationError("Workflow 图片输出缺少 LocalBufferBroker client")

    # 所有 binding 和 payload 先完成结构校验，再开始 lease 分配或对象发布。
    for binding_id, payload_type_id, image_items in image_bindings:
        for item_index, image_payload in enumerate(image_items):
            identity = _physical_image_identity(image_payload)
            payload_id = physical_index.get(identity)
            if payload_id is None:
                payload_id = f"payload-{len(physical_index)}"
                if plan.attachment_delivery_kind == "local-buffer":
                    pending_payloads.append(
                        _prepare_local_buffer_payload(
                            payload_id=payload_id,
                            image_payload=image_payload,
                            execution_metadata=execution_metadata,
                            dataset_storage=dataset_storage,
                            local_buffer_client=local_buffer_client,
                            receipt_index=receipt_index,
                            deadline_ns=int(
                                plan.deadline_ns
                                or monotonic_ns() + 1_000_000_000
                            ),
                        )
                    )
                else:
                    object_payloads.append(
                        _prepare_object_store_payload(
                            payload_id=payload_id,
                            image_payload=image_payload,
                            execution_metadata=execution_metadata,
                            dataset_storage=dataset_storage,
                            local_buffer_client=local_buffer_client,
                        )
                    )
                physical_index[identity] = payload_id
            attachments.append(
                PreparedLogicalAttachment(
                    attachment_id=f"{binding_id}:{item_index}",
                    binding_id=binding_id,
                    item_index=item_index,
                    binding_payload_type_id=payload_type_id,
                    payload_id=payload_id,
                )
            )

    transferred_receipts: tuple[LeaseOwnershipReceipt, ...] = ()
    if pending_payloads:
        transfer = getattr(local_buffer_client, "transfer_lease_ownership", None)
        if not callable(transfer):
            raise ServiceConfigurationError("LocalBufferBroker client 不支持 output handoff")
        transferred_receipts = tuple(
            transfer(
                receipts=tuple(item.receipt for item in pending_payloads),
                new_owner_kind=str(plan.response_owner_kind),
                new_owner_id=str(plan.response_owner_id),
                deadline_ns=int(plan.deadline_ns),
            )
        )
        if len(transferred_receipts) != len(pending_payloads):
            raise ServiceConfigurationError("LocalBufferBroker output handoff 返回数量不一致")
    physical_payloads = [
        PreparedPhysicalPayload(
            payload_id=pending.payload_id,
            delivery_kind="local-buffer",
            media_type=pending.media_type,
            content_length=pending.buffer_ref.content_length,
            checksum_algorithm="crc32",
            checksum=pending.checksum,
            width=pending.width,
            height=pending.height,
            shape=pending.shape,
            dtype=pending.dtype,
            layout=pending.layout,
            pixel_format=pending.pixel_format,
            buffer_ref=pending.buffer_ref.model_dump(mode="json"),
            ownership_receipt=receipt.model_dump(mode="json"),
        )
        for pending, receipt in zip(pending_payloads, transferred_receipts, strict=True)
    ]
    physical_payloads.extend(
        PreparedPhysicalPayload(
            payload_id=item.payload_id,
            delivery_kind="object-store",
            media_type=item.media_type,
            content_length=item.content_length,
            checksum_algorithm=item.checksum_algorithm,
            checksum=item.checksum,
            width=item.width,
            height=item.height,
            shape=item.shape,
            dtype=item.dtype,
            layout=item.layout,
            pixel_format=item.pixel_format,
            object_locator=item.object_locator,
        )
        for item in object_payloads
    )
    return PreparedTriggerResult(
        selected_results=selected_results,
        attachments=tuple(attachments),
        physical_payloads=tuple(physical_payloads),
    )


def build_prepared_result_outputs(
    prepared_result: PreparedTriggerResult,
) -> dict[str, object]:
    """把 prepared 结果恢复为只含稳定 locator 的公开 Workflow outputs。"""

    outputs = dict(prepared_result.selected_results)
    payloads = {item.payload_id: item for item in prepared_result.physical_payloads}
    grouped: dict[
        str, tuple[str, list[tuple[int, dict[str, object]]]]
    ] = {}
    for attachment in prepared_result.attachments:
        physical = payloads.get(attachment.payload_id)
        if physical is None:
            raise ServiceConfigurationError(
                "PreparedTriggerResult attachment 引用了不存在的 payload",
                details={"payload_id": attachment.payload_id},
            )
        payload_type_id, items = grouped.setdefault(
            attachment.binding_id,
            (attachment.binding_payload_type_id, []),
        )
        if payload_type_id != attachment.binding_payload_type_id:
            raise ServiceConfigurationError(
                "PreparedTriggerResult binding payload type 不一致",
                details={"binding_id": attachment.binding_id},
            )
        items.append(
            (attachment.item_index, _build_stable_image_ref(physical))
        )
    for binding_id, (payload_type_id, items) in grouped.items():
        ordered = [item for _index, item in sorted(items, key=lambda pair: pair[0])]
        outputs[binding_id] = (
            ordered[0] if payload_type_id == "image-ref.v1" else {"items": ordered}
        )
    return outputs


def _build_receipt_index(
    execution_metadata: dict[str, object],
) -> dict[str, LeaseOwnershipReceipt]:
    """读取当前 Run cleanup 中完整、可 CAS handoff 的 receipt。"""

    result: dict[str, LeaseOwnershipReceipt] = {}
    for cleanup in list_registered_execution_cleanups(execution_metadata):
        if cleanup.resource_kind != WORKFLOW_EXECUTION_CLEANUP_KIND_LOCAL_BUFFER_LEASE:
            continue
        raw_receipt = cleanup.metadata.get("ownership_receipt")
        if not isinstance(raw_receipt, dict):
            continue
        receipt = LeaseOwnershipReceipt.model_validate(raw_receipt)
        result[receipt.lease_id] = receipt
    return result


def _require_image_refs_items(
    value: object,
    *,
    binding_id: str,
) -> tuple[dict[str, object], ...]:
    """只读取 image-refs.v1.items，不隐式提升 source_image。"""

    if not isinstance(value, dict) or not isinstance(value.get("items"), list):
        raise InvalidRequestError(
            "image-refs.v1 结果要求 items 为数组",
            details={"binding_id": binding_id},
        )
    return tuple(require_image_payload(item) for item in value["items"])


def _physical_image_identity(
    image_payload: dict[str, object],
) -> tuple[object, ...]:
    """按完整物理表示 identity 去重，不以 checksum 推断所有权。"""

    kind = str(image_payload["transport_kind"])
    if kind == IMAGE_TRANSPORT_BUFFER:
        ref = BufferRef.model_validate(image_payload["buffer_ref"])
        return (
            kind,
            ref.arena_id,
            ref.broker_epoch,
            ref.descriptor_index,
            ref.descriptor_generation,
            ref.lease_id,
            ref.buffer_id,
            ref.offset,
            ref.content_length,
            ref.allocation_capacity_bytes,
            ref.media_type,
            ref.shape,
            ref.dtype,
            ref.layout,
            ref.pixel_format,
        )
    if kind == IMAGE_TRANSPORT_FRAME:
        ref = FrameRef.model_validate(image_payload["frame_ref"])
        return (
            kind,
            ref.arena_id,
            ref.broker_epoch,
            ref.descriptor_index,
            ref.descriptor_generation,
            ref.stream_id,
            ref.sequence_id,
            ref.buffer_id,
            ref.offset,
            ref.content_length,
            ref.allocation_capacity_bytes,
        )
    if kind == IMAGE_TRANSPORT_MEMORY:
        return (kind, str(image_payload["image_handle"]))
    if kind == IMAGE_TRANSPORT_STORAGE:
        return (kind, str(image_payload["object_key"]), str(image_payload["media_type"]))
    return (kind, str(image_payload["local_path"]), str(image_payload["media_type"]))


def _prepare_local_buffer_payload(
    *,
    payload_id: str,
    image_payload: dict[str, object],
    execution_metadata: dict[str, object],
    dataset_storage: LocalDatasetStorage,
    local_buffer_client: object,
    receipt_index: dict[str, LeaseOwnershipReceipt],
    deadline_ns: int,
) -> _PendingPhysicalPayload:
    """优先 handoff 当前 Run BufferRef；其余来源只物化一次 output lease。"""

    metadata = normalize_image_payload_metadata(image_payload)
    if image_payload["transport_kind"] == IMAGE_TRANSPORT_BUFFER:
        ref = BufferRef.model_validate(image_payload["buffer_ref"])
        receipt = receipt_index.get(ref.lease_id)
        if receipt is not None and _receipt_matches_buffer_ref(receipt, ref):
            return _PendingPhysicalPayload(
                payload_id=payload_id,
                buffer_ref=ref,
                receipt=receipt,
                media_type=ref.media_type,
                checksum=_buffer_crc32_hex(local_buffer_client, ref),
                width=metadata.width,
                height=metadata.height,
                shape=ref.shape,
                dtype=ref.dtype,
                layout=ref.layout,
                pixel_format=ref.pixel_format,
            )
    content = _read_image_content(
        image_payload,
        execution_metadata=execution_metadata,
        dataset_storage=dataset_storage,
        local_buffer_client=local_buffer_client,
        deadline_ns=deadline_ns,
    )
    allocation = local_buffer_client.allocate_external_buffer(
        content_length=len(content),
        owner_kind="workflow-runtime",
        owner_id=str(execution_metadata.get("workflow_run_id") or "workflow-run"),
        deadline_ns=deadline_ns,
    )
    register_local_buffer_lease_cleanup(
        execution_metadata,
        lease_id=allocation.receipt.lease_id,
        ownership_receipt=allocation.receipt,
    )
    try:
        local_buffer_client.write_lease_bytes(
            lease=allocation.lease,
            content=content,
        )
        checksum_value = crc32(content) & 0xFFFFFFFF
        committed = local_buffer_client.commit_external_buffer(
            receipt=allocation.receipt,
            checksum=checksum_value,
            media_type=metadata.media_type,
            shape=metadata.shape,
            dtype=metadata.dtype,
            layout=metadata.layout,
            pixel_format=metadata.pixel_format,
        )
    except Exception:
        local_buffer_client.conditional_release(receipt=allocation.receipt)
        raise
    return _PendingPhysicalPayload(
        payload_id=payload_id,
        buffer_ref=committed.buffer_ref,
        receipt=allocation.receipt,
        media_type=metadata.media_type,
        checksum=f"{checksum_value:08x}",
        width=metadata.width,
        height=metadata.height,
        shape=metadata.shape,
        dtype=metadata.dtype,
        layout=metadata.layout,
        pixel_format=metadata.pixel_format,
    )


def _prepare_object_store_payload(
    *,
    payload_id: str,
    image_payload: dict[str, object],
    execution_metadata: dict[str, object],
    dataset_storage: LocalDatasetStorage,
    local_buffer_client: object | None,
) -> _PreparedObjectPayload:
    """复用稳定对象或把临时表示物化为不可变 ObjectStore 对象。"""

    metadata = normalize_image_payload_metadata(image_payload)
    object_prefix = (
        Path("workflow-trigger-results")
        / str(execution_metadata.get("trigger_source_id") or "trigger-source")
        / str(execution_metadata.get("workflow_run_id") or "workflow-run")
    ).as_posix()
    kind = image_payload["transport_kind"]
    if kind == IMAGE_TRANSPORT_STORAGE:
        source_object_key = str(image_payload["object_key"])
        source_metadata = dataset_storage.stat_object(source_object_key)
        receipt = (
            dataset_storage.materialize_immutable_object(
                source_object_key=source_object_key,
                object_prefix=object_prefix,
                media_type=metadata.media_type,
            )
            if not _is_complete_immutable_metadata(source_metadata)
            else None
        )
        stable_metadata = receipt.metadata if receipt is not None else source_metadata
    else:
        if local_buffer_client is None and kind in {
            IMAGE_TRANSPORT_BUFFER,
            IMAGE_TRANSPORT_FRAME,
        }:
            raise ServiceConfigurationError(
                "Workflow ObjectStore 图片物化缺少 LocalBufferBroker client"
            )
        content = _read_image_content(
            image_payload,
            execution_metadata=execution_metadata,
            dataset_storage=dataset_storage,
            local_buffer_client=local_buffer_client,
            deadline_ns=monotonic_ns() + 30_000_000_000,
        )
        receipt = dataset_storage.write_immutable_object(
            object_prefix=object_prefix,
            content=(content if isinstance(content, bytes) else content.tobytes()),
            media_type=metadata.media_type,
            extension=_read_image_extension(image_payload),
        )
        stable_metadata = receipt.metadata
    if not _is_complete_immutable_metadata(stable_metadata):
        raise ServiceConfigurationError(
            "ObjectStore 不可变图片缺少稳定 identity",
            details={"object_key": stable_metadata.object_key},
        )
    checksum_algorithm = str(stable_metadata.checksum_algorithm)
    checksum = str(stable_metadata.checksum)
    return _PreparedObjectPayload(
        payload_id=payload_id,
        media_type=stable_metadata.media_type,
        content_length=stable_metadata.content_length,
        checksum_algorithm=checksum_algorithm,
        checksum=checksum,
        object_locator={
            "kind": "object-store",
            "object_key": stable_metadata.object_key,
            "immutable_version": stable_metadata.immutable_version,
            "content_length": stable_metadata.content_length,
            "media_type": stable_metadata.media_type,
            "checksum_algorithm": checksum_algorithm,
            "checksum": checksum,
        },
        width=metadata.width,
        height=metadata.height,
        shape=metadata.shape,
        dtype=metadata.dtype,
        layout=metadata.layout,
        pixel_format=metadata.pixel_format,
    )


def _read_image_content(
    image_payload: dict[str, object],
    *,
    execution_metadata: dict[str, object],
    dataset_storage: LocalDatasetStorage,
    local_buffer_client: object | None,
    deadline_ns: int,
) -> bytes | memoryview:
    """按 transport 读取原始表示，不做图片编码或解码。"""

    kind = image_payload["transport_kind"]
    if kind == IMAGE_TRANSPORT_MEMORY:
        registry = execution_metadata.get("execution_image_registry")
        if not isinstance(registry, ExecutionImageRegistry):
            raise ServiceConfigurationError("memory image-ref 缺少 ExecutionImageRegistry")
        return registry.read_content(str(image_payload["image_handle"]))
    if kind == IMAGE_TRANSPORT_STORAGE:
        return dataset_storage.resolve(str(image_payload["object_key"])).read_bytes()
    if kind == IMAGE_TRANSPORT_LOCAL_PATH:
        path = Path(str(image_payload["local_path"]))
        if not path.is_file():
            raise InvalidRequestError("本地图片文件不存在", details={"local_path": str(path)})
        return path.read_bytes()
    if kind == IMAGE_TRANSPORT_BUFFER:
        if local_buffer_client is None:
            raise ServiceConfigurationError("BufferRef 读取缺少 LocalBufferBroker client")
        ref = BufferRef.model_validate(image_payload["buffer_ref"])
        acquire_reader = getattr(
            local_buffer_client, "acquire_buffer_reader_guard", None
        )
        if callable(acquire_reader):
            with acquire_reader(buffer_ref=ref, deadline_ns=deadline_ns):
                content = _read_buffer_view(local_buffer_client, ref)
                return bytes(content)
        return bytes(_read_buffer_view(local_buffer_client, ref))
    if kind == IMAGE_TRANSPORT_FRAME:
        if local_buffer_client is None:
            raise ServiceConfigurationError("FrameRef 读取缺少 LocalBufferBroker client")
        ref = FrameRef.model_validate(image_payload["frame_ref"])
        acquire_reader = getattr(
            local_buffer_client, "acquire_frame_reader_guard", None
        )
        if not callable(acquire_reader):
            raise ServiceConfigurationError(
                "FrameRef 输出复制缺少 reader guard 支持"
            )
        with acquire_reader(frame_ref=ref, deadline_ns=deadline_ns):
            read_view = getattr(local_buffer_client, "read_frame_ref_view", None)
            content = (
                read_view(ref)
                if callable(read_view)
                else local_buffer_client.read_frame_ref(ref)
            )
            return bytes(content)
    raise InvalidRequestError("不支持的图片 transport_kind", details={"transport_kind": kind})


def _is_complete_immutable_metadata(metadata: object) -> bool:
    """判断 ObjectStore metadata 是否足以作为稳定公开 locator。"""

    return bool(
        getattr(metadata, "is_immutable", False)
        and getattr(metadata, "immutable_version", None)
        and getattr(metadata, "checksum_algorithm", None)
        and getattr(metadata, "checksum", None)
        and getattr(metadata, "content_length", 0) > 0
        and getattr(metadata, "media_type", None)
    )


def _read_image_extension(image_payload: dict[str, object]) -> str | None:
    """从 storage/local-path 原始名称读取表示扩展名。"""

    value = image_payload.get("object_key") or image_payload.get("local_path")
    if not isinstance(value, str):
        return None
    return Path(value).suffix or None


def _build_stable_image_ref(
    physical_payload: PreparedPhysicalPayload,
) -> dict[str, object]:
    """把物理 payload locator 转成公开 image-ref.v1。"""

    if physical_payload.delivery_kind == "local-buffer":
        return {
            "transport_kind": IMAGE_TRANSPORT_BUFFER,
            "buffer_ref": dict(physical_payload.buffer_ref or {}),
            "media_type": physical_payload.media_type,
            **_build_optional_image_metadata(physical_payload),
        }
    locator = dict(physical_payload.object_locator or {})
    payload = build_storage_image_payload(
        object_key=str(locator["object_key"]),
        width=physical_payload.width,
        height=physical_payload.height,
        media_type=physical_payload.media_type,
    )
    payload.update(
        {
            "immutable_version": locator.get("immutable_version"),
            "content_length": physical_payload.content_length,
            "checksum_algorithm": physical_payload.checksum_algorithm,
            "checksum": physical_payload.checksum,
            **_build_optional_image_metadata(physical_payload),
        }
    )
    return payload


def _build_optional_image_metadata(
    physical_payload: PreparedPhysicalPayload,
) -> dict[str, object]:
    """构造 raw/encoded image-ref 的可选表示元数据。"""

    payload: dict[str, object] = {}
    if physical_payload.width is not None:
        payload["width"] = physical_payload.width
    if physical_payload.height is not None:
        payload["height"] = physical_payload.height
    if physical_payload.shape:
        payload["shape"] = list(physical_payload.shape)
    if physical_payload.dtype is not None:
        payload["dtype"] = physical_payload.dtype
    if physical_payload.layout is not None:
        payload["layout"] = physical_payload.layout
    if physical_payload.pixel_format is not None:
        payload["pixel_format"] = physical_payload.pixel_format
    return payload


def _read_buffer_view(local_buffer_client: object, ref: BufferRef) -> bytes | memoryview:
    """优先借用 mmap view 计算校验并复制。"""

    read_view = getattr(local_buffer_client, "read_buffer_ref_view", None)
    return read_view(ref) if callable(read_view) else local_buffer_client.read_buffer_ref(ref)


def _buffer_crc32_hex(local_buffer_client: object, ref: BufferRef) -> str:
    """让 reader guard 覆盖完整 CRC 扫描，不复制图片。"""

    acquire_view = getattr(local_buffer_client, "acquire_buffer_ref_view", None)
    if callable(acquire_view):
        with acquire_view(ref) as content:
            return f"{crc32(content) & 0xFFFFFFFF:08x}"
    return f"{crc32(local_buffer_client.read_buffer_ref(ref)) & 0xFFFFFFFF:08x}"


def _receipt_matches_buffer_ref(
    receipt: LeaseOwnershipReceipt,
    ref: BufferRef,
) -> bool:
    """校验私有 receipt 与公开 locator 的代次 identity。"""

    return (
        receipt.lease_id == ref.lease_id
        and receipt.buffer_id == ref.buffer_id
        and receipt.arena_id == ref.arena_id
        and receipt.broker_epoch == ref.broker_epoch
        and receipt.descriptor_index == ref.descriptor_index
        and receipt.descriptor_generation == ref.descriptor_generation
        and receipt.offset == ref.offset
        and receipt.content_length == ref.content_length
        and receipt.allocation_capacity_bytes == ref.allocation_capacity_bytes
    )


def _reject_ephemeral_refs(value: object, *, binding_id: str) -> None:
    """普通 JSON binding 不允许递归夹带执行期图片引用。"""

    if isinstance(value, dict):
        transport_kind = value.get("transport_kind")
        if transport_kind in {
            IMAGE_TRANSPORT_MEMORY,
            IMAGE_TRANSPORT_BUFFER,
            IMAGE_TRANSPORT_FRAME,
        } or any(key in value for key in ("image_handle", "buffer_ref", "frame_ref")):
            raise EphemeralImageRefInJsonResultError(
                details={"binding_id": binding_id}
            )
        for nested in value.values():
            _reject_ephemeral_refs(nested, binding_id=binding_id)
    elif isinstance(value, list | tuple):
        for nested in value:
            _reject_ephemeral_refs(nested, binding_id=binding_id)


def _resolve_current_response_capability(
    *,
    trigger_kind: str,
    result_mode: str,
    has_images: bool,
) -> tuple[AttachmentDeliveryKind, str]:
    """按当前已经落地的 adapter 能力固定图片交付方式。"""

    if result_mode == "event-only":
        return "none", "event-only.v1"
    if result_mode == "accepted-then-query":
        return (
            "object-store" if has_images else "none",
            "accepted-query-object-store.v1",
        )
    if not has_images:
        return "none", f"{trigger_kind}.json-result.v1"
    if trigger_kind == "local-shared-memory":
        return "local-buffer", "local-shared-memory.local-buffer-result.v1"
    if trigger_kind == "zeromq-topic":
        return "zeromq-frame", "zeromq-topic.multipart-result.v1"
    raise InvalidRequestError(
        "当前 Trigger adapter 尚不支持直接图片结果",
        details={
            "trigger_kind": trigger_kind,
            "required_capability": "image-attachment",
        },
    )


def _try_parse_trigger_response_plan(value: object) -> TriggerResponsePlan | None:
    """只把完整合法的旧计划用于 generation 比较。"""

    if not isinstance(value, dict):
        return None
    try:
        return TriggerResponsePlan.model_validate(value)
    except Exception:
        return None


def _build_trigger_response_plan_fingerprint(payload: dict[str, object]) -> str:
    """计算跨进程稳定的 Trigger response plan SHA-256。"""

    normalized = dict(payload)
    normalized.pop("plan_fingerprint", None)
    return sha256(
        json.dumps(
            normalized,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
