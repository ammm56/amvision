"""Contour 类节点的 debug image preview 工具。"""

from __future__ import annotations

from collections.abc import Iterable

from backend.nodes.debug_image_panel import build_debug_image_preview_output
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def build_contours_debug_preview_output(
    request: WorkflowNodeExecutionRequest,
    *,
    contours_payload: dict[str, object],
    contour_items: Iterable[dict[str, object]],
    title: str,
    artifact_name: str,
) -> dict[str, object]:
    """按 contours.v1 的 source_image 构造 debug_preview 输出。

    参数：
    - request：workflow 节点执行请求。
    - contours_payload：输入或输出的 contours.v1 payload。
    - contour_items：需要显示的 contour 列表。
    - title：图片面板标题。
    - artifact_name：Preview Run artifact 名称。

    返回：
    - dict[str, object]：debug_preview 输出；未启用或缺少 source_image 时返回空 dict。
    """

    source_image = contours_payload.get("source_image")
    if not isinstance(source_image, dict):
        return {}
    return build_debug_image_preview_output(
        request,
        image_payload=source_image,
        title=title,
        artifact_name=artifact_name,
        overlays=_build_contour_overlays(list(contour_items)),
        interaction={
            "mode": "edit",
            "coordinate_space": "source-image",
            "tools": [
                {
                    "tool": "contour",
                    "label": "轮廓点选",
                    "target_parameters": ["selected_contour_index"],
                    "min_points": 3,
                },
            ],
            "controls": [],
        },
    )


def _build_contour_overlays(contour_items: list[dict[str, object]]) -> list[dict[str, object]]:
    """把 contour 列表转换为图片面板 overlay。"""

    overlays: list[dict[str, object]] = []
    for item_index, contour_item in enumerate(contour_items[:120], start=1):
        raw_points = contour_item.get("points")
        if not isinstance(raw_points, list) or len(raw_points) < 3:
            continue
        contour_index = int(contour_item.get("contour_index", item_index))
        overlays.append(
            {
                "kind": "polygon",
                "id": f"contour-{contour_index}",
                "label": f"contour {contour_index}",
                "points_xy": _decimate_points(raw_points, max_points=160),
                "target_parameters": ["selected_contour_index"],
                "parameters": {"selected_contour_index": contour_index},
            }
        )
    return overlays


def _decimate_points(raw_points: list[object], *, max_points: int) -> list[list[float]]:
    """限制 overlay 点数，避免调试预览在大轮廓上过重。"""

    if len(raw_points) <= max_points:
        selected_points = raw_points
    else:
        step = max(1, int(len(raw_points) / max_points))
        selected_points = raw_points[::step][:max_points]
    points_xy: list[list[float]] = []
    for point in selected_points:
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            continue
        points_xy.append([float(point[0]), float(point[1])])
    return points_xy
