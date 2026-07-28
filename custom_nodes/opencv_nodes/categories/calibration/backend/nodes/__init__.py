"""OpenCV 标定节点模块集合。"""

from __future__ import annotations

from custom_nodes.opencv_nodes.categories.calibration.backend.nodes.camera_calibrate import (
    NODE_TYPE_ID as CAMERA_CALIBRATE_NODE_TYPE_ID,
    handle_node as camera_calibrate_handler,
)
from custom_nodes.opencv_nodes.categories.calibration.backend.nodes.chessboard_corners import (
    NODE_TYPE_ID as CHESSBOARD_CORNERS_NODE_TYPE_ID,
    handle_node as chessboard_corners_handler,
)
from custom_nodes.opencv_nodes.categories.calibration.backend.nodes.solve_pnp import (
    NODE_TYPE_ID as SOLVE_PNP_NODE_TYPE_ID,
    handle_node as solve_pnp_handler,
)
from custom_nodes.opencv_nodes.categories.calibration.backend.nodes.circle_grid_detect import (
    NODE_TYPE_ID as CIRCLE_GRID_DETECT_NODE_TYPE_ID,
    handle_node as circle_grid_detect_handler,
)
from custom_nodes.opencv_nodes.categories.calibration.backend.nodes.corner_subpix import (
    NODE_TYPE_ID as CORNER_SUBPIX_NODE_TYPE_ID,
    handle_node as corner_subpix_handler,
)
from custom_nodes.opencv_nodes.categories.calibration.backend.nodes.fisheye_calibrate import (
    NODE_TYPE_ID as FISHEYE_CALIBRATE_NODE_TYPE_ID,
    handle_node as fisheye_calibrate_handler,
)
from custom_nodes.opencv_nodes.categories.calibration.backend.nodes.hand_eye_calibrate import (
    NODE_TYPE_ID as HAND_EYE_CALIBRATE_NODE_TYPE_ID,
    handle_node as hand_eye_calibrate_handler,
)
from custom_nodes.opencv_nodes.categories.calibration.backend.nodes.project_points import (
    NODE_TYPE_ID as PROJECT_POINTS_NODE_TYPE_ID,
    handle_node as project_points_handler,
)
from custom_nodes.opencv_nodes.categories.calibration.backend.nodes.undistort_points import (
    NODE_TYPE_ID as UNDISTORT_POINTS_NODE_TYPE_ID,
    handle_node as undistort_points_handler,
)

NODE_HANDLERS = (
    (CHESSBOARD_CORNERS_NODE_TYPE_ID, chessboard_corners_handler),
    (CAMERA_CALIBRATE_NODE_TYPE_ID, camera_calibrate_handler),
    (SOLVE_PNP_NODE_TYPE_ID, solve_pnp_handler),
    (CIRCLE_GRID_DETECT_NODE_TYPE_ID, circle_grid_detect_handler),
    (CORNER_SUBPIX_NODE_TYPE_ID, corner_subpix_handler),
    (FISHEYE_CALIBRATE_NODE_TYPE_ID, fisheye_calibrate_handler),
    (PROJECT_POINTS_NODE_TYPE_ID, project_points_handler),
    (UNDISTORT_POINTS_NODE_TYPE_ID, undistort_points_handler),
    (HAND_EYE_CALIBRATE_NODE_TYPE_ID, hand_eye_calibrate_handler),
)

__all__ = ["NODE_HANDLERS"]
