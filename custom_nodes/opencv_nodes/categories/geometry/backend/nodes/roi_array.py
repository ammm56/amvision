"""将可编辑首个 ROI 按二维行列向量复制；可显式接入矩形裁剪坐标框。"""

import math
from typing import Annotated

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, ValidationError

from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.nodes.core_nodes.support.roi import (
    build_roi_list_payload,
    build_roi_payload,
    polygon_area,
    polygon_bbox_xyxy,
    require_roi_payload,
)
from backend.nodes.debug_image_panel import (
    build_debug_image_preview_output,
    build_debug_panel_interaction,
    build_number_control,
    build_polygon_overlay,
)
from backend.nodes.roi_array_interaction import build_array_step_tools
from backend.nodes.runtime_support import require_image_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.execution.execution_control import (
    build_node_execution_control,
)

NODE_TYPE_ID = "custom.opencv.roi-array"


class Settings(BaseModel):
    """数量、二维位移和稳定名称；不依赖画布坐标或上游返回次序。"""

    model_config = ConfigDict(extra="ignore")  # 图片调试面板参数由公共层读取。
    rows: Annotated[int, Field(strict=True, ge=1, le=100)] = 1
    columns: Annotated[int, Field(strict=True, ge=1, le=100)] = 1
    column_step_xy: tuple[FiniteFloat, FiniteFloat] = (100, 0)
    row_step_xy: tuple[FiniteFloat, FiniteFloat] = (0, 100)
    roi_id_prefix: Annotated[str, Field(min_length=1, max_length=80)] = "roi"


def handle_node(request):
    """输出父图坐标中的 ROI 列表；frame 为裁图矩形，seed 使用该裁图局部坐标。"""
    control = build_node_execution_control(request)
    try:
        settings = Settings.model_validate(request.parameters)
    except ValidationError as exc:
        raise InvalidRequestError("ROI Array 参数无效") from exc
    if settings.rows * settings.columns > 1024:
        raise InvalidRequestError("ROI Array 最多生成 1024 项")
    column, row = np.asarray(settings.column_step_xy), np.asarray(settings.row_step_xy)
    if (settings.columns > 1 and np.linalg.norm(column) < 1e-8) or (
        settings.rows > 1 and np.linalg.norm(row) < 1e-8
    ):
        raise InvalidRequestError("多行或多列的位移向量不能为零")
    if (
        settings.rows > 1
        and settings.columns > 1
        and abs(np.linalg.det([column, row])) < 1e-8
    ):
        raise InvalidRequestError("二维阵列的行列向量不能共线")
    seed = require_roi_payload(request.input_values.get("roi"))
    points = np.asarray(seed["polygon_xy"], dtype=float)
    if not np.isfinite(points).all() or polygon_area(points.tolist()) <= 0:
        raise InvalidRequestError("首个 ROI 必须是有限且非零面积的多边形")
    if not np.allclose(
        seed["bbox_xyxy"], polygon_bbox_xyxy(points.tolist()), rtol=0, atol=1e-8
    ):
        raise InvalidRequestError("首个 ROI 的 bbox 与多边形范围不一致")
    source = request.input_values.get("image")
    frame = request.input_values.get("frame")
    offset = np.zeros(2)
    bounds = None
    if frame is not None:
        frame = require_roi_payload(frame)
        if frame["roi_kind"] != "bbox":
            raise InvalidRequestError("Frame 仅支持未缩放的矩形裁剪框")
        x1, y1, x2, y2 = frame["bbox_xyxy"]
        if not all(math.isfinite(v) for v in (x1, y1, x2, y2)) or x1 >= x2 or y1 >= y2:
            raise InvalidRequestError("Frame 必须是有限且非零面积的矩形")
        bounds = [math.floor(x1), math.floor(y1), math.ceil(x2), math.ceil(y2)]
        offset = np.asarray(bounds[:2])
        source = source or frame.get("source_image")
        seed_image = seed.get("source_image")
        if seed_image and (seed_image.get("width"), seed_image.get("height")) != (
            bounds[2] - bounds[0],
            bounds[3] - bounds[1],
        ):
            raise InvalidRequestError("首槽图尺寸与 Frame 裁剪尺寸不一致，不能隐式缩放")
    source = require_image_payload(source) if source is not None else None
    if source is not None:
        width, height = source["width"], source["height"]
        if bounds and not (
            0 <= bounds[0] < bounds[2] <= width and 0 <= bounds[1] < bounds[3] <= height
        ):
            raise InvalidRequestError("Frame 超出父图范围")
        bounds = bounds or [0, 0, width, height]
    items, overlays = [], []
    prefix = settings.roi_id_prefix.strip()
    if not prefix:
        raise InvalidRequestError("ROI 名称前缀不能为空")
    for r in range(settings.rows):
        for c in range(settings.columns):
            control.raise_if_cancelled_or_expired()
            polygon = (points + offset + r * row + c * column).tolist()
            bbox = polygon_bbox_xyxy(polygon)
            if bounds and not (
                bounds[0] <= bbox[0] < bbox[2] <= bounds[2]
                and bounds[1] <= bbox[1] < bbox[3] <= bounds[3]
            ):
                raise InvalidRequestError(
                    "阵列 ROI 超出 Frame 或图像范围",
                    details={"row": r + 1, "column": c + 1},
                )
            identifier = f"{prefix}-r{r + 1:02}-c{c + 1:02}"
            items.append(
                build_roi_payload(
                    roi_id=identifier,
                    display_name=identifier,
                    roi_kind=seed["roi_kind"],
                    bbox_xyxy=bbox,
                    polygon_xy=polygon,
                    area=polygon_area(polygon),
                    source_image=source,
                )
            )
            overlays.append(
                build_polygon_overlay(
                    overlay_id=identifier, label=identifier, polygon_xy=polygon
                )
            )
    result = {
        "rois": build_roi_list_payload(items),
        "summary": build_value_payload(
            {
                "count": len(items),
                "rows": settings.rows,
                "columns": settings.columns,
                "column_step_xy": column.tolist(),
                "row_step_xy": row.tolist(),
                "frame_offset_xy": offset.tolist(),
                "coordinate_space": "parent-image-pixels",
                "items": [
                    {"item_id": item["roi_id"], "source": item} for item in items
                ],
            }
        ),
    }
    if source is not None:
        result.update(
            build_debug_image_preview_output(
                request,
                image_payload=source,
                title="ROI Array",
                artifact_name="roi-array-preview",
                overlays=overlays,
                interaction=build_debug_panel_interaction(
                    tools=build_array_step_tools(
                        anchor=(points.mean(axis=0) + offset).tolist(),
                        column=column.tolist(),
                        row=row.tolist(),
                        vector_parameters=True,
                    ),
                    controls=[
                        build_number_control(
                            "rows",
                            "Rows",
                            settings.rows,
                            min_value=1,
                            max_value=100,
                            step=1,
                        ),
                        build_number_control(
                            "columns",
                            "Columns",
                            settings.columns,
                            min_value=1,
                            max_value=100,
                            step=1,
                        ),
                    ],
                ),
            )
        )
    return result
