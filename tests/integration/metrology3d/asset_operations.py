"""固定资产在真实发布链路中的版本冲突、恢复和交换重读验收。"""

import argparse
import json
from pathlib import Path
import platform
import os
from contextlib import contextmanager
from threading import Event, Thread
from time import perf_counter


def operation_documents(reference, operation):
    """复用资产显示图，仅接入已有保存或导出节点，不替换 handler。"""
    from backend.contracts.workflows.workflow_graph import WorkflowGraphTemplate
    from tests.integration.metrology3d.detail_acceptance import documents

    template, app = documents(reference)
    graph = template.model_dump(mode="json")
    graph["nodes"][1]["parameters"]["prepare_details"] = False
    if operation == "save":
        parameters = dict(
            mode="derived",
            target=dict(
                kind="new-version",
                name="Full workpiece saved",
                reference=reference.model_dump(mode="json"),
            ),
        )
    elif operation == "export":
        parameters = dict(
            source=dict(kind="cloud"),
            profile_id="ply-binary-le",
            profile_version=1,
            fields=["positions"],
            file_name="workpiece.ply",
            spatial_acknowledged=True,
        )
    else:
        assert operation == "view"
        return WorkflowGraphTemplate.model_validate(graph), app
    graph["nodes"].append(
        dict(
            node_id=operation,
            node_type_id=f"custom.metrology3d.{operation}-cloud",
            parameters=parameters,
        )
    )
    graph["edges"].append(
        dict(
            edge_id=operation,
            source_node_id="read",
            source_port="cloud",
            target_node_id=operation,
            target_port="cloud",
        )
    )
    return WorkflowGraphTemplate.model_validate(graph), app


def select(system, reference, operation):
    """停机选择真实发布版本；不以手改运行快照绕过准入。"""
    version = system.publish(
        point_limit=100000, documents=operation_documents(reference, operation)
    )
    if system.runtime_id is not None:
        stopped = system.call("POST", f"/app-runtimes/{system.runtime_id}/stop")
        assert stopped["observed_state"] == "stopped"
        system.call(
            "POST",
            f"/app-runtimes/{system.runtime_id}/select-version",
            json=dict(
                workflow_app_version_id=version,
                expected_generation=stopped["revision_generation"],
            ),
        )
    started = system.start(version)
    if not hasattr(system, "asset_worker_pids"):
        system.asset_worker_pids = []
    system.asset_worker_pids.append(started["worker_process_id"])
    return version


def invoke(system, *, expected="succeeded"):
    """真实独立 worker 执行，随后核对租约与准入释放。"""
    run = system.call(
        "POST",
        f"/app-runtimes/{system.runtime_id}/invoke",
        json=dict(input_bindings={}, execution_metadata={}),
    )
    assert run["state"] == expected, run
    system.assert_reclaimed()
    return run


def verify_export(service, reference, policy, exported):
    """交换重读和资产逐字段逐行相等，范围有限的预览不作为精度证据。"""
    import numpy as np

    from backend.service.application.runtime.resource_scope import ResourceScope
    from backend.service.application.workflows.point_cloud.runtime import (
        get_cloud_runtime,
    )
    from custom_nodes.metrology3d_nodes.shared.cloud_assets import read_asset
    from custom_nodes.metrology3d_nodes.shared.io.read_file import read_file_reference
    from tests.point_cloud_support import options

    metadata = service.storage.stat_object(
        exported.relative_to(service.storage.root_dir).as_posix()
    )
    file = dict(
        transport_kind="storage",
        storage_ref="object-store",
        object_key=metadata.object_key,
        file_name="workpiece.ply",
        media_type=metadata.media_type,
        content_length=metadata.content_length,
        checksum_algorithm="sha256",
        checksum=metadata.checksum,
        immutable_version=metadata.immutable_version,
    )
    scope = ResourceScope(kind="workflow")
    runtime = get_cloud_runtime(scope, run_id="asset-roundtrip", policy=policy.io)
    try:
        cloud = read_asset(
            runtime,
            reference,
            service=service,
            project_id="project-1",
            policy=policy.assets(),
            cancel=lambda: None,
        )
        reread = read_file_reference(
            runtime=runtime,
            object_store=service.storage,
            project_id="project-1",
            file=file,
            options=options("ply-binary-le"),
            cancel=lambda: None,
        )
        assert reread.point_count == cloud.point_count
        with runtime.borrow(cloud) as left, runtime.borrow(reread) as right:
            for start in range(0, cloud.point_count, runtime.policy.chunk_rows):
                stop = min(start + runtime.policy.chunk_rows, cloud.point_count)
                a, b = left.chunk(start, stop), right.chunk(start, stop)
                assert set(a) == set(b) == {"positions"}
                assert a["positions"].dtype == b["positions"].dtype
                np.testing.assert_array_equal(a["positions"], b["positions"])
                np.testing.assert_array_equal(
                    left.source_indices(start, stop), right.source_indices(start, stop)
                )
                del a, b
        return cloud.point_count
    finally:
        assert not scope.close() and runtime.budget.used == 0


def exercise(system, service, reference, policy):
    """旧基版冲突保留已提交版本；显式重选后才能生成下一版本。"""
    select(system, reference, "save")
    first = invoke(system)
    versions = service.list_versions(project_id="project-1")
    assert len(versions) == 2
    second = next(d.reference for d in versions if d.reference.version == 2)
    snapshot = {
        p.relative_to(service.storage.root_dir)
        for p in service.storage.resolve(service.root("project-1")).rglob("*")
        if p.is_file()
    }
    conflict = invoke(system, expected="failed")
    assert conflict["error"]["code"] == "resource_conflict", conflict
    assert conflict["error"]["details"]["node_id"] == "save", conflict
    assert len(service.list_versions(project_id="project-1")) == 2
    assert snapshot == {
        p.relative_to(service.storage.root_dir)
        for p in service.storage.resolve(service.root("project-1")).rglob("*")
        if p.is_file()
    }
    select(system, second, "save")
    recovered = invoke(system)
    versions = service.list_versions(project_id="project-1")
    assert len(versions) == 3
    third = next(d.reference for d in versions if d.reference.version == 3)
    select(system, third, "export")
    exported = invoke(system)
    files = list(
        service.storage.resolve("projects/project-1/workflow-exports").rglob("*.bin")
    )
    assert len(files) == 1, files
    count = verify_export(service, third, policy, files[0])
    select(system, third, "view")
    invoke(system)
    return dict(
        platform=platform.platform(),
        point_count=count,
        saved_versions=[1, 2, 3],
        conflict_preserves_files=True,
        exact_export_roundtrip=True,
        resource_budget_released=True,
        reference=third.model_dump(mode="json"),
        runtime_id=system.runtime_id,
        worker_pids=system.asset_worker_pids,
        runs=[first, conflict, recovered, exported],
    )


@contextmanager
def observe_processes(root):
    """逐 PID 复用已有采样；不设置未经确认的资源门禁，不混入性能计时。"""
    from tests.integration.runtime_resource_gate import ResourceGate

    gate = ResourceGate(
        root_pids=(os.getpid(),), warmup_seconds=0, limits={}, include_processes=True
    )
    stop = Event()
    started = perf_counter()

    def sample():
        with (root / "resources.jsonl").open("w", encoding="utf-8") as stream:
            while not stop.is_set():
                stream.write(json.dumps(gate.sample(perf_counter() - started)) + "\n")
                stream.flush()
                stop.wait(0.25)

    thread = Thread(target=sample, name="asset-resource-observer", daemon=False)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join()
        (root / "resources-summary.json").write_text(
            json.dumps(gate.summary(), indent=2), encoding="utf-8"
        )


def main():
    """隔离完整样本验收；可保留进程供真实页面操作，停止文件负责正常退出。"""
    # spawn 重读主模块时不加载 API/测试容器，归属启动门仍使用生产预算。
    from backend.service.application.workflows.documents.measurement_resources import (
        MeasurementResourceService,
    )
    from backend.service.infrastructure.object_store.local_dataset_storage import (
        LocalDatasetStorage,
        DatasetStorageSettings,
    )
    from tests.integration.metrology3d.capacity_support import settings
    from tests.integration.metrology3d.detail_acceptance import save_sample
    from tests.integration.metrology3d.package_acceptance import serve
    from tests.integration.metrology3d.published_support import published_system

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--sample", type=Path, required=True)
    parser.add_argument("--serve", type=int)
    args = parser.parse_args()
    if args.serve and (args.serve in (5600, 5601) or not 1024 <= args.serve <= 65535):
        parser.error("必须使用隔离端口")
    root = args.root.resolve()
    root.mkdir(parents=True, exist_ok=False)
    policy = settings().workflow_runtime.point_cloud
    with (
        observe_processes(root),
        published_system(root, point_cloud_policy=policy) as system,
    ):
        service = MeasurementResourceService(
            LocalDatasetStorage(
                DatasetStorageSettings(
                    root_dir=system.settings.dataset_storage.root_dir
                )
            )
        )
        reference = save_sample(service, args.sample, policy)
        report = exercise(system, service, reference, policy)
        report["api_and_caller_pid"] = os.getpid()
        report["broker_pid"] = system.idle()[1].get("process_id")
        (root / "report.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )
        print(json.dumps({k: v for k, v in report.items() if k != "runs"}), flush=True)
        if args.serve:
            serve(system, root, args.serve)


if __name__ == "__main__":
    main()
