"""OpenCV 第三批工业扩展节点测试。"""

from __future__ import annotations

from pathlib import Path

from backend.contracts.workflows.workflow_graph import (
    WorkflowGraphEdge,
    WorkflowGraphInput,
    WorkflowGraphNode,
    WorkflowGraphOutput,
    WorkflowGraphTemplate,
)
from backend.nodes import ExecutionImageRegistry
from backend.nodes.local_node_pack_loader import LocalNodePackLoader
from backend.nodes.node_catalog_registry import NodeCatalogRegistry
from backend.service.application.workflows.graph_executor import WorkflowGraphExecutor
from backend.service.application.workflows.runtime_registry_loader import (
    WorkflowNodeRuntimeRegistryLoader,
)
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings,
    LocalDatasetStorage,
)


def test_opencv_basic_batch3_hough_lines_execute(tmp_path: Path) -> None:
    """验证 canny、hough-lines 与 payload-to-value 可接成直线检测链。"""

    executor = _create_repository_executor()
    dataset_storage = _create_dataset_storage(tmp_path)
    image_registry = ExecutionImageRegistry()
    dataset_storage.write_bytes("inputs/hough-lines.png", _build_line_test_png_bytes())

    template = WorkflowGraphTemplate(
        template_id="opencv-batch3-hough-lines",
        template_version="1.0.0",
        display_name="OpenCV Batch3 Hough Lines",
        nodes=(
            WorkflowGraphNode(node_id="input", node_type_id="core.io.template-input.image"),
            WorkflowGraphNode(
                node_id="canny",
                node_type_id="custom.opencv.canny",
                parameters={"threshold1": 30, "threshold2": 100, "aperture_size": 3},
            ),
            WorkflowGraphNode(
                node_id="lines",
                node_type_id="custom.opencv.hough-lines",
                parameters={
                    "threshold": 20,
                    "min_line_length": 30.0,
                    "max_line_gap": 8.0,
                    "sort_by": "length_pixels",
                    "descending": True,
                    "debug_image_panel_enabled": True,
                },
            ),
            WorkflowGraphNode(node_id="value", node_type_id="custom.opencv.payload-to-value"),
        ),
        edges=(
            WorkflowGraphEdge(
                edge_id="edge-input-canny",
                source_node_id="input",
                source_port="image",
                target_node_id="canny",
                target_port="image",
            ),
            WorkflowGraphEdge(
                edge_id="edge-canny-lines",
                source_node_id="canny",
                source_port="image",
                target_node_id="lines",
                target_port="image",
            ),
            WorkflowGraphEdge(
                edge_id="edge-lines-value",
                source_node_id="lines",
                source_port="lines",
                target_node_id="value",
                target_port="lines",
            ),
        ),
        template_inputs=(
            WorkflowGraphInput(
                input_id="request_image_base64",
                display_name="Request Image",
                payload_type_id="image-ref.v1",
                target_node_id="input",
                target_port="payload",
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="edge_image",
                display_name="Edge Image",
                payload_type_id="image-ref.v1",
                source_node_id="canny",
                source_port="image",
            ),
            WorkflowGraphOutput(
                output_id="lines",
                display_name="Lines",
                payload_type_id="lines.v1",
                source_node_id="lines",
                source_port="lines",
            ),
            WorkflowGraphOutput(
                output_id="lines_summary",
                display_name="Lines Summary",
                payload_type_id="value.v1",
                source_node_id="lines",
                source_port="summary",
            ),
            WorkflowGraphOutput(
                output_id="lines_value",
                display_name="Lines Value",
                payload_type_id="value.v1",
                source_node_id="value",
                source_port="value",
            ),
        ),
    )

    execution_result = executor.execute(
        template=template,
        input_values={
            "request_image_base64": {
                "object_key": "inputs/hough-lines.png",
                "width": 96,
                "height": 96,
                "media_type": "image/png",
            }
        },
        execution_metadata={
            "dataset_storage": dataset_storage,
            "execution_image_registry": image_registry,
            "workflow_run_id": "opencv-batch3-hough-lines",
            "debug_image_panels_enabled": True,
        },
    )

    edge_image = execution_result.outputs["edge_image"]
    lines = execution_result.outputs["lines"]
    lines_summary = execution_result.outputs["lines_summary"]
    lines_value = execution_result.outputs["lines_value"]

    assert edge_image["transport_kind"] == "memory"
    assert lines["count"] >= 2
    assert lines["source_image"]["width"] == 96
    assert lines["items"][0]["length_pixels"] >= 40.0
    assert isinstance(lines["items"][0]["start_xy"], list)
    assert lines_summary["value"]["count"] == lines["count"]
    assert lines_summary["value"]["max_length_pixels"] >= 40.0
    assert lines_value["value"]["count"] == lines["count"]
    debug_preview = _read_record_output(execution_result, node_id="lines", output_name="debug_preview")
    interaction = debug_preview["interaction"]
    tools_by_name = {tool["tool"]: tool for tool in interaction["tools"]}
    controls_by_name = {control["parameter_name"]: control for control in interaction["controls"]}
    assert debug_preview["type"] == "image-preview"
    assert set(tools_by_name["line"]["target_parameters"]) == {
        "search_bbox_xyxy",
        "min_line_length",
        "angle_min_deg",
        "angle_max_deg",
    }
    assert tools_by_name["rect"]["target_parameters"] == ["search_bbox_xyxy"]
    assert {"threshold", "min_line_length", "max_line_gap", "angle_min_deg", "angle_max_deg"} <= set(controls_by_name)


def test_opencv_basic_batch3_hough_circles_execute(tmp_path: Path) -> None:
    """验证 hough-circles 与 payload-to-value 可接成圆检测链。"""

    executor = _create_repository_executor()
    dataset_storage = _create_dataset_storage(tmp_path)
    image_registry = ExecutionImageRegistry()
    dataset_storage.write_bytes("inputs/hough-circles.png", _build_circle_test_png_bytes())

    template = WorkflowGraphTemplate(
        template_id="opencv-batch3-hough-circles",
        template_version="1.0.0",
        display_name="OpenCV Batch3 Hough Circles",
        nodes=(
            WorkflowGraphNode(node_id="input", node_type_id="core.io.template-input.image"),
            WorkflowGraphNode(
                node_id="circles",
                node_type_id="custom.opencv.hough-circles",
                parameters={
                    "dp": 1.2,
                    "min_dist": 20.0,
                    "param1": 100.0,
                    "param2": 18.0,
                    "min_radius": 14,
                    "max_radius": 24,
                    "sort_by": "radius",
                    "descending": True,
                    "debug_image_panel_enabled": True,
                },
            ),
            WorkflowGraphNode(node_id="value", node_type_id="custom.opencv.payload-to-value"),
        ),
        edges=(
            WorkflowGraphEdge(
                edge_id="edge-input-circles",
                source_node_id="input",
                source_port="image",
                target_node_id="circles",
                target_port="image",
            ),
            WorkflowGraphEdge(
                edge_id="edge-circles-value",
                source_node_id="circles",
                source_port="circles",
                target_node_id="value",
                target_port="circles",
            ),
        ),
        template_inputs=(
            WorkflowGraphInput(
                input_id="request_image_base64",
                display_name="Request Image",
                payload_type_id="image-ref.v1",
                target_node_id="input",
                target_port="payload",
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="circles",
                display_name="Circles",
                payload_type_id="circles.v1",
                source_node_id="circles",
                source_port="circles",
            ),
            WorkflowGraphOutput(
                output_id="circles_summary",
                display_name="Circles Summary",
                payload_type_id="value.v1",
                source_node_id="circles",
                source_port="summary",
            ),
            WorkflowGraphOutput(
                output_id="circles_value",
                display_name="Circles Value",
                payload_type_id="value.v1",
                source_node_id="value",
                source_port="value",
            ),
        ),
    )

    execution_result = executor.execute(
        template=template,
        input_values={
            "request_image_base64": {
                "object_key": "inputs/hough-circles.png",
                "width": 96,
                "height": 96,
                "media_type": "image/png",
            }
        },
        execution_metadata={
            "dataset_storage": dataset_storage,
            "execution_image_registry": image_registry,
            "workflow_run_id": "opencv-batch3-hough-circles",
            "debug_image_panels_enabled": True,
        },
    )

    circles = execution_result.outputs["circles"]
    circles_summary = execution_result.outputs["circles_summary"]
    circles_value = execution_result.outputs["circles_value"]

    assert circles["count"] >= 1
    assert 14.0 <= float(circles["items"][0]["radius"]) <= 24.0
    assert circles_summary["value"]["count"] == circles["count"]
    assert circles_summary["value"]["max_radius_detected"] >= 14.0
    assert circles_value["value"]["count"] == circles["count"]
    debug_preview = _read_record_output(execution_result, node_id="circles", output_name="debug_preview")
    interaction = debug_preview["interaction"]
    tools_by_name = {tool["tool"]: tool for tool in interaction["tools"]}
    controls_by_name = {control["parameter_name"]: control for control in interaction["controls"]}
    assert debug_preview["type"] == "image-preview"
    assert set(tools_by_name["circle"]["target_parameters"]) == {
        "search_bbox_xyxy",
        "min_dist",
        "min_radius",
        "max_radius",
    }
    assert tools_by_name["rect"]["target_parameters"] == ["search_bbox_xyxy"]
    assert {"param1", "param2", "min_radius", "max_radius"} <= set(controls_by_name)


def test_opencv_basic_batch3_fit_line_execute(tmp_path: Path) -> None:
    """验证 contour、fit-line 与 payload-to-value 可接成拟合直线链。"""

    executor = _create_repository_executor()
    dataset_storage = _create_dataset_storage(tmp_path)
    image_registry = ExecutionImageRegistry()
    dataset_storage.write_bytes("inputs/fit-line.png", _build_fit_line_test_png_bytes())

    template = WorkflowGraphTemplate(
        template_id="opencv-batch3-fit-line",
        template_version="1.0.0",
        display_name="OpenCV Batch3 Fit Line",
        nodes=(
            WorkflowGraphNode(node_id="input", node_type_id="core.io.template-input.image"),
            WorkflowGraphNode(
                node_id="otsu",
                node_type_id="custom.opencv.otsu-threshold",
                parameters={"threshold_type": "binary"},
            ),
            WorkflowGraphNode(
                node_id="contour",
                node_type_id="custom.opencv.contour",
                parameters={"retrieval_mode": "external", "min_area": 20.0},
            ),
            WorkflowGraphNode(
                node_id="fit",
                node_type_id="custom.opencv.fit-line",
                parameters={"sort_by": "length_pixels", "descending": True},
            ),
            WorkflowGraphNode(node_id="value", node_type_id="custom.opencv.payload-to-value"),
        ),
        edges=(
            WorkflowGraphEdge(
                edge_id="edge-input-otsu-fit",
                source_node_id="input",
                source_port="image",
                target_node_id="otsu",
                target_port="image",
            ),
            WorkflowGraphEdge(
                edge_id="edge-otsu-contour-fit",
                source_node_id="otsu",
                source_port="image",
                target_node_id="contour",
                target_port="image",
            ),
            WorkflowGraphEdge(
                edge_id="edge-contour-fit",
                source_node_id="contour",
                source_port="contours",
                target_node_id="fit",
                target_port="contours",
            ),
            WorkflowGraphEdge(
                edge_id="edge-fit-value",
                source_node_id="fit",
                source_port="lines",
                target_node_id="value",
                target_port="lines",
            ),
        ),
        template_inputs=(
            WorkflowGraphInput(
                input_id="request_image_base64",
                display_name="Request Image",
                payload_type_id="image-ref.v1",
                target_node_id="input",
                target_port="payload",
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="lines",
                display_name="Lines",
                payload_type_id="lines.v1",
                source_node_id="fit",
                source_port="lines",
            ),
            WorkflowGraphOutput(
                output_id="lines_summary",
                display_name="Lines Summary",
                payload_type_id="value.v1",
                source_node_id="fit",
                source_port="summary",
            ),
            WorkflowGraphOutput(
                output_id="lines_value",
                display_name="Lines Value",
                payload_type_id="value.v1",
                source_node_id="value",
                source_port="value",
            ),
        ),
    )

    execution_result = executor.execute(
        template=template,
        input_values={
            "request_image_base64": {
                "object_key": "inputs/fit-line.png",
                "width": 96,
                "height": 96,
                "media_type": "image/png",
            }
        },
        execution_metadata={
            "dataset_storage": dataset_storage,
            "execution_image_registry": image_registry,
            "workflow_run_id": "opencv-batch3-fit-line",
        },
    )

    lines = execution_result.outputs["lines"]
    lines_summary = execution_result.outputs["lines_summary"]
    lines_value = execution_result.outputs["lines_value"]

    assert lines["count"] >= 1
    assert float(lines["items"][0]["length_pixels"]) >= 50.0
    assert "direction_xy" in lines["items"][0]
    assert abs(float(lines["items"][0]["angle_deg"])) <= 90.0
    assert lines_summary["value"]["count"] == lines["count"]
    assert lines_value["value"]["count"] == lines["count"]


def test_opencv_basic_batch3_min_enclosing_circle_execute(tmp_path: Path) -> None:
    """验证 contour、min-enclosing-circle 与 payload-to-value 可接成圆拟合链。"""

    executor = _create_repository_executor()
    dataset_storage = _create_dataset_storage(tmp_path)
    image_registry = ExecutionImageRegistry()
    dataset_storage.write_bytes("inputs/min-enclosing-circle.png", _build_min_enclosing_circle_test_png_bytes())

    template = WorkflowGraphTemplate(
        template_id="opencv-batch3-min-enclosing-circle",
        template_version="1.0.0",
        display_name="OpenCV Batch3 Min Enclosing Circle",
        nodes=(
            WorkflowGraphNode(node_id="input", node_type_id="core.io.template-input.image"),
            WorkflowGraphNode(
                node_id="otsu",
                node_type_id="custom.opencv.otsu-threshold",
                parameters={"threshold_type": "binary"},
            ),
            WorkflowGraphNode(
                node_id="contour",
                node_type_id="custom.opencv.contour",
                parameters={"retrieval_mode": "external", "min_area": 20.0},
            ),
            WorkflowGraphNode(
                node_id="circle",
                node_type_id="custom.opencv.min-enclosing-circle",
                parameters={
                    "sort_by": "radius",
                    "descending": True,
                    "debug_image_panel_enabled": True,
                },
            ),
            WorkflowGraphNode(node_id="value", node_type_id="custom.opencv.payload-to-value"),
        ),
        edges=(
            WorkflowGraphEdge(
                edge_id="edge-input-otsu-circle",
                source_node_id="input",
                source_port="image",
                target_node_id="otsu",
                target_port="image",
            ),
            WorkflowGraphEdge(
                edge_id="edge-otsu-contour-circle",
                source_node_id="otsu",
                source_port="image",
                target_node_id="contour",
                target_port="image",
            ),
            WorkflowGraphEdge(
                edge_id="edge-contour-circle",
                source_node_id="contour",
                source_port="contours",
                target_node_id="circle",
                target_port="contours",
            ),
            WorkflowGraphEdge(
                edge_id="edge-circle-value",
                source_node_id="circle",
                source_port="circles",
                target_node_id="value",
                target_port="circles",
            ),
        ),
        template_inputs=(
            WorkflowGraphInput(
                input_id="request_image_base64",
                display_name="Request Image",
                payload_type_id="image-ref.v1",
                target_node_id="input",
                target_port="payload",
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="circles",
                display_name="Circles",
                payload_type_id="circles.v1",
                source_node_id="circle",
                source_port="circles",
            ),
            WorkflowGraphOutput(
                output_id="circles_summary",
                display_name="Circles Summary",
                payload_type_id="value.v1",
                source_node_id="circle",
                source_port="summary",
            ),
            WorkflowGraphOutput(
                output_id="circles_value",
                display_name="Circles Value",
                payload_type_id="value.v1",
                source_node_id="value",
                source_port="value",
            ),
        ),
    )

    execution_result = executor.execute(
        template=template,
        input_values={
            "request_image_base64": {
                "object_key": "inputs/min-enclosing-circle.png",
                "width": 96,
                "height": 96,
                "media_type": "image/png",
            }
        },
        execution_metadata={
            "dataset_storage": dataset_storage,
            "execution_image_registry": image_registry,
            "workflow_run_id": "opencv-batch3-min-enclosing-circle",
            "debug_image_panels_enabled": True,
        },
    )

    circles = execution_result.outputs["circles"]
    circles_summary = execution_result.outputs["circles_summary"]
    circles_value = execution_result.outputs["circles_value"]
    debug_preview = _read_record_output(execution_result, node_id="circle", output_name="debug_preview")

    assert circles["count"] >= 1
    assert 16.0 <= float(circles["items"][0]["radius"]) <= 22.0
    assert float(circles["items"][0]["fill_ratio"]) > 0.6
    assert circles_summary["value"]["count"] == circles["count"]
    assert circles_value["value"]["count"] == circles["count"]
    assert debug_preview["type"] == "image-preview"
    assert debug_preview["interaction"]["tools"][0]["target_parameters"] == ["selected_contour_index"]
    pick_overlay = next(
        overlay
        for overlay in debug_preview["overlays"]
        if "selected_contour_index" in overlay.get("target_parameters", [])
    )
    assert isinstance(pick_overlay["parameters"]["selected_contour_index"], int)


def _create_repository_executor() -> WorkflowGraphExecutor:
    """创建绑定仓库 custom_nodes 的 workflow 执行器。"""

    custom_nodes_root_dir = Path(__file__).resolve().parents[1] / "custom_nodes"
    node_pack_loader = LocalNodePackLoader(custom_nodes_root_dir)
    node_pack_loader.refresh()
    runtime_registry_loader = WorkflowNodeRuntimeRegistryLoader(
        node_catalog_registry=NodeCatalogRegistry(node_pack_loader=node_pack_loader),
        node_pack_loader=node_pack_loader,
    )
    runtime_registry_loader.refresh()
    return WorkflowGraphExecutor(registry=runtime_registry_loader.get_runtime_registry())


def _read_record_output(
    execution_result,
    *,
    node_id: str,
    output_name: str,
) -> dict[str, object]:
    """从节点执行记录中读取指定输出。"""

    for record in execution_result.node_records:
        if record.node_id == node_id:
            output_payload = record.outputs.get(output_name)
            assert isinstance(output_payload, dict)
            return output_payload
    raise AssertionError(f"node record not found: {node_id}")


def _create_dataset_storage(tmp_path: Path) -> LocalDatasetStorage:
    """创建本地 dataset storage。"""

    return LocalDatasetStorage(DatasetStorageSettings(root_dir=str(tmp_path / "dataset-files")))


def _build_line_test_png_bytes() -> bytes:
    """构建可稳定检测直线的测试图片。"""

    import cv2
    import numpy as np

    image = np.zeros((96, 96, 3), dtype=np.uint8)
    cv2.line(image, (8, 20), (88, 20), (255, 255, 255), thickness=2)
    cv2.line(image, (12, 72), (80, 44), (255, 255, 255), thickness=2)
    success, encoded = cv2.imencode(".png", image)
    assert success is True
    return encoded.tobytes()


def _build_circle_test_png_bytes() -> bytes:
    """构建可稳定检测圆的测试图片。"""

    import cv2
    import numpy as np

    image = np.zeros((96, 96), dtype=np.uint8)
    cv2.circle(image, (48, 48), 18, 255, thickness=3)
    image = cv2.GaussianBlur(image, (5, 5), 1.2)
    success, encoded = cv2.imencode(".png", image)
    assert success is True
    return encoded.tobytes()


def _build_fit_line_test_png_bytes() -> bytes:
    """构建可稳定提取拟合直线 contour 的测试图片。"""

    import cv2
    import numpy as np

    image = np.zeros((96, 96, 3), dtype=np.uint8)
    cv2.line(image, (14, 78), (80, 22), (255, 255, 255), thickness=6)
    success, encoded = cv2.imencode(".png", image)
    assert success is True
    return encoded.tobytes()


def _build_min_enclosing_circle_test_png_bytes() -> bytes:
    """构建可稳定提取最小外接圆 contour 的测试图片。"""

    import cv2
    import numpy as np

    image = np.zeros((96, 96, 3), dtype=np.uint8)
    cv2.circle(image, (48, 48), 18, (255, 255, 255), thickness=-1)
    success, encoded = cv2.imencode(".png", image)
    assert success is True
    return encoded.tobytes()
