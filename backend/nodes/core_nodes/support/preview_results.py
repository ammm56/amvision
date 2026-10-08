"""通用结果表与原图的显式绑定；只校验身份和显示几何，不计算测量值。"""

import hashlib
import json
from typing import Annotated, Literal

from pydantic import Field, model_validator

from backend.contracts.workflows.metrology import Contract, Identifier, ImageIdentity, Point, unique_ids
from backend.service.application.errors import InvalidRequestError


class ResultShape(Contract):
    """检查项的显示位置；expected 表示名义位置，不能解释为实测几何。"""

    item_id: Identifier
    kind: Literal["line", "expected-point", "point"]
    points: Annotated[tuple[Point, ...], Field(min_length=1, max_length=2)]

    @model_validator(mode="after")
    def check_points(self):
        """线需要两个端点，其余位置只接受一个点。"""
        if len(self.points) != (2 if self.kind == "line" else 1):
            raise ValueError("结果几何点数与类型不匹配")
        return self


class ResultGeometry(Contract):
    """同次观测的有界图形集合；行业包提供，Core 只校验和转发。"""

    observation_id: Identifier
    image: ImageIdentity
    items: Annotated[tuple[ResultShape, ...], Field(max_length=9216)]

    @model_validator(mode="after")
    def check_ids(self):
        """每个检查项只含一个定位图形，禁止覆盖重复 ID。"""
        unique_ids([item.item_id for item in self.items], "result_geometry")
        return self


def require_result_table(body: object) -> dict:
    """校验通用表格边界，避免已绑定图片携带无界或不完整结果。"""
    if not isinstance(body, dict) or body.get("type") != "table-preview":
        raise InvalidRequestError("Results 需要 Value Preview 的 Table 输出")
    rows, columns = body.get("rows"), body.get("columns")
    if not isinstance(rows, list) or len(rows) > 8192 or any(not isinstance(row, dict) for row in rows):
        raise InvalidRequestError("Results 行格式无效")
    if not isinstance(columns, list) or len(columns) > 32 or any(
        not isinstance(c, dict) or not isinstance(c.get("key"), str) or not isinstance(c.get("label"), str)
        or not 1 <= len(c["key"]) <= 128 or not 1 <= len(c["label"]) <= 128 for c in columns
    ):
        raise InvalidRequestError("Results 列格式无效")
    if len({column["key"] for column in columns}) != len(columns):
        raise InvalidRequestError("Results 列不能重复")
    if any(column.get("format", "value") not in ("value", "unit", "result", "validity", "reason") for column in columns):
        raise InvalidRequestError("Results 列显示格式无效")
    return body


def bind_result_geometry(body: dict, raw_geometry: object, observation_id: object) -> None:
    """同次观测和唯一行 ID 都吻合时才附加几何，不依赖上一次结果。"""
    try:
        geometry = ResultGeometry.model_validate(raw_geometry)
        if geometry.observation_id != observation_id:
            raise ValueError("结果表和图形不属于同一次观察")
        ids = [row.get("item_id") for row in body["rows"]]
        if any(not isinstance(item, str) or not item for item in ids):
            raise ValueError("绑定图形的结果表需要唯一 item_id")
        unique_ids(ids, "rows")
    except ValueError as exc:
        raise InvalidRequestError(str(exc)) from exc
    body["result_geometry"] = geometry.model_dump(mode="json")
    body["observation_id"] = geometry.observation_id


def validate_result_image(body: object, request, image_payload: object) -> dict:
    """比对当前调用与原图引用，拒绝错帧或把原图坐标叠加到另一张处理图。"""
    table = require_result_table(body)
    try:
        geometry = ResultGeometry.model_validate(table.get("result_geometry"))
        run_id = request.execution_metadata.get("workflow_run_id") or request.execution_metadata.get("metrology_run_id")
        token = json.dumps(image_payload, sort_keys=True, ensure_ascii=False, allow_nan=False)
        if geometry.image.run_id != run_id or geometry.image.image_id != hashlib.sha256(token.encode()).hexdigest():
            raise ValueError("Results 与当前调用原图不匹配，请连接同一原图")
        if table.get("observation_id") != geometry.observation_id:
            raise ValueError("结果表和图形不属于同一次观察")
        ids = [row.get("item_id") for row in table["rows"]]
        if any(not isinstance(item, str) or not item for item in ids):
            raise ValueError("绑定图形的结果表需要唯一 item_id")
        unique_ids(ids, "rows")
    except (ValueError, TypeError) as exc:
        raise InvalidRequestError(str(exc)) from exc
    return table
