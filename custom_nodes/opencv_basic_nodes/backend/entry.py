"""OpenCV 基础节点包的 backend entrypoint。"""

from __future__ import annotations

from custom_nodes.opencv_basic_nodes.backend.nodes.binary_threshold import (
    NODE_TYPE_ID as BINARY_THRESHOLD_NODE_TYPE_ID,
    handle_node as binary_threshold_handler,
)
from custom_nodes.opencv_basic_nodes.backend.nodes.canny import (
    NODE_TYPE_ID as CANNY_NODE_TYPE_ID,
    handle_node as canny_handler,
)
from custom_nodes.opencv_basic_nodes.backend.nodes.contour import (
    NODE_TYPE_ID as CONTOUR_NODE_TYPE_ID,
    handle_node as contour_handler,
)
from custom_nodes.opencv_basic_nodes.backend.nodes.crop_export import (
    NODE_TYPE_ID as CROP_EXPORT_NODE_TYPE_ID,
    handle_node as crop_export_handler,
)
from custom_nodes.opencv_basic_nodes.backend.nodes.draw_detections import (
    NODE_TYPE_ID as DRAW_DETECTIONS_NODE_TYPE_ID,
    handle_node as draw_detections_handler,
)
from custom_nodes.opencv_basic_nodes.backend.nodes.gallery_preview import (
    NODE_TYPE_ID as GALLERY_PREVIEW_NODE_TYPE_ID,
    handle_node as gallery_preview_handler,
)
from custom_nodes.opencv_basic_nodes.backend.nodes.gaussian_blur import (
    NODE_TYPE_ID as GAUSSIAN_BLUR_NODE_TYPE_ID,
    handle_node as gaussian_blur_handler,
)
from custom_nodes.opencv_basic_nodes.backend.nodes.measure import (
    NODE_TYPE_ID as MEASURE_NODE_TYPE_ID,
    handle_node as measure_handler,
)
from custom_nodes.opencv_basic_nodes.backend.nodes.morphology import (
    NODE_TYPE_ID as MORPHOLOGY_NODE_TYPE_ID,
    handle_node as morphology_handler,
)
from backend.service.application.workflows.runtime_registry_loader import (
    NodePackEntrypointRegistrationContext,
)


def register(context: NodePackEntrypointRegistrationContext) -> None:
    """把 OpenCV 基础节点 handler 注册到 workflow 运行时注册表。

    参数：
    - context：当前 node pack 的注册上下文。
    """

    context.register_python_callable(DRAW_DETECTIONS_NODE_TYPE_ID, draw_detections_handler)
    context.register_python_callable(GAUSSIAN_BLUR_NODE_TYPE_ID, gaussian_blur_handler)
    context.register_python_callable(BINARY_THRESHOLD_NODE_TYPE_ID, binary_threshold_handler)
    context.register_python_callable(MORPHOLOGY_NODE_TYPE_ID, morphology_handler)
    context.register_python_callable(CANNY_NODE_TYPE_ID, canny_handler)
    context.register_python_callable(CONTOUR_NODE_TYPE_ID, contour_handler)
    context.register_python_callable(MEASURE_NODE_TYPE_ID, measure_handler)
    context.register_python_callable(CROP_EXPORT_NODE_TYPE_ID, crop_export_handler)
    context.register_python_callable(GALLERY_PREVIEW_NODE_TYPE_ID, gallery_preview_handler)