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

NODE_HANDLERS = (
    (CHESSBOARD_CORNERS_NODE_TYPE_ID, chessboard_corners_handler),
    (CAMERA_CALIBRATE_NODE_TYPE_ID, camera_calibrate_handler),
    (SOLVE_PNP_NODE_TYPE_ID, solve_pnp_handler),
)

__all__ = ["NODE_HANDLERS"]
