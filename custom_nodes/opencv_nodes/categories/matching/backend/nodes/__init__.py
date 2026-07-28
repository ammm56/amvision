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
from custom_nodes.opencv_nodes.categories.matching.backend.nodes.akaze_keypoints import (
    NODE_TYPE_ID as AKAZE_KEYPOINTS_NODE_TYPE_ID,
    handle_node as akaze_keypoints_handler,
)
from custom_nodes.opencv_nodes.categories.matching.backend.nodes.brisk_keypoints import (
    NODE_TYPE_ID as BRISK_KEYPOINTS_NODE_TYPE_ID,
    handle_node as brisk_keypoints_handler,
)
from custom_nodes.opencv_nodes.categories.matching.backend.nodes.fast_corners import (
    NODE_TYPE_ID as FAST_CORNERS_NODE_TYPE_ID,
    handle_node as fast_corners_handler,
)
from custom_nodes.opencv_nodes.categories.matching.backend.nodes.flann_match import (
    NODE_TYPE_ID as FLANN_MATCH_NODE_TYPE_ID,
    handle_node as flann_match_handler,
)
from custom_nodes.opencv_nodes.categories.matching.backend.nodes.good_features_to_track import (
    NODE_TYPE_ID as GOOD_FEATURES_TO_TRACK_NODE_TYPE_ID,
    handle_node as good_features_to_track_handler,
)
from custom_nodes.opencv_nodes.categories.matching.backend.nodes.line_segment_detect import (
    NODE_TYPE_ID as LINE_SEGMENT_DETECT_NODE_TYPE_ID,
    handle_node as line_segment_detect_handler,
)
from custom_nodes.opencv_nodes.categories.matching.backend.nodes.sift_keypoints import (
    NODE_TYPE_ID as SIFT_KEYPOINTS_NODE_TYPE_ID,
    handle_node as sift_keypoints_handler,
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
    (SIFT_KEYPOINTS_NODE_TYPE_ID, sift_keypoints_handler),
    (AKAZE_KEYPOINTS_NODE_TYPE_ID, akaze_keypoints_handler),
    (BRISK_KEYPOINTS_NODE_TYPE_ID, brisk_keypoints_handler),
    (FLANN_MATCH_NODE_TYPE_ID, flann_match_handler),
    (GOOD_FEATURES_TO_TRACK_NODE_TYPE_ID, good_features_to_track_handler),
    (FAST_CORNERS_NODE_TYPE_ID, fast_corners_handler),
    (LINE_SEGMENT_DETECT_NODE_TYPE_ID, line_segment_detect_handler),
)


__all__ = ["NODE_HANDLERS"]
