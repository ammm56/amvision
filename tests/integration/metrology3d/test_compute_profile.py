"""F0 纯计算边界与完整样本基线，不把传输/读取时间混入算法验收。"""

import json
import platform
from pathlib import Path
from time import perf_counter

import pytest

from backend.service.application.runtime.resource_scope import (
    WORKFLOW_RESOURCE_SCOPE_METADATA_KEY,
    ResourceScope,
)
from backend.service.application.workflows.graph_executor import WorkflowGraphExecutor
from backend.service.application.workflows.point_cloud.runtime import get_cloud_runtime
from backend.service.application.workflows.service_runtime.context import (
    WorkflowServiceNodeRuntimeContext,
)
from custom_nodes.metrology3d_nodes.shared.io.read_file import read_file_reference
from tests.integration.metrology3d.compute_profile import (
    numerical_graph,
    summarize_compute,
)
from tests.integration.metrology3d.representative_workflow import representative_policy
from tests.integration.metrology3d.test_measurement_output import measurement_registry
from tests.integration.metrology3d.test_transport_full_sample import FILE_SHA, POINTS
from tests.integration.metrology3d.workpiece_workflow import (
    workpiece_documents,
    check_workpiece_body,
)
from tests.point_cloud_support import create_resource_service, options


def test_numerical_graph_preserves_measurement_parameters():
    """显示开关不改算法、接线、输出定义或正式输入。"""
    full, _ = workpiece_documents()
    numeric = numerical_graph(full)
    before = {n.node_id: n for n in full.nodes}
    assert len(numeric.nodes) == len(full.nodes) - 2
    assert all(n == before[n.node_id] for n in numeric.nodes)
    assert numeric.template_inputs == full.template_inputs
    assert numeric.template_outputs == full.template_outputs
    assert all("preview" not in n.node_type_id for n in numeric.nodes)


def test_full_sample_compute_profile(tmp_path, request):
    """完整读取一次后执行纯数值图，保留原结果矩阵作同算法优化基线。"""
    sample = request.config.getoption("--cloud-sample")
    if not sample:
        pytest.skip("完整样本必须显式提供")
    service = create_resource_service(tmp_path)
    staged = perf_counter()
    with Path(sample).open("rb") as stream:
        meta = service.storage.write_immutable_stream(
            object_prefix="projects/test/results/cloud",
            source_stream=stream,
            media_type="application/octet-stream",
            extension="ply",
        ).metadata
    assert meta.checksum == FILE_SHA
    staging_seconds = perf_counter() - staged
    configured = representative_policy()
    scope = ResourceScope(kind="workflow")
    runtime = get_cloud_runtime(scope, run_id="r5-f-compute", policy=configured.io)
    try:
        started = perf_counter()
        cloud = read_file_reference(
            runtime=runtime,
            object_store=service.storage,
            project_id="test",
            file=dict(
                transport_kind="storage",
                storage_ref="object-store",
                object_key=meta.object_key,
                file_name="sample.ply",
                media_type=meta.media_type,
                content_length=meta.content_length,
                checksum_algorithm="sha256",
                checksum=meta.checksum,
                immutable_version=meta.immutable_version,
            ),
            options=options(),
            cancel=lambda: None,
        )
        read_seconds = perf_counter() - started
        assert cloud.point_count == POINTS
        graph = numerical_graph(workpiece_documents()[0])
        registry = measurement_registry()
        context = WorkflowServiceNodeRuntimeContext(
            session_factory=None,
            dataset_storage=service.storage,
            point_cloud_policy=configured,
        )
        metadata = dict(
            project_id="test",
            workflow_run_id=runtime.run_id,
            retain_node_records_enabled=False,
        )
        metadata[WORKFLOW_RESOURCE_SCOPE_METADATA_KEY] = scope
        started = perf_counter()
        result = WorkflowGraphExecutor(registry=registry).execute(
            template=graph,
            input_values={"input": cloud.model_dump(mode="json")},
            execution_metadata=metadata,
            runtime_context=context,
        )
        elapsed = perf_counter() - started
        check_workpiece_body(result.outputs["body"])
        report = dict(
            platform=platform.platform(),
            file_sha256=FILE_SHA,
            source_points=POINTS,
            staging_seconds=staging_seconds,
            read_seconds=read_seconds,
            compute=summarize_compute(graph, result, elapsed),
            body=result.outputs["body"],
            live_array_bytes=runtime.budget.used,
            display_enabled=False,
            scope="same-method-regression-not-new-envelope",
        )
    finally:
        assert not scope.close()
        assert runtime.budget.used == 0
    report["resources_released"] = True
    destination = request.config.getoption("--cloud-report-dir")
    if destination:
        path = Path(destination)
        path.mkdir(parents=True, exist_ok=True)
        (path / f"compute-{platform.system().lower()}.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
