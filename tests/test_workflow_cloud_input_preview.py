"""实际输入预览仅执行必要上游，不执行当前未配置节点或保存支路。"""

from contextlib import closing
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.contracts.workflows.preview_session import PreviewExecutionScope
from backend.nodes.local_node_pack_loader import LocalNodePackLoader
from backend.nodes.node_catalog_registry import NodeCatalogRegistry
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.preview.input_scope import (
    input_preview_scope,
)
from backend.service.application.workflows.preview.execution import (
    PreviewMemoryExecutionService,
    PreviewMemoryExecutionRequest,
)
from backend.service.application.workflows.preview.display import PreviewDisplayCapture
from backend.service.application.workflows.preview.buffers import PreviewBuffers
from backend.service.application.workflows.runtime_registry_loader import (
    WorkflowNodeRuntimeRegistryLoader,
)
from backend.service.application.workflows.service_runtime.context import (
    WorkflowServiceNodeRuntimeContext,
)
from tests.metrology3d_transport_support import cloud_documents
from tests.point_cloud_support import options, create_resource_service
from tests.integration.metrology3d.test_nodes import execution_policy
from tests.integration.metrology3d.test_file_read import publish, ply
from tests.test_workflow_preview_values import Bridge


@pytest.fixture
def registries(preserve_custom_node_modules):
    """使用实际公开目录与实现，不替换节点或准入。"""
    packs = LocalNodePackLoader(Path(__file__).resolve().parents[1] / "custom_nodes")
    packs.refresh()
    catalog = NodeCatalogRegistry(node_pack_loader=packs)
    loader = WorkflowNodeRuntimeRegistryLoader(
        node_catalog_registry=catalog, node_pack_loader=packs
    )
    loader.refresh()
    return catalog, loader.get_runtime_registry()


def test_contract_requires_exact_input_scope():
    """旧范围不能夹带输入端口，空白端口不可执行。"""
    assert (
        PreviewExecutionScope(
            kind="node-input", target_node_id="fit", input_port="cloud"
        ).input_port
        == "cloud"
    )
    for fields in [
        dict(kind="node-input", target_node_id="fit"),
        dict(kind="node", target_node_id="fit", input_port="cloud"),
        dict(kind="node-input", target_node_id="fit", input_port=" "),
    ]:
        with pytest.raises(ValidationError):
            PreviewExecutionScope(**fields)


def test_scope_excludes_target_and_does_not_mutate_document(registries):
    """当前节点参数不完整不妨碍查看输入；原 App 及图保持原样。"""
    _, registry = registries
    template, app = cloud_documents(options().model_dump(mode="json"))
    template.nodes[1].parameters.clear()
    before = template.model_dump_json(), app.model_dump_json()
    scoped, bindings, source = input_preview_scope(
        template, app, "filter", "cloud", registry.get_node_definition
    )
    assert [node.node_id for node in scoped.nodes] == ["read"]
    assert source == ("read", "cloud") and not scoped.template_outputs
    assert [binding.binding_id for binding in bindings.bindings] == ["cloud"]
    assert before == (template.model_dump_json(), app.model_dump_json())
    for target, port in [("filter", "missing"), ("missing", "cloud"), ("read", "file")]:
        with pytest.raises(InvalidRequestError):
            input_preview_scope(
                template, app, target, port, registry.get_node_definition
            )
    template = template.model_copy(update={"edges": ()})
    with pytest.raises(InvalidRequestError):
        input_preview_scope(
            template, app, "filter", "cloud", registry.get_node_definition
        )


def test_actual_read_capture_survives_scope_cleanup_without_hidden_nodes(
    tmp_path, registries
):
    """真实文件读入及同一显示构造器，运行 Scope 结束后仅显示副本存活。"""
    catalog, registry = registries
    storage = create_resource_service(tmp_path).storage
    template, app = cloud_documents(options().model_dump(mode="json"))
    template.nodes[1].parameters.clear()
    context = WorkflowServiceNodeRuntimeContext(
        session_factory=None,
        dataset_storage=storage,
        point_cloud_policy=execution_policy(),
    )
    events = []
    with (
        closing(PreviewBuffers()) as buffers,
        closing(
            PreviewDisplayCapture(
                Bridge(buffers), lambda kind, value: events.append((kind, value))
            )
        ) as capture,
    ):
        result = PreviewMemoryExecutionService(
            dataset_storage=storage,
            node_catalog_registry=catalog,
            runtime_registry=registry,
            runtime_context=context,
        ).execute(
            PreviewMemoryExecutionRequest(
                project_id="test",
                application_id=app.application_id,
                application=app,
                template=template,
                session_id="input-test",
                target_node_id="filter",
                input_port="cloud",
                input_bindings={"cloud": publish(storage, ply())},
                execution_metadata={
                    "_runtime_preview_capture": capture,
                    "retain_node_records_enabled": True,
                },
            )
        )
        capture.close()
        assert capture.input_cloud_renderer is None
        assert [record.node_id for record in result.node_records] == ["read"]
        display = next(value for kind, value in events if kind == "display.updated")
        assert (
            display["node_id"] == "read"
            and display["output_port"] == "cloud.input-preview"
        )
        assert display["payload"]["state"] == "ready"
        assert display["payload"]["point_count"] == 2
        assert not result.outputs


@pytest.mark.parametrize("target", ["plane", "preview"])
def test_fit_editor_display_only_for_requested_node(tmp_path, registries, target):
    """同次拟面显示原输入及支持分类；其他节点预览不多跑拟面显示。"""
    from backend.contracts.workflows.workflow_graph import WorkflowGraphTemplate
    from tests.test_metrology3d_plane_support import configured

    catalog, registry = registries
    storage = create_resource_service(tmp_path).storage
    template, app = cloud_documents(options().model_dump(mode="json"))
    document = template.model_dump(mode="json")
    document["nodes"][-1]["parameters"]["point_limit"] = 10
    document["nodes"].append(dict(
        node_id="plane", node_type_id="custom.metrology3d.fit-plane",
        parameters=configured().model_dump(mode="json"),
    ))
    document["edges"].append(dict(
        edge_id="fit", source_node_id="filter", source_port="cloud",
        target_node_id="plane", target_port="cloud",
    ))
    template = WorkflowGraphTemplate.model_validate(document)
    context = WorkflowServiceNodeRuntimeContext(
        session_factory=None, dataset_storage=storage, point_cloud_policy=execution_policy(),
    )
    events = []
    with closing(PreviewBuffers()) as buffers, closing(PreviewDisplayCapture(
        Bridge(buffers), lambda kind, value: events.append((kind, value)),
    )) as capture:
        result = PreviewMemoryExecutionService(
            dataset_storage=storage, node_catalog_registry=catalog,
            runtime_registry=registry, runtime_context=context,
        ).execute(PreviewMemoryExecutionRequest(
            project_id="test", application_id=app.application_id, application=app,
            template=template, session_id="fit-test", target_node_id=target,
            input_bindings={"cloud": publish(storage, ply(
                b"-1 -1 3\n-1 1 3\n1 -1 3\n1 1 3\n9 9 9\n", count=5,
            ))},
            execution_metadata={"_runtime_preview_capture": capture, "retain_node_records_enabled": True},
        ))
        capture.close()
        displays = [v for k, v in events if k == "display.updated" and v["output_port"] == "features.editor-preview"]
        if target != "plane":
            assert not displays
            return
        assert [record.node_id for record in result.node_records] == ["read", "filter", "plane"]
        assert len(displays) == 1
        payload = displays[0]["payload"]
        assert payload["state"] == "ready" and payload["point_count"] == 5
        fitted = payload["geometry"]["planes"][0]
        assert fitted["valid"] and fitted["support_point_count"] == 4
        assert fitted["samples"]["classes"] == [1, 1, 1, 1, 0]
        assert fitted["samples"]["residuals"] == [0, 0, 0, 0, None]
        assert not result.outputs
