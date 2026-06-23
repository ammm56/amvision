"""点分路径取值 helper。"""

from __future__ import annotations

from backend.nodes.core_nodes.support.logic.json_values import normalize_json_safe_value
from backend.service.application.errors import InvalidRequestError


def extract_value_by_path(*, root: object, path: str) -> object:
    """按点分路径从对象中提取子字段。

    参数：
    - root：提取根对象。
    - path：点分路径，数组下标使用纯数字段。

    返回：
    - object：提取到的值。
    """

    found, value = _walk_value_by_path(root=root, path=path, missing_as_error=True)
    if found:
        return normalize_json_safe_value(value)
    raise InvalidRequestError("字段提取路径不存在", details={"path": path.strip()})


def try_extract_value_by_path(*, root: object, path: str) -> tuple[bool, object | None]:
    """按点分路径尝试从对象中提取子字段。

    参数：
    - root：提取根对象。
    - path：点分路径，数组下标使用纯数字段。

    返回：
    - tuple[bool, object | None]：字段是否存在，以及提取到的值。
    """

    found, value = _walk_value_by_path(root=root, path=path, missing_as_error=False)
    if not found:
        return False, None
    return True, normalize_json_safe_value(value)


def _walk_value_by_path(
    *,
    root: object,
    path: str,
    missing_as_error: bool,
) -> tuple[bool, object | None]:
    """按点分路径遍历对象。"""

    normalized_path = path.strip()
    if not normalized_path:
        return True, normalize_json_safe_value(root)
    current_value = root
    for raw_segment in normalized_path.split("."):
        segment = raw_segment.strip()
        if not segment:
            raise InvalidRequestError("字段提取路径不能包含空段")
        if isinstance(current_value, dict):
            if segment not in current_value:
                if not missing_as_error:
                    return False, None
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
                if not missing_as_error:
                    return False, None
                raise InvalidRequestError(
                    "字段提取列表下标越界",
                    details={
                        "segment": segment,
                        "path": normalized_path,
                        "size": len(current_value),
                    },
                )
            current_value = current_value[index]
            continue
        if not missing_as_error:
            return False, None
        raise InvalidRequestError(
            "字段提取路径无法继续深入",
            details={
                "segment": segment,
                "path": normalized_path,
                "value_type": current_value.__class__.__name__,
            },
        )
    return True, current_value
