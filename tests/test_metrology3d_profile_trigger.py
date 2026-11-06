"""轮廓公开描述、私有交接、预算和拒绝边界；真实发布另行组合验证。"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from backend.contracts.buffers import BufferRef
from backend.contracts.workflows.profile_trigger import (
    PROFILE_BUFFER_MEDIA_TYPE,
    WorkflowTriggerProfilePrepareV1,
    WorkflowTriggerProfileInputV1,
)
from backend.contracts.workflows.trigger_sources import (
    workflow_trigger_supports_input_payload_type,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.point_cloud.trigger_input import (
    CLOUD_HANDOFF_KEY,
    CloudInputHandoff,
    require_profile_handoff,
    trusted_cloud_bindings,
)
from backend.service.application.workflows.trigger_sources.input_buffers import (
    buffer_metadata,
    buffer_length,
    input_payload,
    validate_cloud_prepare,
)
from tests.test_metrology3d_profile_buffer import descriptor
from tests.integration.metrology3d.test_nodes import execution_policy


def prepare():
    return WorkflowTriggerProfilePrepareV1(
        trigger_source_id="source",
        event_id="event",
        event_payload_key="profiles",
        profiles=descriptor(),
    )


def test_profile_prepare_schema_and_capabilities():
    path = (
        Path(__file__).resolve().parents[1]
        / "sdks/schemas/workflow-trigger-profile-prepare.v1.schema.json"
    )
    assert (
        json.loads(path.read_text("utf-8"))
        == WorkflowTriggerProfilePrepareV1.model_json_schema()
    )
    assert workflow_trigger_supports_input_payload_type(
        "local-shared-memory", "calibrated-profiles.v1"
    )
    for kind in ("http", "zeromq", "file-watch"):
        assert not workflow_trigger_supports_input_payload_type(
            kind, "calibrated-profiles.v1"
        )
    assert buffer_length(prepare()) == descriptor().content_length
    assert buffer_metadata(prepare())["media_type"] == PROFILE_BUFFER_MEDIA_TYPE


@pytest.mark.parametrize(
    "changes", [{"content_length": 1}, {"has_validity": 1}, {"extra": 1}]
)
def test_profile_prepare_rejects_invalid_layout(changes):
    value = prepare().model_dump(mode="json")
    value["profiles"].update(changes)
    with pytest.raises(ValidationError):
        WorkflowTriggerProfilePrepareV1.model_validate(value)


def test_profile_binding_and_budget_admission():
    policy = execution_policy()
    source = SimpleNamespace(
        metadata={
            "validated_workflow_input_payload_types": {"p": "calibrated-profiles.v1"}
        },
        input_binding_mapping={"p": {"source": "payload.profiles"}},
    )
    validate_cloud_prepare(prepare(), source, policy)
    source.metadata["validated_workflow_input_payload_types"]["p"] = (
        "calibrated-raster.v1"
    )
    with pytest.raises(InvalidRequestError):
        validate_cloud_prepare(prepare(), source, policy)
    source.metadata["validated_workflow_input_payload_types"]["p"] = (
        "calibrated-profiles.v1"
    )
    small = policy.model_copy(
        update={"io": policy.io.model_copy(update={"max_live_array_bytes": 1})}
    )
    with pytest.raises(InvalidRequestError):
        validate_cloud_prepare(prepare(), source, small)


def test_profile_handoff_rejects_json_old_run_and_replacement():
    # 这里只验证契约与私有交接，实际映射和回收在真实发布测试中执行。
    ref = BufferRef(
        buffer_id="b",
        lease_id="l",
        arena_id="a",
        broker_epoch="epoch",
        descriptor_index=0,
        descriptor_generation=1,
        offset=0,
        allocation_capacity_bytes=4096,
        content_length=descriptor().content_length,
        media_type=PROFILE_BUFFER_MEDIA_TYPE,
    )
    key, value = input_payload(prepare(), ref)
    assert key == "profiles"
    handoff = CloudInputHandoff(run_id="r", binding_ids=("input",), payload=value)
    metadata = {CLOUD_HANDOFF_KEY: handoff, "workflow_run_id": "r"}
    assert require_profile_handoff(metadata, value).descriptor == descriptor()
    assert trusted_cloud_bindings(metadata, {"input": value}) == {"input"}
    for meta, payload in [
        ({**metadata, "workflow_run_id": "old"}, value),
        (metadata, {**value, "descriptor_sha256": "0" * 64}),
    ]:
        with pytest.raises(InvalidRequestError):
            require_profile_handoff(meta, payload)
    for change in (
        {"readonly": False},
        {"media_type": "image/raw"},
        {"dtype": "float32"},
        {"content_length": 1},
        {"shape": (6, 2)},
    ):
        bad = {**value, "buffer_ref": {**value["buffer_ref"], **change}}
        with pytest.raises(ValidationError):
            WorkflowTriggerProfileInputV1.model_validate(bad)
    with pytest.raises(InvalidRequestError):
        require_profile_handoff(
            {CLOUD_HANDOFF_KEY: {"run_id": "r"}, "workflow_run_id": "r"}, {}
        )
