"""点云引用、分支所有权、子集、真实 arena 与失败隔离回归。"""

from hashlib import sha256
from uuid import uuid4

import numpy as np
import pytest

from backend.contracts.workflows.point_cloud_runtime import (
    CloudReference,
    CloudLocalSource,
    CloudProvenance,
    FilterCloudMethod,
    FilterCloudValid,
    NormalizeCloudMethod,
    NormalizeCloudUnits,
    canonical_cloud_json,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.resource_scope import ResourceScope
from backend.service.application.workflows.point_cloud.arrays import OwnedCloudArrays
from backend.service.application.workflows.point_cloud.local_array import (
    cloud_descriptor_sha256,
)
from backend.service.application.workflows.point_cloud.runtime import get_cloud_runtime
from backend.service.application.workflows.resource_finalization import (
    finalize_workflow_resources,
    WorkflowResourceCleanupError,
)
from tests.point_cloud_support import policy, options, spatial
from tests.test_point_cloud_local_array import (
    arena_input as arena_input,
    descriptor,
    payload,
)


def own(runtime, arrays):
    """数组夹具登记到与真实文件解码相同的作用域。"""
    reservation = runtime.budget.reserve(sum(array.nbytes for array in arrays.values()))
    owner = OwnedCloudArrays(arrays, reservation)
    runtime.storage_scope.register(uuid4().hex, owner, lambda value: value.close())
    return owner


def method(normalize=False):
    """参数摘要使用完整严格参数正文。"""
    params = (
        NormalizeCloudUnits()
        if normalize
        else FilterCloudValid(finite_fields=("positions",), sentinels=())
    )
    cls = NormalizeCloudMethod if normalize else FilterCloudMethod
    return cls(
        method_id="normalize-units" if normalize else "filter-valid",
        method_version=1,
        parameters=params,
        parameters_sha256=sha256(
            canonical_cloud_json(params.model_dump(mode="json"))
        ).hexdigest(),
    )


def root_cloud(runtime):
    values = np.arange(18, dtype=np.float32).reshape(6, 3)
    owner = own(runtime, {"positions": values})
    reference = runtime.register_source(
        owner=owner,
        point_count=6,
        fields=tuple(field.to_field() for field in options().field_mapping),
        spatial=spatial(),
        source=CloudLocalSource(
            kind="local-array",
            content_sha256="1" * 64,
            descriptor_sha256="2" * 64,
            source_observation_id=None,
        ),
        source_metadata=None,
        cancel=lambda: None,
    )
    return reference, owner


def test_single_scope_single_mapping_multiple_branches(arena_input):
    arena, receipt, acquire = arena_input
    scope = ResourceScope(kind="workflow")
    runtime = get_cloud_runtime(scope, run_id="run-a", policy=policy())
    assert get_cloud_runtime(scope, run_id="run-a", policy=policy()) is runtime
    calls = []

    def guard():
        calls.append("acquire")
        return acquire()

    reference = runtime.open_local(
        descriptor=descriptor(),
        expected_descriptor_sha256=cloud_descriptor_sha256(descriptor()),
        acquire_view=guard,
        cancel=lambda: None,
    )
    with runtime.borrow(reference) as first, runtime.borrow(reference) as second:
        assert np.shares_memory(
            first.chunk(0, 1)["positions"], second.chunk(0, 1)["positions"]
        )
        assert int(first.chunk(0, 1)["label"][0, 0]) == 2**64 - 1
        assert arena.request_reclaim(receipt) == "revoking"
    assert calls == ["acquire"] and runtime.budget.used == 48
    assert scope.close() == () and runtime.budget.used == 0
    assert arena.request_reclaim(receipt) == "released"
    with pytest.raises(RuntimeError, match="结束"):
        first.chunk(0, 1)
    with pytest.raises(RuntimeError, match="不可用"):
        with runtime.borrow(reference):
            pass


@pytest.mark.parametrize(
    "change",
    [
        {"run_id": "other"},
        {"cloud_id": "other"},
        {"revision": 2},
        {"point_count": 5},
        {"observation_id": "other"},
        {"spatial": spatial().model_copy(update={"frame_id": "other"})},
    ],
)
def test_changed_reference_cannot_access_registered_storage(change):
    scope = ResourceScope(kind="workflow")
    runtime = get_cloud_runtime(scope, run_id="run", policy=policy())
    reference, _ = root_cloud(runtime)
    try:
        forged = CloudReference.model_validate({**reference.model_dump(), **change})
        with pytest.raises(InvalidRequestError, match="引用"):
            with runtime.borrow(forged):
                pass
        with pytest.raises(InvalidRequestError, match="身份"):
            get_cloud_runtime(scope, run_id="other", policy=policy())
        other_scope = ResourceScope(kind="other")
        other = get_cloud_runtime(other_scope, run_id="other", policy=policy())
        with pytest.raises(InvalidRequestError, match="引用"):
            with other.borrow(reference):
                pass
        assert other_scope.close() == ()
    finally:
        assert scope.close() == ()


def test_subsets_keep_root_order_even_after_materialized_transform():
    scope = ResourceScope(kind="workflow")
    runtime = get_cloud_runtime(scope, run_id="run", policy=policy())
    root, _ = root_cloud(runtime)
    first = runtime.register_subset(
        parent=root,
        method=method(),
        indices=own(runtime, {"indices": np.array([[1], [3], [5]], dtype=np.uint32)}),
        cancel=lambda: None,
    )
    materialized = own(
        runtime,
        {"positions": np.arange(18, dtype=np.float32).reshape(6, 3)[[1, 3, 5]] * 2},
    )
    transformed = runtime.register_derived(
        parent=first,
        method=method(True),
        owner=materialized,
        fields=first.fields,
        spatial=first.spatial,
        cancel=lambda: None,
    )
    second = runtime.register_subset(
        parent=transformed,
        method=method(),
        indices=own(runtime, {"indices": np.array([[0], [2]], dtype=np.uint32)}),
        cancel=lambda: None,
    )
    with runtime.borrow(second) as view:
        np.testing.assert_array_equal(view.source_indices(0, 2), [1, 5])
        np.testing.assert_array_equal(
            view.chunk(0, 2)["positions"], [[6, 8, 10], [30, 32, 34]]
        )
    empty = runtime.register_subset(
        parent=second,
        method=method(),
        indices=own(runtime, {"indices": np.empty((0, 1), dtype=np.uint32)}),
        cancel=lambda: None,
    )
    assert empty.point_count == 0 and empty.state == "ready"
    with runtime.borrow(empty) as view:
        assert view.chunk(0, 0)["positions"].shape == (0, 3)
    assert scope.close() == () and runtime.budget.used == 0


@pytest.mark.parametrize("indices", [[1, 1], [3, 2], [1, 6]])
def test_invalid_subset_is_not_published(indices):
    scope = ResourceScope(kind="workflow")
    runtime = get_cloud_runtime(scope, run_id="run", policy=policy())
    root, _ = root_cloud(runtime)
    with pytest.raises(InvalidRequestError, match="递增"):
        runtime.register_subset(
            parent=root,
            method=method(),
            indices=own(
                runtime, {"indices": np.array(indices, dtype=np.uint32).reshape(-1, 1)}
            ),
            cancel=lambda: None,
        )
    assert scope.close() == () and runtime.budget.used == 0


def test_live_borrow_blocks_external_release_and_permanently_isolates_scope():
    scope, process = ResourceScope(kind="workflow"), ResourceScope(kind="process")
    runtime = get_cloud_runtime(scope, run_id="run", policy=policy())
    reference, owner = root_cloud(runtime)
    borrowed = runtime.borrow(reference)
    borrowed.__enter__()
    error = finalize_workflow_resources(
        scope=scope,
        process_scope=process,
        cleanup_external=lambda: pytest.fail("underlying resource must remain owned"),
        execution_error=None,
    )
    assert isinstance(error, WorkflowResourceCleanupError)
    assert not owner.closed and runtime.budget.used == 72
    borrowed.__exit__(None, None, None)
    with pytest.raises(RuntimeError, match="不可用"):
        with runtime.borrow(reference):
            pass
    assert scope.close_errors and scope.close() == scope.close_errors


def test_decoder_before_publication_is_also_an_active_resource():
    scope, process = ResourceScope(kind="workflow"), ResourceScope(kind="process")
    runtime = get_cloud_runtime(scope, run_id="run", policy=policy())
    with runtime.producing():
        error = finalize_workflow_resources(
            scope=scope,
            process_scope=process,
            cleanup_external=lambda: pytest.fail("decoder still owns its input"),
            execution_error=None,
        )
        assert isinstance(error, WorkflowResourceCleanupError)
    with pytest.raises(RuntimeError, match="不可用"):
        with runtime.producing():
            pass


def test_guard_close_failure_preserves_guard_and_budget_after_generator_exits():
    scope, process = ResourceScope(kind="workflow"), ResourceScope(kind="process")
    runtime = get_cloud_runtime(scope, run_id="run", policy=policy())
    exits = []

    class Guard:
        def __enter__(self):
            self.view = memoryview(payload())
            return self.view

        def __exit__(self, *_):
            exits.append("exit")
            self.view.release()
            raise BufferError("controlled mapping failure")

    runtime.open_local(
        descriptor=descriptor(),
        expected_descriptor_sha256=cloud_descriptor_sha256(descriptor()),
        acquire_view=Guard,
        cancel=lambda: None,
    )
    error = finalize_workflow_resources(
        scope=scope,
        process_scope=process,
        cleanup_external=lambda: pytest.fail("must not release lease"),
        execution_error=None,
    )
    assert isinstance(error, WorkflowResourceCleanupError)
    assert runtime.budget.used == 48 and runtime.storage_scope.resource_count == 1
    assert scope.close() and exits == ["exit"]


def test_reference_contract_state_and_parameter_hash_are_strict():
    params = FilterCloudValid(finite_fields=("positions",), sentinels=())
    with pytest.raises(ValueError, match="摘要"):
        CloudProvenance(
            method=FilterCloudMethod(
                method_id="filter-valid",
                method_version=1,
                parameters=params,
                parameters_sha256="0" * 64,
            ),
            parents=({"cloud_id": "p", "revision": 1},),
            source_retained=False,
        )
    scope = ResourceScope(kind="workflow")
    runtime = get_cloud_runtime(scope, run_id="run", policy=policy())
    root, _ = root_cloud(runtime)
    with pytest.raises(ValueError, match="unavailable"):
        CloudReference.model_validate(
            {**root.model_dump(), "state": "unavailable", "reason": "datum_missing"}
        )
    assert scope.close() == ()


def test_snapshot_failure_drops_traceback_views_before_closing_real_mapping(
    arena_input, monkeypatch
):
    """算法异常可以保留诊断，但已退栈的 ndarray 不能迫使正常 guard 隔离。"""
    from types import SimpleNamespace
    import weakref
    from backend.service.application.runtime.resource_scope import (
        get_or_create_workflow_resource_scope,
    )
    from backend.service.application.workflows.snapshot_execution import (
        SnapshotExecutionService,
        WorkflowSnapshotExecutionRequest,
    )

    arena, receipt, acquire = arena_input
    service = object.__new__(SnapshotExecutionService)
    service.runtime_context = SimpleNamespace(
        process_resource_scope=ResourceScope(kind="process")
    )
    retained = []
    runtimes = []

    def graph(*, request, model_session_scope_id):
        runtime = get_cloud_runtime(
            get_or_create_workflow_resource_scope(request.execution_metadata),
            run_id="run",
            policy=policy(),
        )
        runtimes.append(runtime)
        reference = runtime.open_local(
            descriptor=descriptor(),
            expected_descriptor_sha256=cloud_descriptor_sha256(descriptor()),
            acquire_view=acquire,
            cancel=lambda: None,
        )
        with runtime.borrow(reference) as view:
            matrix = view.chunk(0, 1)["positions"]
            retained.append(weakref.ref(matrix))
            raise InvalidRequestError("controlled algorithm error")

    monkeypatch.setattr(service, "_execute_snapshot_graph", graph)
    with pytest.raises(
        InvalidRequestError, match="controlled algorithm error"
    ) as error:
        service._execute_in_model_session_scope(
            request=WorkflowSnapshotExecutionRequest(
                project_id="p",
                application_id="a",
                application_snapshot_object_key="a",
                template_snapshot_object_key="t",
            ),
            model_session_scope_id="model",
        )
    assert error.value.__traceback__ is not None
    assert retained[0]() is None and runtimes[0].budget.used == 0
    assert arena.request_reclaim(receipt) == "released"
    assert not service.runtime_context.process_resource_scope.close_errors
