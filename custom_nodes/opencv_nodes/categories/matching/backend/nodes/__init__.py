"""OpenCV 匹配节点模块集合。"""

from __future__ import annotations

from custom_nodes.opencv_nodes.categories.matching.backend.nodes.homography_estimate import (
    NODE_TYPE_ID as HOMOGRAPHY_ESTIMATE_NODE_TYPE_ID,
    handle_node as homography_estimate_handler,
)
from custom_nodes.opencv_nodes.categories.matching.backend.nodes.orb_keypoints import (
    NODE_TYPE_ID as ORB_KEYPOINTS_NODE_TYPE_ID,
    handle_node as orb_keypoints_handler,
)
from custom_nodes.opencv_nodes.categories.matching.backend.nodes.orb_match import (
    NODE_TYPE_ID as ORB_MATCH_NODE_TYPE_ID,
    handle_node as orb_match_handler,
)
from custom_nodes.opencv_nodes.categories.matching.backend.nodes.template_match import (
    NODE_TYPE_ID as TEMPLATE_MATCH_NODE_TYPE_ID,
    handle_node as template_match_handler,
)
from custom_nodes.opencv_nodes.categories.matching.backend.nodes.ecc_align import (
    NODE_TYPE_ID as ECC_ALIGN_NODE_TYPE_ID,
    handle_node as ecc_align_handler,
)
from custom_nodes.opencv_nodes.categories.matching.backend.nodes.multi_scale_template_match import (
    NODE_TYPE_ID as MULTI_SCALE_TEMPLATE_MATCH_NODE_TYPE_ID,
    handle_node as multi_scale_template_match_handler,
)
from custom_nodes.opencv_nodes.categories.matching.backend.nodes.phase_correlation import (
    NODE_TYPE_ID as PHASE_CORRELATION_NODE_TYPE_ID,
    handle_node as phase_correlation_handler,
)
from custom_nodes.opencv_nodes.categories.matching.backend.nodes.rotation_scale_template_match import (
    NODE_TYPE_ID as ROTATION_SCALE_TEMPLATE_MATCH_NODE_TYPE_ID,
    handle_node as rotation_scale_template_match_handler,
)


NODE_HANDLERS = (
    (PHASE_CORRELATION_NODE_TYPE_ID, phase_correlation_handler),
    (ECC_ALIGN_NODE_TYPE_ID, ecc_align_handler),
    (MULTI_SCALE_TEMPLATE_MATCH_NODE_TYPE_ID, multi_scale_template_match_handler),
    (ROTATION_SCALE_TEMPLATE_MATCH_NODE_TYPE_ID, rotation_scale_template_match_handler),
    (TEMPLATE_MATCH_NODE_TYPE_ID, template_match_handler),
    (ORB_KEYPOINTS_NODE_TYPE_ID, orb_keypoints_handler),
    (ORB_MATCH_NODE_TYPE_ID, orb_match_handler),
    (HOMOGRAPHY_ESTIMATE_NODE_TYPE_ID, homography_estimate_handler),
)


__all__ = ["NODE_HANDLERS"]
