"""六节点真实执行器链路；只显式注册内部包，不启用生产 manifest。"""

from dataclasses import replace
import pytest
from backend.contracts.workflows.workflow_graph import WorkflowGraphTemplate
from backend.service.application.errors import (
    ServiceConfigurationError,
    InvalidRequestError,
)
from backend.service.application.runtime.resource_scope import (
    get_or_create_workflow_resource_scope,
)
from backend.service.application.workflows.service_runtime.context import (
    WorkflowServiceNodeRuntimeContext,
)
from backend.service.application.workflows.point_cloud.execution_policy import (
    PointCloudExecutionPolicy,
)
from backend.service.application.workflows.graph_executor import (
    WorkflowGraphExecutor,
    WorkflowNodeRuntimeRegistry,
    WorkflowNodeExecutionRequest,
)
from backend.service.application.workflows.runtime_preview import (
    RuntimePreviewCapture,
    PREVIEW_CAPTURE_KEY,
)
from custom_nodes._metrology3d_nodes.workflow.catalog_builder import (
    build_custom_node_catalog_document,
)
from custom_nodes._metrology3d_nodes.backend.entry import HANDLERS
from tests.point_cloud_support import create_resource_service, options, policy
from tests.test_metrology3d_preview import preview_policy, decode
from tests.integration.metrology3d.test_file_read import ply, publish


def execution_policy():
    """测试值不写入生产 JSON。"""
    return PointCloudExecutionPolicy(
        io=policy(),
        preview=preview_policy(),
        max_asset_bytes=8192,
        max_archive_bytes=16384,
        max_export_bytes=8192,
    )


def build_chain():
    """相同 Catalog 与 handler 进入项目原有 GraphExecutor。"""
    catalog = build_custom_node_catalog_document()
    registry = WorkflowNodeRuntimeRegistry()
    for definition in catalog.node_definitions:
        registry.register_python_callable(
            definition, HANDLERS[definition.node_type_id.rsplit(".", 1)[1]]
        )
    params = {
        "read-cloud": dict(
            source=dict(kind="file"), file_options=options().model_dump(mode="json")
        ),
        "normalize-units": dict(target_unit="mm"),
        "filter-valid": dict(finite_fields=["positions"], sentinels=[]),
        "cloud-preview": dict(point_limit=2, color=dict(mode="solid")),
        "save-cloud": dict(mode="derived", target=dict(kind="new", name="Sample")),
        "export-cloud": dict(
            source=dict(kind="cloud"),
            profile_id="ply-binary-le",
            profile_version=1,
            fields=["positions"],
            file_name="sample.ply",
            spatial_acknowledged=True,
        ),
    }
    links = [
        ("read-cloud", "normalize-units"),
        ("normalize-units", "filter-valid"),
        ("filter-valid", "cloud-preview"),
        ("filter-valid", "save-cloud"),
        ("filter-valid", "export-cloud"),
    ]
    template = WorkflowGraphTemplate.model_validate(
        dict(
            template_id="metrology3d-test",
            template_version="0.1.8",
            display_name="3D Metrology",
            nodes=[
                dict(node_id=k, node_type_id="custom.metrology3d." + k, parameters=p)
                for k, p in params.items()
            ],
            edges=[
                dict(
                    edge_id=str(i),
                    source_node_id=a,
                    source_port="cloud",
                    target_node_id=b,
                    target_port="cloud",
                )
                for i, (a, b) in enumerate(links)
            ],
            template_inputs=[
                dict(
                    input_id="file",
                    display_name="File",
                    payload_type_id="file-ref.v1",
                    target_node_id="read-cloud",
                    target_port="file",
                )
            ],
            template_outputs=[
                dict(
                    output_id=p,
                    display_name=p,
                    payload_type_id=t,
                    source_node_id=k,
                    source_port=p,
                )
                for k, p, t in (
                    ("cloud-preview", "body", "response-body.v1"),
                    ("save-cloud", "resource", "measurement-resource-ref.v1"),
                    ("export-cloud", "file", "file-ref.v1"),
                )
            ],
        )
    )
    return registry, template


def test_six_node_graph_and_persisted_asset_read(tmp_path):
    """真实读/归一/过滤/显示/保存/导出，并在新运行恢复持久引用。"""
    service = create_resource_service(tmp_path)
    context = WorkflowServiceNodeRuntimeContext(
        session_factory=None,
        dataset_storage=service.storage,
        point_cloud_policy=execution_policy(),
    )
    registry, template = build_chain()
    metadata = dict(project_id="test", workflow_run_id="nodes-run")
    capture = RuntimePreviewCapture()
    metadata[PREVIEW_CAPTURE_KEY] = capture
    scope = get_or_create_workflow_resource_scope(metadata)
    try:
        result = WorkflowGraphExecutor(registry=registry).execute(
            template=template,
            input_values={"file": publish(service.storage, ply())},
            execution_metadata=metadata,
            runtime_context=context,
        )
        assert len(result.node_records) == 6
        assert result.outputs["body"]["display_point_count"] == 2
        assert result.outputs["file"]["content_length"] > 0
        assert not capture.error and len(capture.records) == 1
    finally:
        assert not scope.close()
    assert decode(result.outputs["body"])["source_indices"][:, 0].tolist() == [0, 1]
    other = dict(project_id="test", workflow_run_id="restored")
    try:
        output = HANDLERS["read-cloud"](
            WorkflowNodeExecutionRequest(
                node_id="restored",
                node_definition=object(),
                parameters=dict(
                    source=dict(kind="asset", reference=result.outputs["resource"])
                ),
                execution_metadata=other,
                runtime_context=context,
            )
        )
        assert (
            output["cloud"]["point_count"] == 2
            and output["cloud"]["run_id"] == "restored"
        )
    finally:
        assert not get_or_create_workflow_resource_scope(other).close()


def test_missing_policy_and_conflicting_sources(tmp_path):
    """不配置策略时即便手工注册也不能运行；参数不得同时选择两入口。"""
    service = create_resource_service(tmp_path)
    context = WorkflowServiceNodeRuntimeContext(
        session_factory=None, dataset_storage=service.storage
    )
    request = WorkflowNodeExecutionRequest(
        node_id="read",
        node_definition=object(),
        parameters=dict(
            source=dict(kind="file"), file_options=options().model_dump(mode="json")
        ),
        execution_metadata=dict(project_id="test", workflow_run_id="test"),
        runtime_context=context,
    )
    with pytest.raises(ServiceConfigurationError):
        HANDLERS["read-cloud"](request)
    with pytest.raises((ValueError, InvalidRequestError)):
        HANDLERS["read-cloud"](
            replace(
                request,
                parameters=dict(
                    source=dict(kind="asset"),
                    file_options=options().model_dump(mode="json"),
                ),
            )
        )


def test_preview_budget_error_does_not_cancel_save_or_export(tmp_path):
    """实际执行器中显示超限独立报告，保存/导出仍提交，Scope 完整释放。"""
    service = create_resource_service(tmp_path)
    configured = execution_policy()
    configured = configured.model_copy(
        update={"preview": preview_policy(max_data_bytes=1)}
    )
    context = WorkflowServiceNodeRuntimeContext(
        session_factory=None,
        dataset_storage=service.storage,
        point_cloud_policy=configured,
    )
    registry, template = build_chain()
    capture = RuntimePreviewCapture()
    metadata = dict(
        project_id="test",
        workflow_run_id="display-error",
        **{PREVIEW_CAPTURE_KEY: capture},
    )
    scope = get_or_create_workflow_resource_scope(metadata)
    try:
        result = WorkflowGraphExecutor(registry=registry).execute(
            template=template,
            input_values={"file": publish(service.storage, ply())},
            execution_metadata=metadata,
            runtime_context=context,
        )
        assert len(result.node_records) == 6
        assert result.outputs["body"]["reason"] == "preview_size_limit"
        assert capture.error is not None and not capture.records
        assert result.outputs["resource"]["kind"] == "point-cloud"
        assert (
            service.storage.stat_object(
                result.outputs["file"]["object_key"]
            ).content_length
            > 0
        )
    finally:
        assert not scope.close()
