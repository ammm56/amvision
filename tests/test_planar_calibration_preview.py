"""标定预览保存使用同次结果，运行时不复制标定证据。"""

from dataclasses import replace

import pytest

from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest, WorkflowGraphExecutor, WorkflowNodeRuntimeRegistry
from backend.contracts.workflows.workflow_graph import WorkflowGraphTemplate
from custom_nodes.opencv_nodes.categories.calibration.workflow.catalog_builder import build_custom_node_catalog_document
from custom_nodes.opencv_nodes.categories.calibration.backend.nodes.planar_calibrate import handle_node


def test_planar_preview_snapshot_and_runtime_boundary():
    """验证独立点门槛、完整参数快照和生产输出不变。"""
    parameters = dict(
        image_width=128, image_height=128, plane_id="test-plane",
        control_points=[dict(image=p, world=[v / 10 for v in p]) for p in [[10, 10], [110, 10], [110, 110], [10, 110]]],
        validation_points=[dict(image=p, world=[v / 10 for v in p]) for p in [[30, 40], [80, 70]]],
        max_validation_error=.001,
    )
    request = WorkflowNodeExecutionRequest(node_id="calibration", node_definition=object(), parameters=parameters, input_values={}, execution_metadata={})
    runtime = handle_node(request)
    preview = handle_node(replace(request, execution_metadata={"debug_image_panels_enabled": True}))
    assert set(runtime) == {"calibration", "summary"}
    assert preview["calibration"] == runtime["calibration"]
    assert preview["debug_preview"]["calibration_resource"] == runtime["calibration"]
    assert preview["debug_preview"]["parameter_snapshot"]["model"] == "affine"
    assert preview["debug_preview"]["parameter_snapshot"]["validation_points"] == parameters["validation_points"]
    definition = next(d for d in build_custom_node_catalog_document().node_definitions if d.node_type_id == "custom.opencv.planar-calibrate")
    registry = WorkflowNodeRuntimeRegistry()
    registry.register_python_callable(definition, handle_node)
    graph = WorkflowGraphTemplate.model_validate(dict(template_id="calibration-test", template_version="0.1.8", display_name="Calibration", nodes=[dict(node_id="calibrate", node_type_id=definition.node_type_id, parameters=parameters)], edges=[], template_inputs=[], template_outputs=[dict(output_id="result", display_name="Calibration", payload_type_id="planar-calibration.v1", source_node_id="calibrate", source_port="calibration")]))
    executed = WorkflowGraphExecutor(registry=registry).execute(template=graph, input_values={}, execution_metadata={"debug_image_panels_enabled": True})
    assert executed.outputs["result"] == runtime["calibration"]
    parameters["validation_points"][0]["world"] = [9, 9]
    with pytest.raises(InvalidRequestError, match="独立标定验证误差"):
        handle_node(request)
