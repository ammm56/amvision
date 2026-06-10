"""OpenCV 缺陷节点模块集合。"""

from __future__ import annotations

from custom_nodes.opencv_defect_nodes.backend.nodes.absdiff_threshold import (
    NODE_TYPE_ID as ABSDIFF_THRESHOLD_NODE_TYPE_ID,
    handle_node as absdiff_threshold_handler,
)
from custom_nodes.opencv_defect_nodes.backend.nodes.connected_components import (
    NODE_TYPE_ID as CONNECTED_COMPONENTS_NODE_TYPE_ID,
    handle_node as connected_components_handler,
)
from custom_nodes.opencv_defect_nodes.backend.nodes.distance_transform import (
    NODE_TYPE_ID as DISTANCE_TRANSFORM_NODE_TYPE_ID,
    handle_node as distance_transform_handler,
)
from custom_nodes.opencv_defect_nodes.backend.nodes.fill_holes import (
    NODE_TYPE_ID as FILL_HOLES_NODE_TYPE_ID,
    handle_node as fill_holes_handler,
)
from custom_nodes.opencv_defect_nodes.backend.nodes.image_diff import (
    NODE_TYPE_ID as IMAGE_DIFF_NODE_TYPE_ID,
    handle_node as image_diff_handler,
)


NODE_HANDLERS = (
    (IMAGE_DIFF_NODE_TYPE_ID, image_diff_handler),
    (ABSDIFF_THRESHOLD_NODE_TYPE_ID, absdiff_threshold_handler),
    (CONNECTED_COMPONENTS_NODE_TYPE_ID, connected_components_handler),
    (FILL_HOLES_NODE_TYPE_ID, fill_holes_handler),
    (DISTANCE_TRANSFORM_NODE_TYPE_ID, distance_transform_handler),
)


__all__ = ["NODE_HANDLERS"]
