"""数值交付不依赖显示副本；使用真实测量节点和已有 core 输出节点。"""

from types import SimpleNamespace
from pathlib import Path
import json
import platform

import numpy as np
import pytest

from backend.contracts.workflows.workflow_graph import WorkflowGraphTemplate
from backend.nodes.core_nodes.io.output.response import response_envelope
from backend.nodes.core_nodes.io.preview import value_preview
from backend.nodes.core_nodes.logic.value import (
    numeric_table_to_value,
    numeric_tables_merge,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.resource_scope import (
    WORKFLOW_RESOURCE_SCOPE_METADATA_KEY,
)
from backend.service.application.workflows.graph_executor import WorkflowGraphExecutor
from backend.service.application.workflows.runtime_preview import (
    PREVIEW_CAPTURE_KEY,
    RuntimePreviewCapture,
)
from backend.service.application.workflows.service_runtime.context import (
    WorkflowServiceNodeRuntimeContext,
)
from tests.integration.metrology3d.measurement_output import connect_measurement_output
from tests.integration.metrology3d.test_measurement_nodes import measurement_graph
from tests.integration.metrology3d.test_nodes import build_chain, execution_policy
from tests.point_cloud_support import create_resource_service, policy
from tests.test_metrology3d_preprocess import make_cloud
from tests.test_metrology3d_preview import preview_policy


def measurement_registry():
    """注册原有生产 handler，不用测试 handler 伪造算法或显示成功。"""
    registry, _ = build_chain()
    for module in (
        response_envelope,
        value_preview,
        numeric_table_to_value,
        numeric_tables_merge,
    ):
        spec = module.CORE_NODE_SPEC
        registry.register_python_callable(spec.node_definition, spec.handler)
    return registry


@pytest.mark.parametrize("good", [True, False])
def test_numeric_output_survives_display_failures_and_absent_observer(tmp_path, good):
    """同一冻结输入在无订阅、正常显示、云预算拒绝和捕获超限下返回相同数值。"""
    io = policy(max_working_bytes=1024 * 1024)
    scope, runtime, cloud = make_cloud(
        unit="mm",
        runtime_policy=io,
        coordinates=np.array(
            [
                (x, y, z)
                for z in ((0, 5) if good else (0,))
                for x in (-1, 0, 1)
                for y in (-1, 0, 1)
            ],
            dtype=np.float32,
        ),
    )
    template = measurement_graph(read=False).model_dump(mode="json")
    connect_measurement_output(template, ("height", "step"))
    graph = WorkflowGraphTemplate.model_validate(template)
    service = create_resource_service(tmp_path)
    responses = []
    try:
        for mode in ("unobserved", "normal", "cloud-budget", "capture-budget"):
            capture = None if mode == "unobserved" else RuntimePreviewCapture()
            if mode == "capture-budget":
                capture.budget[0] = 1
            metadata = {
                "project_id": "test",
                "workflow_run_id": "run",
                WORKFLOW_RESOURCE_SCOPE_METADATA_KEY: scope,
            }
            if capture is not None:
                metadata[PREVIEW_CAPTURE_KEY] = capture
            configured = execution_policy().model_copy(
                update={
                    "io": io,
                    "preview": preview_policy(
                        max_points=18,
                        max_data_bytes=1 if mode == "cloud-budget" else 65536,
                        max_body_bytes=131072,
                    ),
                }
            )
            result = WorkflowGraphExecutor(registry=measurement_registry()).execute(
                template=graph,
                input_values={
                    item.input_id: cloud.model_dump(mode="json")
                    for item in graph.template_inputs
                },
                execution_metadata=metadata,
                runtime_context=WorkflowServiceNodeRuntimeContext(
                    session_factory=None,
                    dataset_storage=service.storage,
                    point_cloud_policy=configured,
                ),
            )
            body = result.outputs["body"]
            assert body["message"] == "measured"
            assert body["data"]["observation_id"] == cloud.observation_id
            assert set(body["data"]) == {"observation_id", "values", "items"}
            assert body["data"]["values"] == {
                "height": 5 if good else None,
                "step": 5 if good else None,
            }
            assert all(item["valid"] == good for item in body["data"]["items"])
            assert all(
                (item["reason"] is None) == good for item in body["data"]["items"]
            )
            responses.append(body)
            if capture is not None:
                if mode in {"cloud-budget", "capture-budget"}:
                    assert (
                        capture.error.code == "preview_size_limit"
                        and not capture.records
                    )
                else:
                    assert capture.error is None
                    displayed = capture.records[("preview", "body")]["payload"]
                    assert displayed["state"] == "ready"
                    assert (
                        capture.records[("table", "body")]["payload"]["rows"]
                        == body["data"]["items"]
                    )
        assert responses == [responses[0]] * 4
    finally:
        assert not scope.close()
        assert runtime.budget.used == 0


@pytest.mark.parametrize("conflict", ["item", "observation"])
def test_numeric_output_rejects_cross_object_or_observation_conflicts(conflict):
    """公开合并处理器不能覆盖重名结果或把旧运行结果混入当前响应。"""
    first = dict(
        observation_id="one",
        items=[dict(item_id="A.H", value=1, unit="mm", valid=True)],
    )
    second = dict(
        observation_id="two" if conflict == "observation" else "one",
        items=[
            dict(
                item_id="B.H" if conflict == "observation" else "A.H",
                value=None,
                unit="mm",
                valid=False,
                reason="no_support",
            )
        ],
    )
    with pytest.raises(InvalidRequestError):
        numeric_tables_merge.handle_node(
            SimpleNamespace(input_values={"tables": (first, second)})
        )


@pytest.mark.parametrize("whole", [False, True], ids=["representative", "workpiece"])
def test_representative_file_numeric_response(tmp_path, request, whole):
    """完整 PLY 经真实文件入口、全部代表节点和数值输出；同时检查有界显示。"""
    from backend.service.application.runtime.resource_scope import (
        get_or_create_workflow_resource_scope,
    )
    from backend.service.application.workflows.point_cloud.runtime import (
        get_cloud_runtime,
    )
    from tests.integration.metrology3d.representative_workflow import (
        check_representative_body,
        representative_documents,
        representative_policy,
    )
    from tests.integration.metrology3d.test_transport_full_sample import (
        FILE_SHA,
        POINTS,
    )
    from tests.integration.metrology3d.workpiece_workflow import (
        workpiece_documents,
        check_workpiece_body,
    )
    from time import monotonic

    supplied = request.config.getoption("--cloud-sample")
    if not supplied:
        pytest.skip("完整样本必须显式提供")
    service = create_resource_service(tmp_path)
    with Path(supplied).open("rb") as stream:
        meta = service.storage.write_immutable_stream(
            object_prefix="projects/test/results/cloud",
            source_stream=stream,
            media_type="application/octet-stream",
            extension="ply",
        ).metadata
    assert meta.checksum == FILE_SHA
    file = dict(
        transport_kind="storage",
        storage_ref="object-store",
        object_key=meta.object_key,
        file_name="sample.ply",
        media_type=meta.media_type,
        content_length=meta.content_length,
        checksum_algorithm="sha256",
        checksum=meta.checksum,
        immutable_version=meta.immutable_version,
    )
    configured = representative_policy()
    capture = RuntimePreviewCapture()
    metadata = {
        "project_id": "test",
        "workflow_run_id": "r5-output",
        PREVIEW_CAPTURE_KEY: capture,
        "retain_node_records_enabled": False,
    }
    scope = get_or_create_workflow_resource_scope(metadata)
    runtime = get_cloud_runtime(scope, run_id="r5-output", policy=configured.io)
    try:
        template, _ = (workpiece_documents if whole else representative_documents)(
            file=True
        )
        started = monotonic()
        result = WorkflowGraphExecutor(registry=measurement_registry()).execute(
            template=template,
            input_values={"input": file},
            execution_metadata=metadata,
            runtime_context=WorkflowServiceNodeRuntimeContext(
                session_factory=None,
                dataset_storage=service.storage,
                point_cloud_policy=configured,
            ),
        )
        body = result.outputs["body"]
        (check_workpiece_body if whole else check_representative_body)(body)
        assert capture.error is None
        cloud = capture.records[("preview", "body")]["payload"]
        assert cloud["source_point_count"] == POINTS
        assert cloud["display_point_count"] == 500000
        assert cloud["observation_id"] == body["data"]["observation_id"]
        assert (
            capture.records[("table", "body")]["payload"]["rows"]
            == body["data"]["items"]
        )
        report = dict(
            platform=platform.platform(),
            file_sha256=FILE_SHA,
            source_points=POINTS,
            body=body,
            response_body_bytes=len(json.dumps(body).encode()),
            preview_values_used=100000 - capture.budget[1],
            preview_accounted_bytes=64 * 1024 * 1024 - 16384 - capture.budget[0],
            display_points=cloud["display_point_count"],
            preview_error=None,
            elapsed_seconds=monotonic() - started,
            node_timings={
                record.node_id: record.duration_ms for record in result.node_records
            },
        )
    finally:
        assert not scope.close()
        assert runtime.budget.used == 0
    report["resources_released"] = True
    target = request.config.getoption("--cloud-report-dir")
    if target:
        directory = Path(target)
        directory.mkdir(parents=True, exist_ok=True)
        (
            directory
            / f"numeric-{'workpiece' if whole else 'file'}-{platform.system().lower()}.json"
        ).write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
