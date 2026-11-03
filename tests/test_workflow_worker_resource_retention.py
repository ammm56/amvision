"""资源关闭失败后，整组回收与父进程重复清理的所有权回归。"""

from threading import Event
from types import SimpleNamespace

import pytest

from backend.service.application.workflows.execution_cleanup import (
    register_execution_cleanup,
)
from backend.service.application.workflows.worker.manager import (
    _WorkflowRuntimePendingResponse,
)
from tests.test_workflow_worker_manager_cleanup import (
    _build_test_workflow_runtime,
    _build_token_worker_manager,
)


def make_manager():
    """复用既有 Runtime/token 夹具，不创建另一套进程管理器。"""
    runtime = _build_test_workflow_runtime(
        revision_id="revision-1", generation=1, fingerprint="fingerprint-1"
    )
    manager = _build_token_worker_manager(runtime)
    manager._recovery_scan_requested = Event()
    manager._monitor_wake_event = Event()
    handle = manager._handles[runtime.workflow_runtime_id]
    calls = []
    handle.process.stop_group = lambda **_: calls.append("group-exited")
    manager.dataset_storage = SimpleNamespace(delete_tree=lambda key: calls.append(key))
    manager._get_cleanup_local_buffer_client = lambda: None
    metadata = {}
    register_execution_cleanup(
        metadata, resource_kind="dataset_storage_tree", resource_id="input/run-1"
    )
    return manager, runtime, handle, calls, metadata


def fatal_response(handle):
    """使用真实消息身份字段模拟资源释放失败响应。"""
    return {
        "message_type": "worker-error",
        "state": "failed",
        "worker_reusable": False,
        "error_message": "Workflow resource cleanup failed",
        "workflow_runtime_revision_id": handle.workflow_runtime_revision_id,
        "runtime_generation": handle.runtime_generation,
        "snapshot_fingerprint": handle.expected_snapshot_fingerprint,
        "worker_instance_id": handle.worker_instance_id,
    }


def test_fatal_response_stops_group_before_input_release():
    manager, runtime, handle, calls, metadata = make_manager()

    def respond(request):
        pending = handle.pending_responses[request["message_id"]]
        pending.response = fatal_response(handle)
        pending.event.set()

    handle.request_queue.put = respond
    result = manager.invoke_runtime(
        workflow_app_runtime=runtime,
        workflow_run_id="run-1",
        input_bindings={},
        execution_metadata=metadata,
        timeout_seconds=5,
    )
    assert result.state == "failed"
    assert calls == ["group-exited", "input/run-1"]
    assert handle.cleanup_completed and not handle.pending_resource_cleanups
    assert not manager._retained_resource_handles
    assert not manager._handles and not manager._execution_tokens


@pytest.mark.parametrize("failure", ["stop", "delete"])
def test_failed_stop_or_release_retains_owner_and_blocks_upper_cleanup(failure):
    manager, runtime, handle, calls, metadata = make_manager()
    manager._retain_run_resources(handle, "run-1", metadata)

    def fail(**_):
        raise OSError("controlled failure")

    if failure == "stop":
        handle.process.stop_group = fail
    else:
        manager.dataset_storage.delete_tree = lambda _: fail()
    with pytest.raises(OSError, match="controlled failure"):
        manager._cleanup_handle(handle)
    assert not handle.cleanup_completed and handle.expected_shutdown
    assert handle.pending_resource_cleanups["run-1"] == metadata
    assert manager.cleanup_parent_local_buffer_leases(dict(metadata)) == 0
    assert manager.cleanup_workflow_run_local_buffer_owner("run-1") == 0
    assert calls == ([] if failure == "stop" else ["group-exited"])
    handle.process.stop_group = lambda **_: calls.append("group-exited")
    manager.dataset_storage.delete_tree = lambda key: calls.append(key)
    manager._cleanup_handle(handle)
    assert calls[-2:] == ["group-exited", "input/run-1"]
    assert handle.cleanup_completed and not manager._retained_resource_handles


def test_fatal_response_during_cancel_grace_cannot_be_treated_as_reusable():
    manager, runtime, handle, calls, metadata = make_manager()
    pending = _WorkflowRuntimePendingResponse()
    pending.response = fatal_response(handle)
    pending.event.set()
    manager._retain_run_resources(handle, "run-1", metadata)
    received = manager._cancel_runtime_invocation(
        workflow_runtime_id=runtime.workflow_runtime_id,
        handle=handle,
        pending=pending,
        cancellation_grace_seconds=1,
        workflow_run_id="run-1",
    )
    assert received is False
    assert calls == ["group-exited", "input/run-1"]
    assert not manager._handles


def test_broker_failure_does_not_discard_deferred_input():
    manager, _, handle, _, metadata = make_manager()
    register_execution_cleanup(
        metadata, resource_kind="local_buffer_lease", resource_id="lease-1"
    )
    released = []

    def fail(**_):
        raise OSError("broker unavailable")

    client = SimpleNamespace(
        release_owner=fail, release=lambda lease: released.append(lease)
    )
    manager._get_cleanup_local_buffer_client = lambda: client
    manager._invalidate_cleanup_local_buffer_client = lambda _: None
    manager._retain_run_resources(handle, "run-1", metadata)
    with pytest.raises(OSError, match="broker unavailable"):
        manager._cleanup_handle(handle)
    assert (
        not released
        and handle.pending_resource_cleanups
        and not handle.cleanup_completed
    )
    client.release_owner = lambda **_: 0
    manager._cleanup_handle(handle)
    assert released == ["lease-1"] and handle.cleanup_completed


def test_failed_run_reclaims_response_owner_after_group_exit():
    manager, _, handle, calls, metadata = make_manager()
    from backend.service.application.workflows.trigger_sources.output_delivery import (
        WORKFLOW_OUTPUT_DELIVERY_PLAN_METADATA_KEY,
        WorkflowOutputDeliveryPlan,
    )

    metadata[WORKFLOW_OUTPUT_DELIVERY_PLAN_METADATA_KEY] = WorkflowOutputDeliveryPlan(
        result_mode="sync-reply",
        result_bindings=("image",),
        attachment_delivery_kind="local-buffer",
        response_owner_kind="trigger-response",
        response_owner_id="response-1",
        deadline_ns=100,
    ).model_dump(mode="json")
    client = SimpleNamespace(release_owner=lambda **owner: calls.append(owner))
    manager._get_cleanup_local_buffer_client = lambda: client
    manager._retain_run_resources(handle, "run-1", metadata)
    manager._cleanup_handle(handle)
    assert calls == [
        "group-exited",
        {"owner_kind": "workflow-runtime", "owner_id_prefix": "run-1:"},
        "input/run-1",
        {"owner_kind": "trigger-response", "owner_id": "response-1"},
    ]


def test_monitor_wins_response_race_without_losing_input_ownership(monkeypatch):
    manager, runtime, handle, calls, metadata = make_manager()

    def respond(request):
        pending = handle.pending_responses[request["message_id"]]
        pending.response = {**fatal_response(handle), "worker_reusable": True}
        pending.event.set()

    handle.request_queue.put = respond
    original = manager._validate_worker_response_identity

    def validate(message, observed):
        original(message, observed)
        manager._cleanup_handle(handle)

    monkeypatch.setattr(manager, "_validate_worker_response_identity", validate)
    with pytest.raises(Exception, match="迟到响应"):
        manager.invoke_runtime(
            workflow_app_runtime=runtime,
            workflow_run_id="run-1",
            input_bindings={},
            execution_metadata=metadata,
            timeout_seconds=5,
        )
    assert calls[:2] == ["group-exited", "input/run-1"]
    assert (
        not handle.pending_resource_cleanups and not manager._retained_resource_handles
    )


def test_invoke_stop_failure_is_not_retried_or_released_by_upper_layer():
    manager, runtime, handle, calls, metadata = make_manager()

    def stop(**_):
        calls.append("stop-failed")
        raise OSError("stop failed")

    handle.process.stop_group = stop

    def respond(request):
        pending = handle.pending_responses[request["message_id"]]
        pending.response = fatal_response(handle)
        pending.event.set()

    handle.request_queue.put = respond
    with pytest.raises(OSError, match="stop failed"):
        manager.invoke_runtime(
            workflow_app_runtime=runtime,
            workflow_run_id="run-1",
            input_bindings={},
            execution_metadata=metadata,
            timeout_seconds=5,
        )
    manager.cleanup_parent_local_buffer_leases(metadata)
    assert calls == ["stop-failed"]
    assert handle.pending_resource_cleanups and handle.expected_shutdown
    assert not manager._execution_tokens
    handle.process.stop_group = lambda **_: calls.append("group-exited")
    manager._cleanup_handle(handle)
    assert calls[-2:] == ["group-exited", "input/run-1"]
