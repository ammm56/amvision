"""OpenCV matching 节点双图调试预览工具。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.nodes.debug_image_panel import (
    build_checkbox_control,
    build_circle_overlay,
    build_debug_image_preview_output,
    build_line_overlay,
    build_numeric_control,
    build_polygon_overlay,
    is_debug_image_panel_enabled,
)
from backend.nodes.runtime_support import load_image_matrix_from_payload, register_image_matrix
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


@dataclass(frozen=True)
class PairDebugPreviewContext:
    """描述双图拼接预览的坐标换算信息。"""

    width_a: int
    height_a: int
    width_b: int
    height_b: int
    gap: int

    @property
    def image_b_offset_x(self) -> int:
        """返回右侧图片在拼接图中的 x 偏移。"""

        return self.width_a + self.gap


def build_pair_match_debug_preview_output(
    request: WorkflowNodeExecutionRequest,
    *,
    cv2_module: Any,
    np_module: Any,
    source_a_image: object,
    source_b_image: object,
    title: str,
    artifact_name: str,
    match_items: list[dict[str, object]],
    interaction: dict[str, object],
    inlier_match_ids: set[str] | None = None,
    homography_matrix: Any | None = None,
    selected_match_ids: set[str] | None = None,
    show_match_lines: bool = True,
    show_homography_projection: bool = True,
    selected_match_only: bool = False,
    show_left_points: bool = True,
    show_right_points: bool = True,
    manual_pair_lines_xyxy: list[list[float]] | None = None,
    selected_projection_id: str | None = None,
    max_match_lines: int = 200,
) -> dict[str, object]:
    """构建 ORB Match / Homography 这类双图节点的 debug_preview 输出。

    参数：
    - request：当前节点执行请求。
    - cv2_module / np_module：调用方已加载的 OpenCV / NumPy 模块。
    - source_a_image / source_b_image：两路 local-features 记录的源图。
    - title：图片面板标题。
    - artifact_name：Preview Run artifact 名称。
    - match_items：feature-matches.v1 中的匹配项。
    - interaction：图片面板交互和调参声明。
    - inlier_match_ids：可选内点 id 集合；提供后仅绘制内点匹配线。
    - homography_matrix：可选 3x3 homography，用于把左图外框投影到右图。
    - selected_match_ids：可选高亮 match id 集合，用于图片面板点选后的反馈。
    - show_match_lines：是否绘制匹配线；关闭后仍保留调参控件。
    - show_homography_projection：是否绘制 homography 投影框。
    - selected_match_only：是否只绘制点选的匹配线，便于排查误匹配。
    - show_left_points / show_right_points：是否绘制左右图匹配端点。
    - manual_pair_lines_xyxy：可选手动点对线列表，用于双图人工点对调试。
    - selected_projection_id：可选点选的投影框 id，用于 homography overlay 高亮。
    - max_match_lines：最多绘制的匹配线数量，避免调试图过载。

    返回：
    - dict[str, object]：关闭调试图时返回空 dict。
    """

    if not is_debug_image_panel_enabled(request):
        return {}

    context, pair_image_payload = _build_pair_image_payload(
        request,
        cv2_module=cv2_module,
        np_module=np_module,
        source_a_image=source_a_image,
        source_b_image=source_b_image,
    )
    overlays = (
        _build_pair_match_overlays(
            context,
            match_items=match_items,
            inlier_match_ids=inlier_match_ids,
            selected_match_ids=selected_match_ids or set(),
            selected_match_only=selected_match_only,
            show_left_points=show_left_points,
            show_right_points=show_right_points,
            max_match_lines=max_match_lines,
        )
        if show_match_lines
        else []
    )
    for pair_index, manual_pair_line_xyxy in enumerate(manual_pair_lines_xyxy or (), start=1):
        overlays.append(_build_manual_pair_overlay(manual_pair_line_xyxy, pair_index=pair_index))
    if homography_matrix is not None and show_homography_projection:
        projected_overlay = _build_homography_projection_overlay(
            context,
            cv2_module=cv2_module,
            np_module=np_module,
            homography_matrix=homography_matrix,
            selected_projection_id=selected_projection_id,
        )
        if projected_overlay is not None:
            overlays.append(projected_overlay)

    return build_debug_image_preview_output(
        request,
        image_payload=pair_image_payload,
        title=title,
        artifact_name=artifact_name,
        overlays=overlays,
        interaction=interaction,
    )


def _build_pair_image_payload(
    request: WorkflowNodeExecutionRequest,
    *,
    cv2_module: Any,
    np_module: Any,
    source_a_image: object,
    source_b_image: object,
) -> tuple[PairDebugPreviewContext, dict[str, object]]:
    """读取两路源图并注册拼接后的 raw BGR24 调试图。"""

    if not isinstance(source_a_image, dict) or not isinstance(source_b_image, dict):
        raise InvalidRequestError("匹配调试图要求 features payload 中包含两路 source_image")

    _payload_a, image_matrix_a = load_image_matrix_from_payload(
        request,
        image_payload=source_a_image,
        cv2_module=cv2_module,
        np_module=np_module,
        imdecode_flags=cv2_module.IMREAD_COLOR,
    )
    _payload_b, image_matrix_b = load_image_matrix_from_payload(
        request,
        image_payload=source_b_image,
        cv2_module=cv2_module,
        np_module=np_module,
        imdecode_flags=cv2_module.IMREAD_COLOR,
    )
    image_matrix_a = _ensure_bgr_matrix(cv2_module, image_matrix_a)
    image_matrix_b = _ensure_bgr_matrix(cv2_module, image_matrix_b)

    height_a, width_a = image_matrix_a.shape[:2]
    height_b, width_b = image_matrix_b.shape[:2]
    gap = 24
    canvas_height = max(int(height_a), int(height_b))
    canvas_width = int(width_a) + gap + int(width_b)
    canvas = np_module.full(
        (canvas_height, canvas_width, 3),
        fill_value=24,
        dtype=np_module.uint8,
    )
    canvas[0:int(height_a), 0:int(width_a)] = image_matrix_a
    canvas[0:int(height_b), int(width_a + gap):int(width_a + gap + width_b)] = image_matrix_b
    context = PairDebugPreviewContext(
        width_a=int(width_a),
        height_a=int(height_a),
        width_b=int(width_b),
        height_b=int(height_b),
        gap=gap,
    )
    return context, register_image_matrix(request, image_matrix=canvas)


def _ensure_bgr_matrix(cv2_module: Any, image_matrix: Any) -> Any:
    """把灰度或 BGRA matrix 规整为 BGR matrix。"""

    if len(image_matrix.shape) == 2:
        return cv2_module.cvtColor(image_matrix, cv2_module.COLOR_GRAY2BGR)
    if len(image_matrix.shape) == 3 and image_matrix.shape[2] == 4:
        return cv2_module.cvtColor(image_matrix, cv2_module.COLOR_BGRA2BGR)
    return image_matrix


def _build_pair_match_overlays(
    context: PairDebugPreviewContext,
    *,
    match_items: list[dict[str, object]],
    inlier_match_ids: set[str] | None,
    selected_match_ids: set[str],
    selected_match_only: bool,
    show_left_points: bool,
    show_right_points: bool,
    max_match_lines: int,
) -> list[dict[str, object]]:
    """把 feature match 转成拼接图坐标系下的匹配线 overlay。"""

    overlays: list[dict[str, object]] = []
    match_line_count = 0
    for match_item in match_items:
        match_id = str(match_item.get("match_id") or f"match-{match_line_count + 1}")
        if inlier_match_ids is not None and match_id not in inlier_match_ids:
            continue
        if selected_match_only and selected_match_ids and match_id not in selected_match_ids:
            continue
        query_xy = match_item.get("query_xy")
        train_xy = match_item.get("train_xy")
        if not isinstance(query_xy, list) or len(query_xy) < 2:
            continue
        if not isinstance(train_xy, list) or len(train_xy) < 2:
            continue
        is_selected = match_id in selected_match_ids
        label_prefix = "selected" if is_selected else ("inlier" if inlier_match_ids is not None else "match")
        overlays.append(
            build_line_overlay(
                kind="match-line",
                overlay_id=match_id,
                label=f"{label_prefix} {match_id}",
                line_xyxy=[
                    float(query_xy[0]),
                    float(query_xy[1]),
                    float(train_xy[0]) + float(context.image_b_offset_x),
                    float(train_xy[1]),
                ],
                target_parameters=["debug_selected_match_ids"],
                parameters={
                    "debug_selected_match_ids": [match_id],
                    "selected_match_ids": [match_id],
                    "selection_mode": "toggle",
                    "match_role": label_prefix,
                    "query_xy": [round(float(query_xy[0]), 4), round(float(query_xy[1]), 4)],
                    "train_xy": [round(float(train_xy[0]), 4), round(float(train_xy[1]), 4)],
                },
            )
        )
        if show_left_points:
            overlays.append(
                _build_pair_endpoint_overlay(
                    match_id=match_id,
                    side="left",
                    point_x=float(query_xy[0]),
                    point_y=float(query_xy[1]),
                    selected=is_selected,
                )
            )
        if show_right_points:
            overlays.append(
                _build_pair_endpoint_overlay(
                    match_id=match_id,
                    side="right",
                    point_x=float(train_xy[0]) + float(context.image_b_offset_x),
                    point_y=float(train_xy[1]),
                    selected=is_selected,
                )
            )
        match_line_count += 1
        if match_line_count >= max_match_lines:
            break
    return overlays


def _build_pair_endpoint_overlay(
    *,
    match_id: str,
    side: str,
    point_x: float,
    point_y: float,
    selected: bool,
) -> dict[str, object]:
    """构建左右图匹配端点 overlay，辅助用户确认匹配线落点。"""

    label = f"{side} {match_id}" if not selected else f"selected {side} {match_id}"
    return build_circle_overlay(
        kind="match-point",
        overlay_id=f"{match_id}-{side}-point",
        label=label,
        center_x=point_x,
        center_y=point_y,
        radius=6.0 if selected else 4.0,
        target_parameters=["debug_selected_match_ids"],
        parameters={
            "debug_selected_match_ids": [match_id],
            "selected_match_ids": [match_id],
            "selection_mode": "toggle",
            "match_point_side": side,
        },
    )


def _build_manual_pair_overlay(manual_pair_line_xyxy: list[float], *, pair_index: int) -> dict[str, object]:
    """构建用户在双图上手动画出的点对线。"""

    normalized_line = [round(float(item), 4) for item in manual_pair_line_xyxy[:4]]
    return build_line_overlay(
        kind="point-pair",
        overlay_id=f"manual-pair-{pair_index}",
        label=f"manual pair {pair_index}",
        line_xyxy=normalized_line,
        target_parameters=["debug_manual_pair_lines_xyxy"],
        parameters={
            "debug_manual_pair_lines_xyxy": [normalized_line],
        },
    )


def _build_homography_projection_overlay(
    context: PairDebugPreviewContext,
    *,
    cv2_module: Any,
    np_module: Any,
    homography_matrix: Any,
    selected_projection_id: str | None,
) -> dict[str, object] | None:
    """把左图外框通过 homography 投影到右图并返回 polygon overlay。"""

    source_corners = np_module.array(
        [
            [[0.0, 0.0]],
            [[float(context.width_a), 0.0]],
            [[float(context.width_a), float(context.height_a)]],
            [[0.0, float(context.height_a)]],
        ],
        dtype=np_module.float32,
    )
    try:
        projected_corners = cv2_module.perspectiveTransform(source_corners, homography_matrix).reshape(-1, 2)
    except cv2_module.error:
        return None
    polygon_xy: list[list[float]] = []
    for point in projected_corners:
        polygon_xy.append(
            [
                round(float(point[0]) + float(context.image_b_offset_x), 4),
                round(float(point[1]), 4),
            ]
        )
    projection_id = "homography-projection"
    is_selected = selected_projection_id == projection_id
    return build_polygon_overlay(
        kind="homography-overlay",
        overlay_id=projection_id,
        label="selected homography projection" if is_selected else "homography projection",
        polygon_xy=polygon_xy,
        target_parameters=["debug_selected_projection_id"],
        parameters={
            "debug_selected_projection_id": projection_id,
            "selected_projection_id": projection_id,
            "overlay_role": "homography-projection",
        },
    )
