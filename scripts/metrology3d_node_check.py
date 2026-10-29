"""完整样本的实际节点执行器验收，不注册生产包或修改现场参数。"""

import base64
from hashlib import sha256
import numpy as np

from backend.contracts.workflows.workflow_graph import WorkflowGraphTemplate
from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.resource_scope import (
    get_or_create_workflow_resource_scope,
)
from backend.service.application.workflows.graph_executor import (
    WorkflowGraphExecutor,
    WorkflowNodeRuntimeRegistry,
    WorkflowNodeExecutionRequest,
)
from backend.service.application.workflows.point_cloud.runtime import get_cloud_runtime
from backend.service.application.workflows.service_runtime.context import (
    WorkflowServiceNodeRuntimeContext,
)
from backend.service.application.workflows.runtime_preview import (
    RuntimePreviewCapture,
    PREVIEW_CAPTURE_KEY,
)
from custom_nodes.metrology3d_nodes.backend.entry import HANDLERS
from custom_nodes.metrology3d_nodes.workflow.catalog_builder import (
    build_custom_node_catalog_document,
)


def verify_node_graph(
    *,
    storage,
    file,
    options,
    policy,
    point_limit,
    expected_points,
    expected_array_sha256,
):
    """全量计算后才采样显示；持久引用和导出独立新运行逐块核对。"""
    registry = WorkflowNodeRuntimeRegistry()
    catalog = build_custom_node_catalog_document()
    definitions = {
        d.node_type_id.rsplit(".", 1)[1]: d for d in catalog.node_definitions
    }
    for key, definition in definitions.items():
        registry.register_python_callable(definition, HANDLERS[key])
    parameters = {
        "read-cloud": dict(
            source=dict(kind="file"), file_options=options.model_dump(mode="json")
        ),
        "filter-valid": dict(finite_fields=["positions"], sentinels=[]),
        "cloud-preview": dict(point_limit=point_limit, color=dict(mode="solid")),
        "save-cloud": dict(
            mode="derived", target=dict(kind="new", name="Full sample nodes")
        ),
        "export-cloud": dict(
            source=dict(kind="cloud"),
            profile_id="ply-binary-le",
            profile_version=1,
            fields=["positions"],
            file_name="full-sample.ply",
            spatial_acknowledged=True,
        ),
    }
    links = [
        ("read-cloud", "filter-valid"),
        *(("filter-valid", k) for k in ("cloud-preview", "save-cloud", "export-cloud")),
    ]
    template = WorkflowGraphTemplate.model_validate(
        dict(
            template_id="full-sample-nodes",
            template_version="1",
            display_name="Full Sample",
            nodes=[
                dict(node_id=k, node_type_id="custom.metrology3d." + k, parameters=p)
                for k, p in parameters.items()
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
                    ("filter-valid", "cloud", "point-cloud-ref.v1"),
                    ("cloud-preview", "body", "response-body.v1"),
                    ("save-cloud", "resource", "measurement-resource-ref.v1"),
                    ("export-cloud", "file", "file-ref.v1"),
                )
            ],
        )
    )
    context = WorkflowServiceNodeRuntimeContext(
        session_factory=None, dataset_storage=storage, point_cloud_policy=policy
    )
    metadata = dict(project_id="sample", workflow_run_id="full-node-graph")
    capture = RuntimePreviewCapture()
    metadata[PREVIEW_CAPTURE_KEY] = capture
    scope = get_or_create_workflow_resource_scope(metadata)
    runtime = get_cloud_runtime(
        scope, run_id=metadata["workflow_run_id"], policy=policy.io
    )
    try:
        result = WorkflowGraphExecutor(registry=registry).execute(
            template=template,
            input_values={"file": file},
            execution_metadata=metadata,
            runtime_context=context,
        )
        if options.spatial.length_unit is not None:
            raise ValueError("本样本验收需要保留未知单位，不能猜测单位")
        try:
            HANDLERS["normalize-units"](
                WorkflowNodeExecutionRequest(
                    node_id="normalize",
                    node_definition=definitions["normalize-units"],
                    parameters={"target_unit": "mm"},
                    input_values={"cloud": result.outputs["cloud"]},
                    execution_metadata=metadata,
                    runtime_context=context,
                )
            )
        except InvalidRequestError:
            unit_guard = "unknown-unit-rejected"
        else:
            raise AssertionError("未知单位被静默归一")
        if capture.error or len(capture.records) != 1:
            raise AssertionError("运行显示捕获未完整交接")
    finally:
        if scope.close() or runtime.budget.used:
            raise AssertionError("节点运行资源没有完整释放")
    body = result.outputs["body"]
    data = base64.b64decode(body["data"]["content"], validate=True)
    if (
        sha256(data).hexdigest() != body["data"]["checksum"]
        or body["source_point_count"] != expected_points
    ):
        raise AssertionError("显示内容或原始总点数不一致")
    fields = {f["name"]: f for f in body["data"]["fields"]}
    index = fields["source_indices"]
    indices = np.frombuffer(
        data, dtype="<u8", offset=index["offset"], count=body["display_point_count"]
    )
    np.testing.assert_array_equal(
        indices,
        np.array(
            [
                j * (expected_points - 1) // (len(indices) - 1)
                if len(indices) > 1
                else 0
                for j in range(len(indices))
            ],
            dtype="u8",
        ),
    )
    if fields["positions"]["dtype"] != "float32":
        raise AssertionError("显示副本改变源精度")
    checks = {}
    for source in ("asset", "export"):
        identity = "verify-node-" + source
        meta = dict(project_id="sample", workflow_run_id=identity)
        owner = get_or_create_workflow_resource_scope(meta)
        restored_runtime = get_cloud_runtime(owner, run_id=identity, policy=policy.io)
        params = (
            dict(source=dict(kind="asset", reference=result.outputs["resource"]))
            if source == "asset"
            else dict(
                source=dict(kind="file"),
                file_options={
                    **options.model_dump(mode="json"),
                    "profile_id": "ply-binary-le",
                },
            )
        )
        try:
            restored = HANDLERS["read-cloud"](
                WorkflowNodeExecutionRequest(
                    node_id="read",
                    node_definition=definitions["read-cloud"],
                    parameters=params,
                    input_values={}
                    if source == "asset"
                    else {"file": result.outputs["file"]},
                    execution_metadata=meta,
                    runtime_context=context,
                )
            )["cloud"]
            from backend.contracts.workflows.point_cloud_runtime import CloudReference

            ref = CloudReference.model_validate(restored)
            digest = sha256()
            with restored_runtime.borrow(ref) as view:
                for start in range(0, ref.point_count, policy.io.chunk_rows):
                    stop = min(ref.point_count, start + policy.io.chunk_rows)
                    with memoryview(view.chunk(start, stop)["positions"]).cast(
                        "B"
                    ) as chunk:
                        digest.update(chunk)
                    np.testing.assert_array_equal(
                        view.source_indices(start, stop),
                        np.arange(start, stop, dtype="u4"),
                    )
            if (
                ref.point_count != expected_points
                or digest.hexdigest() != expected_array_sha256
            ):
                raise AssertionError("节点产物全量点数或坐标摘要不同")
            checks[source] = digest.hexdigest()
        finally:
            if owner.close() or restored_runtime.budget.used:
                raise AssertionError("节点产物恢复资源没有完整释放")
    return dict(
        executed_nodes=len(result.node_records),
        normalize_units=unit_guard,
        source_point_count=body["source_point_count"],
        display_point_count=body["display_point_count"],
        display_bytes=len(data),
        display_checksum=body["data"]["checksum"],
        preview_after_scope_close=True,
        budget_after_close=runtime.budget.used,
        full_array_checks=checks,
    )
