"""运行引用前置清理、失败保留和 Snapshot 恢复准入回归。"""

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace
import weakref

import pytest

from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.resource_scope import (
    ResourceScope,
    get_or_create_workflow_resource_scope,
)
from backend.service.application.workflows.resource_finalization import (
    WorkflowResourceCleanupError,
    finalize_workflow_resources,
    require_reusable_process_scope,
)
from backend.service.application.workflows.snapshot_execution import (
    SnapshotExecutionService,
    WorkflowSnapshotExecutionRequest,
)


class Resource:
    """可 weakref 的资源夹具。"""


def fail_close(_resource):
    """模拟仍有 ndarray 导出视图时底层 mapping 无法关闭。"""
    raise BufferError("mapping is still borrowed")


def test_explicit_borrow_phase_preserves_existing_cleanup_order():
    scope, process = ResourceScope(kind="workflow"), ResourceScope(kind="process")
    calls = []
    scope.register("old", Resource(), lambda _: calls.append("old"))
    scope.register(
        "cloud",
        Resource(),
        lambda _: calls.append("cloud"),
        before_external_cleanup=True,
    )
    assert (
        finalize_workflow_resources(
            scope=scope,
            process_scope=process,
            cleanup_external=lambda: calls.append("external"),
            execution_error=None,
        )
        is None
    )
    assert calls == ["cloud", "external", "old"]
    assert scope.close() == () and scope.resource_count == 0


def test_failed_borrow_blocks_external_cleanup_and_survives_later_close():
    scope, process = ResourceScope(kind="workflow"), ResourceScope(kind="process")
    resource = Resource()
    retained = weakref.ref(resource)
    scope.register("cloud", resource, fail_close, before_external_cleanup=True)
    del resource

    def forbidden():
        pytest.fail("must not release underlying lease or file")

    error = finalize_workflow_resources(
        scope=scope,
        process_scope=process,
        cleanup_external=forbidden,
        execution_error=InvalidRequestError("bad input"),
    )
    assert isinstance(error, WorkflowResourceCleanupError)
    assert error.details["external_cleanup_blocked"]
    assert error.details["execution_error"]["error_code"] == "invalid_request"
    first = scope.close_errors
    assert scope.close() == first and scope.close_resource("cloud") == first
    assert scope.resource_count == 1
    del scope
    assert retained() is not None and process.close_errors
    with pytest.raises(WorkflowResourceCleanupError):
        require_reusable_process_scope(process)


def test_failed_scopes_from_parallel_runs_remain_owned():
    process = ResourceScope(kind="process")

    def finish(index):
        scope = ResourceScope(kind=str(index))
        scope.register("cloud", Resource(), fail_close, before_external_cleanup=True)
        return finalize_workflow_resources(
            scope=scope,
            process_scope=process,
            cleanup_external=lambda: None,
            execution_error=None,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        errors = list(executor.map(finish, range(2)))
    assert all(isinstance(error, WorkflowResourceCleanupError) for error in errors)
    assert len(process.close_errors) == process.resource_count == 2


def test_simultaneous_scope_close_waits_for_in_progress_closer():
    scope = ResourceScope(kind="workflow")
    entered, release, finished = Event(), Event(), Event()

    def close(_):
        entered.set()
        assert release.wait(5)
        finished.set()

    scope.register("cloud", Resource(), close, before_external_cleanup=True)
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(scope.close_before_external_cleanup)
        assert entered.wait(5)
        second = executor.submit(scope.close)
        assert not finished.is_set() and not second.done()
        release.set()
        assert first.result() == second.result() == ()


@pytest.mark.parametrize("fail_external", [False, True])
def test_late_scope_failure_is_fatal_even_if_external_cleanup_fails(fail_external):
    scope, process = ResourceScope(kind="workflow"), ResourceScope(kind="process")
    scope.register("old", Resource(), fail_close)

    def external():
        if fail_external:
            raise OSError("disk unavailable")

    error = finalize_workflow_resources(
        scope=scope,
        process_scope=process,
        cleanup_external=external,
        execution_error=None,
    )
    assert isinstance(error, WorkflowResourceCleanupError)
    assert not error.details["external_cleanup_blocked"]
    assert ("cleanup_error" in error.details) == fail_external


def test_snapshot_preparation_failure_is_inside_cleanup_boundary(monkeypatch):
    service = object.__new__(SnapshotExecutionService)
    service.runtime_context = SimpleNamespace(
        process_resource_scope=ResourceScope(kind="process")
    )
    calls = []

    def prepare(*, request, model_session_scope_id):
        scope = get_or_create_workflow_resource_scope(request.execution_metadata)
        scope.register("prepare", Resource(), lambda _: calls.append("closed"))
        raise InvalidRequestError("preparation failed")

    monkeypatch.setattr(service, "_execute_snapshot_graph", prepare)
    request = WorkflowSnapshotExecutionRequest(
        project_id="p",
        application_id="a",
        application_snapshot_object_key="a",
        template_snapshot_object_key="t",
    )
    with pytest.raises(InvalidRequestError, match="preparation failed"):
        service._execute_in_model_session_scope(
            request=request, model_session_scope_id="model"
        )
    assert calls == ["closed"]
    assert not request.execution_metadata


def test_snapshot_rejects_second_run_after_cleanup_failure(monkeypatch):
    service = object.__new__(SnapshotExecutionService)
    service.runtime_context = SimpleNamespace(
        process_resource_scope=ResourceScope(kind="process")
    )
    calls = []

    def graph(*, request, model_session_scope_id):
        calls.append("run")
        scope = get_or_create_workflow_resource_scope(request.execution_metadata)
        scope.register("cloud", Resource(), fail_close, before_external_cleanup=True)

    monkeypatch.setattr(service, "_execute_snapshot_graph", graph)
    request = WorkflowSnapshotExecutionRequest(
        project_id="p",
        application_id="a",
        application_snapshot_object_key="a",
        template_snapshot_object_key="t",
    )
    for _ in range(2):
        with pytest.raises(WorkflowResourceCleanupError):
            service._execute_in_model_session_scope(
                request=request, model_session_scope_id="model"
            )
    assert calls == ["run"]
