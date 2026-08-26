"""Workflow Trigger 输出规范化、去重与 lease handoff 测试。"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from time import monotonic_ns
from zlib import crc32

import pytest

from backend.nodes.runtime_support import ExecutionImageRegistry
from backend.service.application.errors import (
    EphemeralImageRefInJsonResultError,
    InvalidRequestError,
)
from backend.service.application.local_buffers import (
    LocalBufferBrokerProcessSupervisor,
    LocalBufferBrokerSettings,
)
from backend.service.application.workflows.execution_cleanup import (
    register_local_buffer_lease_cleanup,
)
from backend.service.application.workflows.trigger_sources.output_delivery import (
    TRIGGER_RESPONSE_PLAN_METADATA_KEY,
    WORKFLOW_OUTPUT_DELIVERY_PLAN_METADATA_KEY,
    WorkflowOutputDeliveryPlan,
    build_trigger_response_plan,
    build_workflow_output_delivery_plan,
    build_prepared_result_outputs,
    build_public_prepared_result_payload,
    list_prepared_result_ownership_receipts,
    prepare_trigger_result_before_cleanup,
    require_trigger_response_plan,
)
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings,
    LocalDatasetStorage,
)


def test_selected_json_keeps_order_and_rejects_nested_ephemeral_ref(
    tmp_path: Path,
) -> None:
    """普通 JSON 只返回显式 binding，且不允许夹带短期图片引用。"""

    metadata = {
        WORKFLOW_OUTPUT_DELIVERY_PLAN_METADATA_KEY: WorkflowOutputDeliveryPlan(
            result_mode="sync-reply",
            result_bindings=("second", "first"),
        ).model_dump(mode="json")
    }
    prepared = prepare_trigger_result_before_cleanup(
        outputs={"first": {"value": 1}, "second": {"value": 2}, "ignored": 3},
        output_payload_types={"first": "value.v1", "second": "value.v1"},
        execution_metadata=metadata,
        dataset_storage=_storage(tmp_path),
        local_buffer_client=None,
    )
    assert prepared is not None
    assert list(prepared.selected_results) == ["second", "first"]
    assert build_prepared_result_outputs(prepared) == {
        "second": {"value": 2},
        "first": {"value": 1},
    }

    with pytest.raises(EphemeralImageRefInJsonResultError):
        prepare_trigger_result_before_cleanup(
            outputs={
                "first": {
                    "nested": {
                        "transport_kind": "memory",
                        "image_handle": "img-1",
                    }
                }
            },
            output_payload_types={"first": "value.v1"},
            execution_metadata={
                WORKFLOW_OUTPUT_DELIVERY_PLAN_METADATA_KEY: (
                    WorkflowOutputDeliveryPlan(
                        result_mode="sync-reply",
                        result_bindings=("first",),
                    ).model_dump(mode="json")
                )
            },
            dataset_storage=_storage(tmp_path),
            local_buffer_client=None,
        )


def test_trigger_response_plan_fixes_contract_identity_and_generation() -> None:
    """相同契约保留 generation，Runtime 或 binding 变化时原子推进。"""

    first = _response_plan(
        selected_output_payload_types={
            "summary": "value.v1",
            "image": "image-ref.v1",
        }
    )
    same = _response_plan(
        selected_output_payload_types={
            "summary": "value.v1",
            "image": "image-ref.v1",
        },
        previous_plan=first.model_dump(mode="json"),
    )
    changed = _response_plan(
        workflow_runtime_revision_id="revision-2",
        selected_output_payload_types={
            "summary": "value.v1",
            "image": "image-ref.v1",
        },
        previous_plan=same.model_dump(mode="json"),
    )

    assert first.attachment_delivery_kind == "local-buffer"
    assert same.plan_generation == first.plan_generation
    assert same.plan_fingerprint == first.plan_fingerprint
    assert changed.plan_generation == first.plan_generation + 1
    output_plan = build_workflow_output_delivery_plan(
        first,
        response_owner_kind="workflow-trigger-response",
        response_owner_id="descriptor-1",
        deadline_ns=monotonic_ns() + 5_000_000_000,
    )
    assert output_plan.result_bindings == ("summary", "image")
    assert output_plan.attachment_delivery_kind == "local-buffer"


def test_trigger_response_plan_rejects_tampering_and_enables_zeromq_images() -> None:
    """fingerprint 防止配置漂移，ZeroMQ 图片输出固定为 multipart capability。"""

    plan = _response_plan(selected_output_payload_types={"summary": "value.v1"})
    payload = plan.model_dump(mode="json")
    payload["contract_fingerprint"] = "tampered"
    with pytest.raises(ValueError, match="fingerprint"):
        require_trigger_response_plan(
            {TRIGGER_RESPONSE_PLAN_METADATA_KEY: payload}
        )

    zeromq_plan = _response_plan(
        trigger_kind="zeromq-topic",
        selected_output_payload_types={"image": "image-ref.v1"},
    )
    assert zeromq_plan.attachment_delivery_kind == "zeromq-frame"
    assert (
        zeromq_plan.adapter_capability_revision
        == "zeromq-topic.multipart-result.v1"
    )


def test_current_run_buffer_is_handed_off_once_for_duplicate_attachments(
    tmp_path: Path,
) -> None:
    """同一物理 BufferRef 的多个逻辑 item 只发生一次 owner transfer。"""

    with _broker(tmp_path, capacity_units=3) as supervisor:
        client = supervisor.create_client()
        assert client is not None
        content = b"BGR" * 1024
        allocation, buffer_ref = _write_external(
            client,
            content,
            owner_kind="workflow-runtime",
            owner_id="workflow-run-1",
        )
        deadline_ns = monotonic_ns() + 5_000_000_000
        execution_metadata = {
            "workflow_run_id": "workflow-run-1",
            WORKFLOW_OUTPUT_DELIVERY_PLAN_METADATA_KEY: WorkflowOutputDeliveryPlan(
                result_mode="sync-reply",
                result_bindings=("images",),
                attachment_delivery_kind="local-buffer",
                response_owner_kind="workflow-trigger-response",
                response_owner_id="descriptor-1",
                deadline_ns=deadline_ns,
            ).model_dump(mode="json"),
        }
        register_local_buffer_lease_cleanup(
            execution_metadata,
            lease_id=allocation.receipt.lease_id,
            ownership_receipt=allocation.receipt,
        )
        image_ref = {
            "transport_kind": "buffer",
            "buffer_ref": buffer_ref.model_dump(mode="json"),
            "media_type": buffer_ref.media_type,
        }

        prepared = prepare_trigger_result_before_cleanup(
            outputs={"images": {"items": [image_ref, image_ref]}},
            output_payload_types={"images": "image-refs.v1"},
            execution_metadata=execution_metadata,
            dataset_storage=_storage(tmp_path),
            local_buffer_client=client,
        )
        assert prepared is not None
        assert len(prepared.attachments) == 2
        assert len(prepared.physical_payloads) == 1
        assert {item.payload_id for item in prepared.attachments} == {"payload-0"}
        assert client.conditional_release(receipt=allocation.receipt) == "stale"

        stable_outputs = build_prepared_result_outputs(prepared)
        assert len(stable_outputs["images"]["items"]) == 2
        response_receipts = list_prepared_result_ownership_receipts(prepared)
        assert len(response_receipts) == 1
        public_payload = build_public_prepared_result_payload(prepared)
        public_physical = public_payload["payloads"][0]
        assert "reader_guard_path" not in public_physical
        assert "reader_guard_offset" not in public_physical
        assert "reader_guard_slots" not in public_physical
        assert "ownership_receipt" not in public_physical
        assert client.read_buffer_ref(buffer_ref) == content
        assert client.conditional_release(receipt=response_receipts[0]) == "released"
        client.close()


def test_foreign_buffer_is_copied_under_reader_guard(
    tmp_path: Path,
) -> None:
    """缺少当前 Run receipt 的 BufferRef 复制到新 lease，不转移 foreign owner。"""

    with _broker(tmp_path, capacity_units=3) as supervisor:
        client = supervisor.create_client()
        assert client is not None
        content = b"foreign-image" * 128
        foreign, foreign_ref = _write_external(
            client,
            content,
            owner_kind="foreign-owner",
            owner_id="foreign-1",
        )
        execution_metadata = {
            "workflow_run_id": "workflow-run-copy",
            WORKFLOW_OUTPUT_DELIVERY_PLAN_METADATA_KEY: WorkflowOutputDeliveryPlan(
                result_mode="sync-reply",
                result_bindings=("image",),
                attachment_delivery_kind="local-buffer",
                response_owner_kind="workflow-trigger-response",
                response_owner_id="descriptor-copy",
                deadline_ns=monotonic_ns() + 5_000_000_000,
            ).model_dump(mode="json"),
        }
        prepared = prepare_trigger_result_before_cleanup(
            outputs={
                "image": {
                    "transport_kind": "buffer",
                    "buffer_ref": foreign_ref.model_dump(mode="json"),
                    "media_type": foreign_ref.media_type,
                }
            },
            output_payload_types={"image": "image-ref.v1"},
            execution_metadata=execution_metadata,
            dataset_storage=_storage(tmp_path),
            local_buffer_client=client,
        )
        assert prepared is not None
        copied_ref = prepared.physical_payloads[0].buffer_ref
        assert copied_ref is not None
        assert copied_ref["lease_id"] != foreign_ref.lease_id
        assert client.conditional_release(receipt=foreign.receipt) == "released"
        response_receipt = list_prepared_result_ownership_receipts(prepared)[0]
        assert client.conditional_release(receipt=response_receipt) == "released"
        client.close()


def test_accepted_query_materializes_memory_image_to_immutable_object(
    tmp_path: Path,
) -> None:
    """异步查询结果把 memory image 固定为带完整 identity 的 ObjectStore locator。"""

    storage = _storage(tmp_path)
    registry = ExecutionImageRegistry()
    entry = registry.register_image_bytes(
        content=b"encoded-png-content",
        media_type="image/png",
        width=4,
        height=3,
    )
    metadata = {
        "trigger_source_id": "source-1",
        "workflow_run_id": "run-1",
        "execution_image_registry": registry,
        WORKFLOW_OUTPUT_DELIVERY_PLAN_METADATA_KEY: WorkflowOutputDeliveryPlan(
            result_mode="accepted-then-query",
            result_bindings=("image", "record"),
            attachment_delivery_kind="object-store",
        ).model_dump(mode="json"),
    }
    prepared = prepare_trigger_result_before_cleanup(
        outputs={
            "image": {
                "transport_kind": "memory",
                "image_handle": entry.image_handle,
                "media_type": entry.media_type,
                "width": entry.width,
                "height": entry.height,
            },
            "record": {"ok": True},
        },
        output_payload_types={"image": "image-ref.v1", "record": "value.v1"},
        execution_metadata=metadata,
        dataset_storage=storage,
        local_buffer_client=None,
    )
    assert prepared is not None
    assert prepared.selected_results == {"record": {"ok": True}}
    physical = prepared.physical_payloads[0]
    assert physical.delivery_kind == "object-store"
    assert physical.checksum_algorithm == "sha256"
    locator = dict(physical.object_locator or {})
    assert locator["immutable_version"] == f"sha256:{physical.checksum}"
    assert storage.resolve(str(locator["object_key"])).read_bytes() == (
        b"encoded-png-content"
    )
    stable = build_prepared_result_outputs(prepared)
    assert stable["image"]["transport_kind"] == "storage"
    assert stable["image"]["immutable_version"] == locator["immutable_version"]


def test_missing_selected_binding_fails_before_any_handoff(tmp_path: Path) -> None:
    """binding 缺失时不分配图片 lease，也不形成部分响应。"""

    with pytest.raises(InvalidRequestError, match="binding 不存在"):
        prepare_trigger_result_before_cleanup(
            outputs={"present": 1},
            output_payload_types={"present": "value.v1"},
            execution_metadata={
                WORKFLOW_OUTPUT_DELIVERY_PLAN_METADATA_KEY: (
                    WorkflowOutputDeliveryPlan(
                        result_mode="sync-reply",
                        result_bindings=("missing",),
                    ).model_dump(mode="json")
                )
            },
            dataset_storage=_storage(tmp_path),
            local_buffer_client=None,
        )


def _storage(tmp_path: Path) -> LocalDatasetStorage:
    """构造隔离的本地 ObjectStore。"""

    return LocalDatasetStorage(DatasetStorageSettings(root_dir=str(tmp_path / "files")))


def _response_plan(
    *,
    trigger_kind: str = "local-shared-memory",
    workflow_runtime_revision_id: str = "revision-1",
    selected_output_payload_types: dict[str, str],
    previous_plan: object = None,
):
    """构造测试使用的固定 Trigger response plan。"""

    return build_trigger_response_plan(
        trigger_source_id="trigger-source-1",
        trigger_kind=trigger_kind,
        workflow_runtime_id="runtime-1",
        workflow_runtime_revision_id=workflow_runtime_revision_id,
        workflow_app_version_id="version-1",
        workflow_runtime_generation=1,
        expected_snapshot_fingerprint="snapshot-1",
        contract_fingerprint="contract-1",
        submit_mode="sync",
        result_mode="sync-reply",
        ack_policy="ack-after-run-finished",
        reply_timeout_seconds=30,
        response_ack_timeout_seconds=(
            30.0 if trigger_kind == "local-shared-memory" else None
        ),
        selected_output_payload_types=selected_output_payload_types,
        previous_plan=previous_plan,
    )


@contextmanager
def _broker(
    tmp_path: Path,
    *,
    capacity_units: int,
) -> object:
    """构造小容量固定 arena；capacity_units 只调节测试总容量。"""

    supervisor = LocalBufferBrokerProcessSupervisor(
        settings=LocalBufferBrokerSettings(
            root_dir=str(tmp_path / "buffers"),
            arena_id="local-buffer-main",
            arena_size_bytes=max(4, capacity_units) * 1024 * 1024,
            min_block_size_bytes=1024 * 1024,
            max_allocation_bytes=4 * 1024 * 1024,
            reader_guard_slots=8,
            request_timeout_seconds=5.0,
        )
    )
    supervisor.start()
    try:
        yield supervisor
    finally:
        supervisor.stop()


def _write_external(
    client: object,
    content: bytes,
    *,
    owner_kind: str,
    owner_id: str,
):
    """向真实 Broker 写入并提交一份测试图片。"""

    deadline_ns = monotonic_ns() + 5_000_000_000
    allocation = client.allocate_external_buffer(
        content_length=len(content),
        owner_kind=owner_kind,
        owner_id=owner_id,
        deadline_ns=deadline_ns,
    )
    client.write_lease_bytes(lease=allocation.lease, content=content)
    result = client.commit_external_buffer(
        receipt=allocation.receipt,
        checksum=crc32(content) & 0xFFFFFFFF,
        media_type="application/octet-stream",
    )
    return allocation, result.buffer_ref
