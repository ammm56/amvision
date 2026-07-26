"""Contour 类节点的 debug image preview 工具。"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from backend.nodes.debug_image_panel import (
    build_debug_image_preview_output,
    build_debug_panel_interaction,
    build_interaction_tool,
    build_polygon_overlay,
)
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def build_contours_debug_preview_output(
    request: WorkflowNodeExecutionRequest,
    *,
    contours_payload: dict[str, object],
    contour_items: Iterable[dict[str, object]],
    title: str,
    artifact_name: str,
    selected_contour_index: int | None = None,
    controls: Iterable[Mapping[str, object]] | None = None,
) -> dict[str, object]:
    """按 contours.v1 的 source_image 构造 debug_preview 输出。

    参数：
    - request：workflow 节点执行请求。
    - contours_payload：输入或输出的 contours.v1 payload。
    - contour_items：需要显示的 contour 列表。
    - title：图片面板标题。
    - artifact_name：Preview Run artifact 名称。
    - selected_contour_index：当前节点已经点选的 contour index，用于高亮反馈。
    - controls：可选调参控件，供 contour 消费节点复用。

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
        overlays=_build_contour_overlays(
            list(contour_items),
            selected_contour_index=selected_contour_index,
        ),
        interaction=build_debug_panel_interaction(
            tools=[
                build_interaction_tool(
                    "contour",
                    "轮廓点选",
                    ["selected_contour_index"],
                    extra={"min_points": 3},
                ),
            ],
            controls=controls,
        ),
    )


def _build_contour_overlays(
    contour_items: list[dict[str, object]],
    *,
    selected_contour_index: int | None,
) -> list[dict[str, object]]:
    """把 contour 列表转换为图片面板 overlay。"""

    overlays: list[dict[str, object]] = []
    for item_index, contour_item in enumerate(contour_items[:120], start=1):
        raw_points = contour_item.get("points")
        if not isinstance(raw_points, list) or len(raw_points) < 3:
            continue
        contour_index = int(contour_item.get("contour_index", item_index))
        is_selected = selected_contour_index is not None and contour_index == selected_contour_index
        overlays.append(
            build_polygon_overlay(
                kind="selected-contour" if is_selected else "contour",
                overlay_id=f"contour-{contour_index}",
                label=f"selected contour {contour_index}" if is_selected else f"contour {contour_index}",
                polygon_xy=_decimate_points(raw_points, max_points=160),
                target_parameters=["selected_contour_index"],
                parameters={"selected_contour_index": contour_index},
            )
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
