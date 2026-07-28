"""Histogram 节点实现。"""

from __future__ import annotations

from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.opencv_nodes.shared.backend.runtime.atomic_ops import read_int
from custom_nodes.opencv_nodes.shared.backend.runtime.images import load_image_matrix
from custom_nodes.opencv_nodes.shared.backend.runtime.imports import require_opencv_imports
from custom_nodes.opencv_nodes.shared.backend.runtime.search_roi import resolve_search_roi

NODE_TYPE_ID = "custom.opencv.histogram"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """计算整图或 ROI 的逐通道直方图。"""

    cv2_module, _ = require_opencv_imports()
    image_payload, _, image = load_image_matrix(request, imdecode_flags=cv2_module.IMREAD_UNCHANGED)
    search_roi = resolve_search_roi(request, image_matrix=image)
    selected = search_roi.image_matrix
    bins = read_int(request.parameters.get("bins"), field_name="bins", default=256, minimum=2, maximum=4096)
    raw_channels = request.parameters.get("channels")
    channel_count = 1 if len(selected.shape) == 2 else int(selected.shape[2])
    channels = list(range(channel_count)) if raw_channels is None or raw_channels == "" else raw_channels
    if not isinstance(channels, list) or any(
        isinstance(item, bool) or not isinstance(item, int) or item < 0 or item >= channel_count
        for item in channels
    ):
        raise InvalidRequestError("channels 必须是有效的通道序号数组")
    items: list[dict[str, object]] = []
    for channel_index in channels:
        values = cv2_module.calcHist([selected], [channel_index], None, [bins], [0, 256]).reshape(-1)
        items.append(
            {
                "channel_index": channel_index,
                "bins": bins,
                "range": [0.0, 256.0],
                "sample_count": int(values.sum()),
                "values": [float(value) for value in values.tolist()],
            }
        )
    return {
        "histogram": build_value_payload(
            {
                "source_image": image_payload,
                "roi_bbox_xyxy": search_roi.bbox_xyxy,
                "channel_count": channel_count,
                "items": items,
            }
        )
    }
