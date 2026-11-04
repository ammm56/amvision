"""实写大载荷的显示索引与全字段原始行验证，不复跑无关传输矩阵。"""

import errno

import pytest

from backend.service.application.errors import PersistenceOperationError
from backend.service.application.runtime.resource_scope import ResourceScope
from backend.service.application.workflows.point_cloud.detail_index import (
    index_root,
    prepare_index,
    read_index,
)
from backend.service.application.workflows.point_cloud.runtime import get_cloud_runtime
from custom_nodes.metrology3d_nodes.shared.cloud_assets import read_asset
from tests.point_cloud_support import create_resource_service
from tests.integration.metrology3d.capacity_support import (
    read_options,
    report,
    settings,
    stage,
    write_ply,
)
from tests.integration.metrology3d.detail_acceptance import save_sample, verify


def test_exact_capacity_index_and_failed_rebuild(tmp_path, request, monkeypatch):
    """正式资源服务构建，取消和磁盘写失败后旧代次仍可完整读取。"""
    policy = settings().workflow_runtime.point_cloud
    size = request.config.getoption("--cloud-capacity-bytes")
    service = create_resource_service(tmp_path)
    with report(request, "details") as evidence:
        source = tmp_path / "capacity.ply"
        with stage(evidence, "generate"):
            count = write_ply(source, size)
        with stage(evidence, "save_asset"):
            reference = save_sample(
                service, source, policy, file_options=read_options()
            )
        scope = ResourceScope(kind="test")
        runtime = get_cloud_runtime(scope, run_id="capacity-details", policy=policy.io)
        try:
            cloud = read_asset(
                runtime,
                reference,
                service=service,
                project_id="project-1",
                policy=policy.assets(),
                cancel=lambda: None,
            )
            baseline = runtime.budget.used

            def build(cancel=lambda: None):
                return prepare_index(
                    runtime,
                    cloud,
                    service=service,
                    project_id="project-1",
                    policy=policy,
                    cancel=cancel,
                )

            with stage(evidence, "build_index"):
                index = build()
            assert runtime.budget.used == baseline
            assert index.point_count == count and index.row_bytes == 24
            evidence.update(
                point_count=count,
                data_bytes=sum(b.byte_length for b in index.blocks),
                block_count=len(index.blocks),
                logical_dtype=index.logical_dtype,
                identity_dtype=index.identity_dtype,
                previous_reserve_bytes=count * 192,
            )
            with stage(evidence, "verify_every_field"):
                evidence["complete"] = verify(service, reference, policy)

            original = service.storage.write_immutable_stream
            written = False

            def record_write(**kwargs):
                nonlocal written
                receipt = original(**kwargs)
                written = True
                return receipt

            def cancel():
                if written:
                    raise RuntimeError("cancel after first complete leaf")

            with stage(evidence, "cancel_after_leaf"):
                with monkeypatch.context() as patch:
                    patch.setattr(
                        service.storage, "write_immutable_stream", record_write
                    )
                    with pytest.raises(RuntimeError, match="cancel after"):
                        build(cancel)
            assert written and runtime.budget.used == baseline
            assert (
                read_index(
                    service, reference, project_id="project-1", policy=policy.preview
                )
                == index
            )

            def disk_full(**kwargs):
                original(**kwargs)
                raise OSError(errno.ENOSPC, "injected detail disk write failure")

            with stage(evidence, "disk_full_after_leaf"):
                with monkeypatch.context() as patch:
                    patch.setattr(service.storage, "write_immutable_stream", disk_full)
                    with pytest.raises(PersistenceOperationError) as failure:
                        build()
                assert failure.value.details["errno"] == errno.ENOSPC
            assert runtime.budget.used == baseline
            root = service.storage.resolve(index_root(service, reference))
            assert len(list(root.iterdir())) == 2 and not list(root.rglob("*.rows"))
            assert (
                read_index(
                    service, reference, project_id="project-1", policy=policy.preview
                )
                == index
            )
            with stage(evidence, "rebuild_after_failures"):
                next_index = build()
                assert next_index.generation != index.generation
            assert runtime.budget.used == baseline and len(list(root.iterdir())) == 2
            with stage(evidence, "verify_recovered_index"):
                evidence["recovered"] = verify(service, reference, policy)
            evidence["cancelled_generation_removed"] = True
            evidence["disk_failure_rolled_back"] = True
        finally:
            assert not scope.close() and runtime.budget.used == 0
        evidence["released_budget_bytes"] = runtime.budget.used
