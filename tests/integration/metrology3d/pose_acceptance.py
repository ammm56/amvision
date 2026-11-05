"""B05 完整工件真实发布与逐行回查；可保留隔离服务供页面操作。"""

import argparse
import json
from pathlib import Path
from time import perf_counter
import numpy as np

from backend.contracts.workflows.workflow_graph import WorkflowGraphTemplate
from backend.contracts.workflows.point_cloud_runtime import CloudReference
from backend.service.application.runtime.resource_scope import (
    get_or_create_workflow_resource_scope,
)
from backend.service.application.workflows.point_cloud.runtime import get_cloud_runtime
from backend.service.application.workflows.graph_executor import WorkflowGraphExecutor
from backend.service.application.workflows.service_runtime.context import (
    WorkflowServiceNodeRuntimeContext,
)
from backend.service.application.workflows.documents.measurement_resources import (
    MeasurementResourceService,
)
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
    DatasetStorageSettings,
)
from tests.integration.metrology3d.capacity_support import settings
from tests.integration.metrology3d.detail_acceptance import save_sample
from tests.integration.metrology3d.pose_documents import pose_documents
from tests.integration.metrology3d.package_acceptance import serve
from tests.integration.metrology3d.published_support import published_system
from tests.integration.metrology3d.test_nodes import build_chain


def check_rows(system, service, template, policy):
    """同一正式节点图补只读结果端口，用完整输入逐行验证，不替换 handler。"""
    graph = template.model_dump(mode="json")
    for key in ("filter", "restored"):
        graph["template_outputs"].append(
            dict(
                output_id=key,
                display_name=key,
                payload_type_id="point-cloud-ref.v1",
                source_node_id=key,
                source_port="cloud",
            )
        )
    metadata = dict(project_id="project-1", workflow_run_id="pose-row-audit")
    scope = get_or_create_workflow_resource_scope(metadata)
    runtime = get_cloud_runtime(scope, run_id="pose-row-audit", policy=policy.io)
    try:
        registry, _ = build_chain()
        output = WorkflowGraphExecutor(registry=registry).execute(
            template=WorkflowGraphTemplate.model_validate(graph),
            input_values={},
            execution_metadata=metadata,
            runtime_context=WorkflowServiceNodeRuntimeContext(
                session_factory=None,
                dataset_storage=service.storage,
                point_cloud_policy=policy,
            ),
        )
        before = CloudReference.model_validate(output.outputs["filter"])
        after = CloudReference.model_validate(output.outputs["restored"])
        assert before.point_count == after.point_count == 14745099
        assert before.fields == after.fields
        error = 0.0
        with runtime.borrow(before) as a, runtime.borrow(after) as b:
            for start in range(0, before.point_count, policy.io.chunk_rows):
                stop = min(start + policy.io.chunk_rows, before.point_count)
                first, second = (
                    a.chunk(start, stop)["positions"],
                    b.chunk(start, stop)["positions"],
                )
                np.testing.assert_array_equal(
                    a.source_indices(start, stop), b.source_indices(start, stop)
                )
                error = max(
                    error,
                    float(np.max(np.abs(first.astype("f8") - second.astype("f8")))),
                )
        # 两次 f32 写回的舍入检查，不作为工件公差或质量条件。
        assert error < 0.00005
        assert runtime.source_point_count(after) == 14745099
        return dict(point_count=before.point_count, max_roundtrip_float32_error=error)
    finally:
        assert scope.close() == () and runtime.budget.used == 0


def main():
    """数据与服务均处于独立目录，测试端口禁止使用业务5600/5601。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--sample", type=Path, required=True)
    parser.add_argument("--serve", type=int)
    args = parser.parse_args()
    if args.serve is not None and (
        args.serve in (5600, 5601) or not 1024 <= args.serve <= 65535
    ):
        parser.error("必须使用隔离端口")
    args.root.mkdir(parents=True, exist_ok=False)
    policy = settings().workflow_runtime.point_cloud
    with published_system(args.root / "system", point_cloud_policy=policy) as system:
        service = MeasurementResourceService(
            LocalDatasetStorage(
                DatasetStorageSettings(
                    root_dir=system.settings.dataset_storage.root_dir
                )
            )
        )
        reference = save_sample(service, args.sample, policy)
        documents = pose_documents(reference=reference, complete=True)
        report = check_rows(system, service, documents[0], policy)
        version = system.publish(point_limit=100000, documents=documents)
        system.start(version)
        started = perf_counter()
        run = system.call(
            "POST",
            f"/app-runtimes/{system.runtime_id}/invoke",
            json=dict(
                input_bindings={},
                execution_metadata={"workflow_run_record_mode": "full"},
            ),
        )
        assert run["state"] == "succeeded", run
        body = run["results"]["body"]
        assert body["point_count"] == 14745099
        frame = body["geometry"]["frame"]
        assert frame["state"] == "found"
        np.testing.assert_allclose(frame["transform"]["matrix"], np.eye(4), atol=1e-10)
        report.update(
            version=version,
            published_seconds=perf_counter() - started,
            quality=frame["quality"],
            runtime_id=system.runtime_id,
        )
        system.assert_reclaimed()
        system.call("POST", f"/app-runtimes/{system.runtime_id}/stop")
        (args.root / "report.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )
        print(json.dumps(report), flush=True)
        if args.serve:
            serve(system, args.root, args.serve)


if __name__ == "__main__":
    main()
