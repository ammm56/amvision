"""字段显示正文校验：限制组合图片携带的元数据，不引入图片或任意嵌套内容。"""

import json
import math

from backend.nodes.core_nodes.support.display_appearance import display_appearance, display_color
from backend.service.application.errors import InvalidRequestError


def validate_display_body(body: object) -> dict:
    """校验并返回字段正文；调用方只传引用，不复制图片或修改上游输出。"""
    def invalid() -> InvalidRequestError:
        """构造可定位的输入错误。"""
        return InvalidRequestError("Presentation 必须为有效的 Value Display Body")

    if not isinstance(body, dict) or body.get("type") != "value-display":
        raise invalid()
    if set(body) - {"type", "fields", "context", "title", "appearance"}:
        raise invalid()
    title = body.get("title", "")
    if not isinstance(title, str) or len(title) > 128:
        raise invalid()
    fields = body.get("fields")
    if not isinstance(fields, list) or not 1 <= len(fields) <= 32:
        raise invalid()
    for field in fields:
        if not isinstance(field, dict) or set(field) - {
            "label", "value", "format", "precision", "states", "label_color", "value_color"
        }:
            raise invalid()
        label, value = field.get("label"), field.get("value")
        if not isinstance(label, str) or len(label) > 128:
            raise invalid()
        if value is not None and type(value) not in (str, int, float, bool):
            raise invalid()
        if isinstance(value, str) and len(value) > 1024:
            raise invalid()
        if type(value) is int and abs(value) > 2**53 - 1:
            raise invalid()
        if type(value) is float and not math.isfinite(value):
            raise invalid()
        if field.get("format", "text") not in ("text", "integer", "number", "percent", "status"):
            raise invalid()
        precision = field.get("precision", 2)
        if type(precision) is not int or not 0 <= precision <= 6:
            raise invalid()
        states = field.get("states", {})
        if not isinstance(states, dict) or len(states) > 64:
            raise invalid()
        for key, color in states.items():
            if not isinstance(key, str) or not 1 <= len(key) <= 128 or not color:
                raise invalid()
            display_color(color, presets=True)
        for key in ("label_color", "value_color"):
            display_color(field.get(key))
    display_appearance(body.get("appearance"))
    try:
        size = len(json.dumps(body, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8"))
    except (TypeError, ValueError, RecursionError) as exc:
        raise invalid() from exc
    if size > 128 * 1024:
        raise InvalidRequestError("Value Display 超过 128 KiB")
    return body


def validate_presentation_context(expected: object, actual: object) -> None:
    """可选文件来源校验；不要求没有来源约束的通用显示提供文件标识。"""
    keys = ("generation", "sequence", "snapshot_revision")
    if not isinstance(expected, dict) or not isinstance(actual, dict) or any(
        expected.get(key) is None or type(expected[key]) is not type(actual.get(key))
        or expected[key] != actual[key] for key in keys
    ):
        raise InvalidRequestError("Presentation Context 与 Value Display 来源不一致")
