"""OpenCV 匹配节点模块集合。"""

from __future__ import annotations

from custom_nodes.opencv_matching_nodes.backend.nodes.homography_estimate import (
    NODE_TYPE_ID as HOMOGRAPHY_ESTIMATE_NODE_TYPE_ID,
    handle_node as homography_estimate_handler,
)
from custom_nodes.opencv_matching_nodes.backend.nodes.orb_keypoints import (
    NODE_TYPE_ID as ORB_KEYPOINTS_NODE_TYPE_ID,
    handle_node as orb_keypoints_handler,
)
from custom_nodes.opencv_matching_nodes.backend.nodes.orb_match import (
    NODE_TYPE_ID as ORB_MATCH_NODE_TYPE_ID,
    handle_node as orb_match_handler,
)
from custom_nodes.opencv_matching_nodes.backend.nodes.template_match import (
    NODE_TYPE_ID as TEMPLATE_MATCH_NODE_TYPE_ID,
    handle_node as template_match_handler,
)


NODE_HANDLERS = (
    (TEMPLATE_MATCH_NODE_TYPE_ID, template_match_handler),
    (ORB_KEYPOINTS_NODE_TYPE_ID, orb_keypoints_handler),
    (ORB_MATCH_NODE_TYPE_ID, orb_match_handler),
    (HOMOGRAPHY_ESTIMATE_NODE_TYPE_ID, homography_estimate_handler),
)


__all__ = ["NODE_HANDLERS"]
