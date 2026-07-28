"""ROI Intensity Statistics 节点实现。"""

from __future__ import annotations

from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.opencv_nodes.shared.backend.runtime.images import load_image_matrix
from custom_nodes.opencv_nodes.shared.backend.runtime.imports import require_opencv_imports
from custom_nodes.opencv_nodes.shared.backend.runtime.search_roi import resolve_search_roi

NODE_TYPE_ID = "custom.opencv.roi-intensity-statistics"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """计算整图或 ROI 各通道强度统计。"""

    cv2_module, np_module = require_opencv_imports()
    image_payload, _, image = load_image_matrix(request, imdecode_flags=cv2_module.IMREAD_UNCHANGED)
    search_roi = resolve_search_roi(request, image_matrix=image)
    selected = search_roi.image_matrix
    channels = [selected] if len(selected.shape) == 2 else list(cv2_module.split(selected))
    channel_items: list[dict[str, object]] = []
    for channel_index, channel in enumerate(channels):
        percentiles = np_module.percentile(channel, [1, 5, 25, 50, 75, 95, 99])
        channel_items.append(
            {
                "channel_index": channel_index,
                "minimum": float(channel.min()),
                "maximum": float(channel.max()),
                "mean": float(channel.mean()),
                "standard_deviation": float(channel.std()),
                "percentiles": {
                    "p01": float(percentiles[0]),
                    "p05": float(percentiles[1]),
                    "p25": float(percentiles[2]),
                    "p50": float(percentiles[3]),
                    "p75": float(percentiles[4]),
                    "p95": float(percentiles[5]),
                    "p99": float(percentiles[6]),
                },
            }
        )
    return {
        "statistics": build_value_payload(
            {
                "source_image": image_payload,
                "roi_bbox_xyxy": search_roi.bbox_xyxy,
                "width": int(selected.shape[1]),
                "height": int(selected.shape[0]),
                "pixel_count": int(selected.shape[0] * selected.shape[1]),
                "channel_count": len(channels),
                "channels": channel_items,
            }
        )
    }
