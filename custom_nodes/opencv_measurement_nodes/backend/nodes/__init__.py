"""OpenCV 量测节点模块集合。"""

from __future__ import annotations

from custom_nodes.opencv_measurement_nodes.backend.nodes.caliper_edge import (
    NODE_TYPE_ID as CALIPER_EDGE_NODE_TYPE_ID,
    handle_node as caliper_edge_handler,
)
from custom_nodes.opencv_measurement_nodes.backend.nodes.circle_diameter import (
    NODE_TYPE_ID as CIRCLE_DIAMETER_NODE_TYPE_ID,
    handle_node as circle_diameter_handler,
)
from custom_nodes.opencv_measurement_nodes.backend.nodes.concentricity_metrics import (
    NODE_TYPE_ID as CONCENTRICITY_METRICS_NODE_TYPE_ID,
    handle_node as concentricity_metrics_handler,
)
from custom_nodes.opencv_measurement_nodes.backend.nodes.line_angle import (
    NODE_TYPE_ID as LINE_ANGLE_NODE_TYPE_ID,
    handle_node as line_angle_handler,
)
from custom_nodes.opencv_measurement_nodes.backend.nodes.measure import (
    NODE_TYPE_ID as MEASURE_NODE_TYPE_ID,
    handle_node as measure_handler,
)
from custom_nodes.opencv_measurement_nodes.backend.nodes.parallelism_metrics import (
    NODE_TYPE_ID as PARALLELISM_METRICS_NODE_TYPE_ID,
    handle_node as parallelism_metrics_handler,
)
from custom_nodes.opencv_measurement_nodes.backend.nodes.point_distance import (
    NODE_TYPE_ID as POINT_DISTANCE_NODE_TYPE_ID,
    handle_node as point_distance_handler,
)
from custom_nodes.opencv_measurement_nodes.backend.nodes.point_to_line_distance import (
    NODE_TYPE_ID as POINT_TO_LINE_DISTANCE_NODE_TYPE_ID,
    handle_node as point_to_line_distance_handler,
)
from custom_nodes.opencv_measurement_nodes.backend.nodes.slot_width import (
    NODE_TYPE_ID as SLOT_WIDTH_NODE_TYPE_ID,
    handle_node as slot_width_handler,
)


NODE_HANDLERS = (
    (CALIPER_EDGE_NODE_TYPE_ID, caliper_edge_handler),
    (CIRCLE_DIAMETER_NODE_TYPE_ID, circle_diameter_handler),
    (CONCENTRICITY_METRICS_NODE_TYPE_ID, concentricity_metrics_handler),
    (LINE_ANGLE_NODE_TYPE_ID, line_angle_handler),
    (MEASURE_NODE_TYPE_ID, measure_handler),
    (PARALLELISM_METRICS_NODE_TYPE_ID, parallelism_metrics_handler),
    (POINT_DISTANCE_NODE_TYPE_ID, point_distance_handler),
    (POINT_TO_LINE_DISTANCE_NODE_TYPE_ID, point_to_line_distance_handler),
    (SLOT_WIDTH_NODE_TYPE_ID, slot_width_handler),
)


__all__ = ["NODE_HANDLERS"]

