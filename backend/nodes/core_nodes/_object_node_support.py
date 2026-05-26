"""对象类 core nodes 共享 helper。"""

from __future__ import annotations

from backend.nodes.core_nodes._logic_node_support import build_value_payload, require_value_payload
from backend.service.application.errors import InvalidRequestError


def require_object_value(
    payload: object,
    *,
    field_name: str,
    node_id: str,
) -> dict[str, object]:
    """校验输入 payload 中的值必须为对象。

    参数：
    - payload：待校验的 value payload。
    - field_name：错误消息中使用的字段名。
    - node_id：当前节点实例 id。

    返回：
    - dict[str, object]：复制后的对象值。
    """

    object_value = require_value_payload(payload, field_name=field_name)["value"]
    if not isinstance(object_value, dict):
        raise InvalidRequestError(
            f"{field_name} payload 中的 value 必须是对象",
            details={"node_id": node_id, "field_name": field_name},
        )
    return dict(object_value)


def read_object_paths(raw_value: object, *, field_name: str) -> tuple[str, ...]:
    """读取并校验对象字段路径数组。

    参数：
    - raw_value：待校验的原始参数值。
    - field_name：错误消息中使用的字段名。

    返回：
    - tuple[str, ...]：规范化后的字段路径列表。
    """

    if not isinstance(raw_value, list) or not raw_value:
        raise InvalidRequestError(f"{field_name} 必须是非空字符串数组")
    normalized_paths: list[str] = []
    for path_index, raw_path in enumerate(raw_value, start=1):
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise InvalidRequestError(
                f"{field_name} 的每一项都必须是非空字符串",
                details={"field_name": field_name, "path_index": path_index},
            )
        normalized_path = raw_path.strip()
        _validate_object_path(normalized_path, field_name=field_name)
        if normalized_path in normalized_paths:
            raise InvalidRequestError(
                f"{field_name} 不能包含重复字段路径",
                details={"field_name": field_name, "path": normalized_path},
            )
        normalized_paths.append(normalized_path)
    return tuple(normalized_paths)


def set_object_path(target: dict[str, object], *, path: str, value: object) -> None:
    """把值写入对象的指定字段路径。

    参数：
    - target：待更新的目标对象。
    - path：点分字段路径。
    - value：待写入的 JSON 安全值。
    """

    segments = _split_object_path(path)
    current_object = target
    for segment in segments[:-1]:
        next_value = current_object.get(segment)
        if next_value is None:
            next_value = {}
            current_object[segment] = next_value
        if not isinstance(next_value, dict):
            raise InvalidRequestError(
                "对象字段路径的中间段必须是对象",
                details={"path": path, "segment": segment},
            )
        current_object = next_value
    current_object[segments[-1]] = build_value_payload(value)["value"]


def try_read_object_path(source: dict[str, object], *, path: str) -> tuple[bool, object | None]:
    """尝试从对象读取指定字段路径。

    参数：
    - source：待读取的源对象。
    - path：点分字段路径。

    返回：
    - tuple[bool, object | None]：字段是否存在，以及读取到的值。
    """

    current_value: object = source
    for segment in _split_object_path(path):
        if not isinstance(current_value, dict) or segment not in current_value:
            return False, None
        current_value = current_value[segment]
    return True, build_value_payload(current_value)["value"]


def remove_object_path(source: dict[str, object], *, path: str) -> bool:
    """从对象中移除指定字段路径，并清理空对象父节点。

    参数：
    - source：待更新的源对象。
    - path：点分字段路径。

    返回：
    - bool：是否成功移除了目标字段。
    """

    segments = _split_object_path(path)
    return _remove_object_path_recursive(source, segments)


def copy_object_value(value: dict[str, object]) -> dict[str, object]:
    """复制对象值，保证后续修改不会影响原对象。"""

    copied_value = build_value_payload(value)["value"]
    if not isinstance(copied_value, dict):
        raise InvalidRequestError("copy_object_value 只支持对象值")
    return dict(copied_value)


def _remove_object_path_recursive(current_object: dict[str, object], segments: tuple[str, ...]) -> bool:
    """递归移除对象字段路径。"""

    current_segment = segments[0]
    if current_segment not in current_object:
        return False
    if len(segments) == 1:
        current_object.pop(current_segment, None)
        return True

    next_value = current_object.get(current_segment)
    if not isinstance(next_value, dict):
        return False
    removed = _remove_object_path_recursive(next_value, segments[1:])
    if removed and not next_value:
        current_object.pop(current_segment, None)
    return removed


def _validate_object_path(path: str, *, field_name: str) -> None:
    """校验对象字段路径格式。"""

    segments = path.split(".")
    if any(not segment.strip() for segment in segments):
        raise InvalidRequestError(
            f"{field_name} 中的字段路径不能包含空段",
            details={"field_name": field_name, "path": path},
        )


def _split_object_path(path: str) -> tuple[str, ...]:
    """把对象字段路径拆分为段列表。"""

    return tuple(segment.strip() for segment in path.split("."))