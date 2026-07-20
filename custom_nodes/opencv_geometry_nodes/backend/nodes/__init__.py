"""OpenCV 几何节点模块集合。"""

from __future__ import annotations

from custom_nodes.opencv_geometry_nodes.backend.nodes.affine_transform import (
    NODE_TYPE_ID as AFFINE_TRANSFORM_NODE_TYPE_ID,
    handle_node as affine_transform_handler,
)
from custom_nodes.opencv_geometry_nodes.backend.nodes.planar_transform_bridge import (
    NODE_TYPE_ID as PLANAR_TRANSFORM_BRIDGE_NODE_TYPE_ID,
    handle_node as planar_transform_bridge_handler,
)
from custom_nodes.opencv_geometry_nodes.backend.nodes.perspective_transform import (
    NODE_TYPE_ID as PERSPECTIVE_TRANSFORM_NODE_TYPE_ID,
    handle_node as perspective_transform_handler,
)
from custom_nodes.opencv_geometry_nodes.backend.nodes.line_deduplicate import (
    NODE_TYPE_ID as LINE_DEDUPLICATE_NODE_TYPE_ID,
    handle_node as line_deduplicate_handler,
)
from custom_nodes.opencv_geometry_nodes.backend.nodes.line_intersection import (
    NODE_TYPE_ID as LINE_INTERSECTION_NODE_TYPE_ID,
    handle_node as line_intersection_handler,
)
from custom_nodes.opencv_geometry_nodes.backend.nodes.quadrilateral_from_circle_centers import (
    NODE_TYPE_ID as QUADRILATERAL_FROM_CIRCLE_CENTERS_NODE_TYPE_ID,
    handle_node as quadrilateral_from_circle_centers_handler,
)
from custom_nodes.opencv_geometry_nodes.backend.nodes.quadrilateral_from_lines import (
    NODE_TYPE_ID as QUADRILATERAL_FROM_LINES_NODE_TYPE_ID,
    handle_node as quadrilateral_from_lines_handler,
)
from custom_nodes.opencv_geometry_nodes.backend.nodes.remap import (
    NODE_TYPE_ID as REMAP_NODE_TYPE_ID,
    handle_node as remap_handler,
)
from custom_nodes.opencv_geometry_nodes.backend.nodes.rotation_correct import (
    NODE_TYPE_ID as ROTATION_CORRECT_NODE_TYPE_ID,
    handle_node as rotation_correct_handler,
)
from custom_nodes.opencv_geometry_nodes.backend.nodes.undistort import (
    NODE_TYPE_ID as UNDISTORT_NODE_TYPE_ID,
    handle_node as undistort_handler,
)


NODE_HANDLERS = (
    (AFFINE_TRANSFORM_NODE_TYPE_ID, affine_transform_handler),
    (LINE_DEDUPLICATE_NODE_TYPE_ID, line_deduplicate_handler),
    (LINE_INTERSECTION_NODE_TYPE_ID, line_intersection_handler),
    (PLANAR_TRANSFORM_BRIDGE_NODE_TYPE_ID, planar_transform_bridge_handler),
    (PERSPECTIVE_TRANSFORM_NODE_TYPE_ID, perspective_transform_handler),
    (
        QUADRILATERAL_FROM_CIRCLE_CENTERS_NODE_TYPE_ID,
        quadrilateral_from_circle_centers_handler,
    ),
    (QUADRILATERAL_FROM_LINES_NODE_TYPE_ID, quadrilateral_from_lines_handler),
    (REMAP_NODE_TYPE_ID, remap_handler),
    (ROTATION_CORRECT_NODE_TYPE_ID, rotation_correct_handler),
    (UNDISTORT_NODE_TYPE_ID, undistort_handler),
)


__all__ = ["NODE_HANDLERS"]
