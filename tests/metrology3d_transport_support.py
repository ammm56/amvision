"""仅测试进程内注册 M1 六节点；不生成或启用生产 manifest。"""

from dataclasses import replace
from hashlib import sha256
import os

from backend.nodes.node_catalog_registry import NodeCatalogRegistry
from backend.contracts.nodes.node_pack_manifest import NodePackManifest
from backend.service.application.workflows.runtime_registry_loader import (
    WorkflowNodeRuntimeRegistryLoader,
)
from custom_nodes._metrology3d_nodes.workflow.catalog_builder import (
    build_custom_node_catalog_document,
)
from custom_nodes._metrology3d_nodes.backend.entry import HANDLERS


class CloudTestCatalog(NodeCatalogRegistry):
    """测试值只存在于此夹具；生产 timeout 仍待确认。"""

    def _build_catalog_snapshot(self):
        base = super()._build_catalog_snapshot()
        cloud = build_custom_node_catalog_document()
        manifest = NodePackManifest.model_validate(
            dict(
                id="metrology3d.nodes",
                version="0.1.9",
                displayName="3D test",
                category="vision",
                capabilities=("workflow-nodes",),
                compatibility=dict(api=">=0.1 <1.0", runtime=">=3.12"),
                timeout=dict(defaultSeconds=180, maxSeconds=180, killGraceSeconds=2),
            )
        )
        return replace(
            base,
            payload_contracts=(*base.payload_contracts, *cloud.payload_contracts),
            node_definitions=(*base.node_definitions, *cloud.node_definitions),
            node_pack_manifests=(*base.node_pack_manifests, manifest),
        )


def checked_preview(request):
    """同一真实 handler 执行前全量核验，测试输出数组留给另一路入口复验。"""
    from custom_nodes._metrology3d_nodes.shared.node_runtime import (
        require_node_runtime,
        cloud_input,
    )
    from contextlib import nullcontext
    import numpy as np

    env = require_node_runtime(request)
    cloud = cloud_input(request, env.runtime)
    expected = os.environ.get("AMVISION_M1_ARRAY_SHA256")
    if expected:
        path = os.environ.get("AMVISION_M1_ARRAY_OUTPUT")
        digest = sha256()
        with open(path, "xb") if path else nullcontext() as stream:
            with env.runtime.borrow(cloud) as view:
                for start in range(0, cloud.point_count, env.runtime.policy.chunk_rows):
                    stop = min(start + env.runtime.policy.chunk_rows, cloud.point_count)
                    block = view.chunk(start, stop)
                    np.testing.assert_array_equal(
                        view.source_indices(start, stop),
                        np.arange(start, stop, dtype="uint32"),
                    )
                    with memoryview(block["positions"]).cast("B") as data:
                        digest.update(data)
                        if stream is not None:
                            assert stream.write(data) == len(data)
                    block = None
        assert digest.hexdigest() == expected
    return HANDLERS["cloud-preview"](request)


class CloudTestRegistryLoader(WorkflowNodeRuntimeRegistryLoader):
    """复用正式 registry，增加内部 Catalog 的真实 handler。"""

    def refresh(self):
        super().refresh()
        for definition in build_custom_node_catalog_document().node_definitions:
            key = definition.node_type_id.rsplit(".", 1)[1]
            self._runtime_registry.register_python_callable(
                definition, checked_preview if key == "cloud-preview" else HANDLERS[key]
            )


def cloud_preview_worker(**kwargs):
    """测试 bootstrap，只替换注册来源，不替换文件、执行或退出路径。"""
    from backend.service.application.workflows.worker import process
    from backend.service.application.workflows.preview.worker import run_preview_worker

    process.NodeCatalogRegistry = CloudTestCatalog
    process.WorkflowNodeRuntimeRegistryLoader = CloudTestRegistryLoader
    run_preview_worker(**kwargs)


def cloud_documents(file_options=None):
    """完整文件或数组沿同一个 filter/preview 图运行。"""
    from backend.contracts.workflows.workflow_graph import (
        WorkflowGraphTemplate,
        FlowApplication,
    )

    file = file_options is not None
    nodes = [
        dict(
            node_id="filter",
            node_type_id="custom.metrology3d.filter-valid",
            parameters=dict(finite_fields=["positions"], sentinels=[]),
        ),
        dict(
            node_id="preview",
            node_type_id="custom.metrology3d.cloud-preview",
            parameters=dict(point_limit=1000, color=dict(mode="solid")),
        ),
    ]
    edges = [
        dict(
            edge_id="display",
            source_node_id="filter",
            source_port="cloud",
            target_node_id="preview",
            target_port="cloud",
        )
    ]
    if file:
        nodes.insert(
            0,
            dict(
                node_id="read",
                node_type_id="custom.metrology3d.read-cloud",
                parameters=dict(source=dict(kind="file"), file_options=file_options),
            ),
        )
        edges.insert(
            0,
            dict(
                edge_id="read-filter",
                source_node_id="read",
                source_port="cloud",
                target_node_id="filter",
                target_port="cloud",
            ),
        )
    template = WorkflowGraphTemplate.model_validate(
        dict(
            template_id="cloud-transport",
            template_version="0.1.8",
            display_name="Cloud",
            nodes=nodes,
            edges=edges,
            template_inputs=[
                dict(
                    input_id="input",
                    display_name="Input",
                    payload_type_id="file-ref.v1" if file else "point-cloud-ref.v1",
                    target_node_id="read" if file else "filter",
                    target_port="file" if file else "cloud",
                )
            ],
            template_outputs=[
                dict(
                    output_id="body",
                    display_name="Cloud",
                    payload_type_id="response-body.v1",
                    source_node_id="preview",
                    source_port="body",
                )
            ],
        )
    )
    application = FlowApplication.model_validate(
        dict(
            application_id="cloud-transport-app",
            display_name="Cloud",
            template_ref=dict(
                template_id=template.template_id,
                template_version=template.template_version,
                source_uri="unused",
            ),
            bindings=[
                dict(
                    binding_id="cloud",
                    direction="input",
                    template_port_id="input",
                    binding_kind="api-request",
                    config=dict(
                        allowed_media_types=["application/octet-stream"],
                        max_file_bytes=1_000_000_000,
                    )
                    if file
                    else {},
                ),
                dict(
                    binding_id="body",
                    direction="output",
                    template_port_id="body",
                    binding_kind="http-response",
                ),
            ],
            metadata=dict(project_id="project-1"),
        )
    )
    return template, application


def cloud_snapshot_child(
    connection, pool_config, policy, metadata, bindings, storage_root
):
    """真实 spawn 子进程经过 Snapshot 输入验证、映射、图执行和 Scope 收尾。"""
    from types import SimpleNamespace
    from backend.service.application.workflows.preview.execution import (
        PreviewMemoryExecutionService,
        PreviewMemoryExecutionRequest,
    )
    from backend.service.application.workflows.service_runtime.context import (
        WorkflowServiceNodeRuntimeContext,
    )
    from backend.service.infrastructure.local_buffers import (
        MmapBufferArenaExternalAccess,
    )
    from tests.point_cloud_support import create_resource_service
    from backend.nodes.local_node_pack_loader import LocalNodePackLoader

    os.environ.pop("AMVISION_M1_ARRAY_OUTPUT", None)
    access = MmapBufferArenaExternalAccess(pool_config)
    context = WorkflowServiceNodeRuntimeContext(
        session_factory=None,
        dataset_storage=create_resource_service(storage_root).storage,
        point_cloud_policy=policy,
        local_buffer_reader=SimpleNamespace(
            acquire_buffer_ref_view=access.acquire_reader_view
        ),
    )
    try:
        catalog = CloudTestCatalog()
        loader = CloudTestRegistryLoader(
            node_catalog_registry=catalog,
            node_pack_loader=LocalNodePackLoader(storage_root / "empty-packs"),
        )
        loader.refresh()
        template, application = cloud_documents()
        # 协议回复由父 supervisor 完成；此子进程只验证正式 Snapshot 输入及图执行。
        metadata = {
            k: v
            for k, v in metadata.items()
            if k in {"workflow_run_id", "_workflow_cloud_input_handoff"}
        }
        result = PreviewMemoryExecutionService(
            dataset_storage=context.dataset_storage,
            node_catalog_registry=catalog,
            runtime_registry=loader.get_runtime_registry(),
            runtime_context=context,
        ).execute(
            PreviewMemoryExecutionRequest(
                project_id="project-1",
                application_id=application.application_id,
                application=application,
                template=template,
                session_id="test",
                input_bindings=bindings,
                execution_metadata=metadata,
            )
        )
        connection.send((True, result.outputs))
    except BaseException:
        import traceback

        connection.send((False, traceback.format_exc()))
    finally:
        access.close()
        connection.close()
