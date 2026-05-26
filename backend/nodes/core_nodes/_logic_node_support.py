"""逻辑与编排类 core nodes 共享 helper。"""

from __future__ import annotations

from backend.service.application.errors import InvalidRequestError


def build_value_payload(value: object) -> dict[str, object]:
    """把任意 JSON 安全值包装成 value payload。

    参数：
    - value：要包装的值。

    返回：
    - dict[str, object]：包装后的 value payload。
    """

    return {"value": _normalize_json_safe_value(value)}


def require_value_payload(payload: object, *, field_name: str = "value") -> dict[str, object]:
    """校验并规范化 value payload。

    参数：
    - payload：待校验的 payload。
    - field_name：错误消息中使用的字段名称。

    返回：
    - dict[str, object]：规范化后的 value payload。
    """

    if not isinstance(payload, dict) or "value" not in payload:
        raise InvalidRequestError(f"{field_name} payload 必须是包含 value 的对象")
    return {"value": _normalize_json_safe_value(payload.get("value"))}


def build_boolean_payload(value: bool) -> dict[str, object]:
    """把布尔值包装成 boolean payload。"""

    if not isinstance(value, bool):
        raise InvalidRequestError("boolean payload 要求 value 必须是布尔值")
    return {"value": value}


def require_boolean_payload(payload: object, *, field_name: str = "condition") -> dict[str, object]:
    """校验并规范化 boolean payload。"""

    if not isinstance(payload, dict) or not isinstance(payload.get("value"), bool):
        raise InvalidRequestError(f"{field_name} payload 必须是包含布尔 value 的对象")
    return {"value": bool(payload["value"])}


def compare_values(*, left_value: object, right_value: object, operator: str) -> bool:
    """执行最小比较语义。

    参数：
    - left_value：左值。
    - right_value：右值。
    - operator：比较运算符。

    返回：
    - bool：比较结果。
    """

    normalized_operator = operator.strip().lower()
    if normalized_operator in {"eq", "="}:
        return left_value == right_value
    if normalized_operator in {"ne", "!="}:
        return left_value != right_value
    if normalized_operator in {"gt", ">"}:
        _require_orderable_values(left_value=left_value, right_value=right_value, operator=normalized_operator)
        return left_value > right_value
    if normalized_operator in {"ge", ">="}:
        _require_orderable_values(left_value=left_value, right_value=right_value, operator=normalized_operator)
        return left_value >= right_value
    if normalized_operator in {"lt", "<"}:
        _require_orderable_values(left_value=left_value, right_value=right_value, operator=normalized_operator)
        return left_value < right_value
    if normalized_operator in {"le", "<="}:
        _require_orderable_values(left_value=left_value, right_value=right_value, operator=normalized_operator)
        return left_value <= right_value
    raise InvalidRequestError(
        "compare 节点不支持指定运算符",
        details={"operator": operator},
    )


def extract_value_by_path(*, root: object, path: str) -> object:
    """按点分路径从对象中提取子字段。

    参数：
    - root：提取根对象。
    - path：点分路径，数组下标使用纯数字段。

    返回：
    - object：提取到的值。
    """

    normalized_path = path.strip()
    if not normalized_path:
        return _normalize_json_safe_value(root)
    current_value = root
    for raw_segment in normalized_path.split("."):
        segment = raw_segment.strip()
        if not segment:
            raise InvalidRequestError("字段提取路径不能包含空段")
        if isinstance(current_value, dict):
            if segment not in current_value:
                raise InvalidRequestError(
                    "字段提取路径不存在",
                    details={"missing_segment": segment, "path": normalized_path},
                )
            current_value = current_value[segment]
            continue
        if isinstance(current_value, list):
            if not segment.isdigit():
                raise InvalidRequestError(
                    "列表路径段必须是非负整数",
                    details={"segment": segment, "path": normalized_path},
                )
            index = int(segment)
            if index >= len(current_value):
                raise InvalidRequestError(
                    "字段提取列表下标越界",
                    details={"segment": segment, "path": normalized_path, "size": len(current_value)},
                )
            current_value = current_value[index]
            continue
        raise InvalidRequestError(
            "字段提取路径无法继续深入",
            details={"segment": segment, "path": normalized_path, "value_type": current_value.__class__.__name__},
        )
    return _normalize_json_safe_value(current_value)


def try_extract_value_by_path(*, root: object, path: str) -> tuple[bool, object | None]:
    """按点分路径尝试从对象中提取子字段。

    参数：
    - root：提取根对象。
    - path：点分路径，数组下标使用纯数字段。

    返回：
    - tuple[bool, object | None]：字段是否存在，以及提取到的值。
    """

    normalized_path = path.strip()
    if not normalized_path:
        return True, _normalize_json_safe_value(root)
    current_value = root
    for raw_segment in normalized_path.split("."):
        segment = raw_segment.strip()
        if not segment:
            raise InvalidRequestError("字段提取路径不能包含空段")
        if isinstance(current_value, dict):
            if segment not in current_value:
                return False, None
            current_value = current_value[segment]
            continue
        if isinstance(current_value, list):
            if not segment.isdigit():
                raise InvalidRequestError(
                    "列表路径段必须是非负整数",
                    details={"segment": segment, "path": normalized_path},
                )
            index = int(segment)
            if index >= len(current_value):
                return False, None
            current_value = current_value[index]
            continue
        return False, None
    return True, _normalize_json_safe_value(current_value)


def _require_orderable_values(*, left_value: object, right_value: object, operator: str) -> None:
    """校验左右值适合做有序比较。"""

    if isinstance(left_value, bool) or isinstance(right_value, bool):
        raise InvalidRequestError(
            "compare 节点不支持对布尔值执行有序比较",
            details={"operator": operator},
        )
    if isinstance(left_value, (int, float)) and isinstance(right_value, (int, float)):
        return
    if isinstance(left_value, str) and isinstance(right_value, str):
        return
    raise InvalidRequestError(
        "compare 节点的有序比较只支持同类数字或字符串",
        details={
            "operator": operator,
            "left_type": left_value.__class__.__name__,
            "right_type": right_value.__class__.__name__,
        },
    )


def _normalize_json_safe_value(value: object) -> object:
    """把值递归规范化为 JSON 安全结构。"""

    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, tuple):
        return [_normalize_json_safe_value(item) for item in value]
    if isinstance(value, list):
        return [_normalize_json_safe_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _normalize_json_safe_value(item) for key, item in value.items()}
    raise InvalidRequestError(
        "当前逻辑节点只支持 JSON 安全值",
        details={"value_type": value.__class__.__name__},
    )