"""OpenCV 几何节点模块集合。"""

from __future__ import annotations

from custom_nodes.opencv_nodes.categories.geometry.backend.nodes.affine_transform import (
    NODE_TYPE_ID as AFFINE_TRANSFORM_NODE_TYPE_ID,
    handle_node as affine_transform_handler,
)
from custom_nodes.opencv_nodes.categories.geometry.backend.nodes.planar_transform_bridge import (
    NODE_TYPE_ID as PLANAR_TRANSFORM_BRIDGE_NODE_TYPE_ID,
    handle_node as planar_transform_bridge_handler,
)
from custom_nodes.opencv_nodes.categories.geometry.backend.nodes.perspective_transform import (
    NODE_TYPE_ID as PERSPECTIVE_TRANSFORM_NODE_TYPE_ID,
    handle_node as perspective_transform_handler,
)
from custom_nodes.opencv_nodes.categories.geometry.backend.nodes.line_deduplicate import (
    NODE_TYPE_ID as LINE_DEDUPLICATE_NODE_TYPE_ID,
    handle_node as line_deduplicate_handler,
)
from custom_nodes.opencv_nodes.categories.geometry.backend.nodes.line_intersection import (
    NODE_TYPE_ID as LINE_INTERSECTION_NODE_TYPE_ID,
    handle_node as line_intersection_handler,
)
from custom_nodes.opencv_nodes.categories.geometry.backend.nodes.quadrilateral_from_circle_centers import (
    NODE_TYPE_ID as QUADRILATERAL_FROM_CIRCLE_CENTERS_NODE_TYPE_ID,
    handle_node as quadrilateral_from_circle_centers_handler,
)
from custom_nodes.opencv_nodes.categories.geometry.backend.nodes.quadrilateral_from_lines import (
    NODE_TYPE_ID as QUADRILATERAL_FROM_LINES_NODE_TYPE_ID,
    handle_node as quadrilateral_from_lines_handler,
)
from custom_nodes.opencv_nodes.categories.geometry.backend.nodes.remap import (
    NODE_TYPE_ID as REMAP_NODE_TYPE_ID,
    handle_node as remap_handler,
)
from custom_nodes.opencv_nodes.categories.geometry.backend.nodes.rotation_correct import (
    NODE_TYPE_ID as ROTATION_CORRECT_NODE_TYPE_ID,
    handle_node as rotation_correct_handler,
)
from custom_nodes.opencv_nodes.categories.geometry.backend.nodes.undistort import (
    NODE_TYPE_ID as UNDISTORT_NODE_TYPE_ID,
    handle_node as undistort_handler,
)
from custom_nodes.opencv_nodes.categories.geometry.backend.nodes.flip import (
    NODE_TYPE_ID as FLIP_NODE_TYPE_ID,
    handle_node as flip_handler,
)
from custom_nodes.opencv_nodes.categories.geometry.backend.nodes.get_rect_subpix import (
    NODE_TYPE_ID as GET_RECT_SUBPIX_NODE_TYPE_ID,
    handle_node as get_rect_subpix_handler,
)
from custom_nodes.opencv_nodes.categories.geometry.backend.nodes.pad_border import (
    NODE_TYPE_ID as PAD_BORDER_NODE_TYPE_ID,
    handle_node as pad_border_handler,
)
from custom_nodes.opencv_nodes.categories.geometry.backend.nodes.transpose import (
    NODE_TYPE_ID as TRANSPOSE_NODE_TYPE_ID,
    handle_node as transpose_handler,
)
from custom_nodes.opencv_nodes.categories.geometry.backend.nodes.warp_polar import (
    NODE_TYPE_ID as WARP_POLAR_NODE_TYPE_ID,
    handle_node as warp_polar_handler,
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
    (GET_RECT_SUBPIX_NODE_TYPE_ID, get_rect_subpix_handler),
    (WARP_POLAR_NODE_TYPE_ID, warp_polar_handler),
    (FLIP_NODE_TYPE_ID, flip_handler),
    (TRANSPOSE_NODE_TYPE_ID, transpose_handler),
    (PAD_BORDER_NODE_TYPE_ID, pad_border_handler),
)


__all__ = ["NODE_HANDLERS"]
