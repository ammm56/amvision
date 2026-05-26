"""TriggerSource dotted path 读取工具。"""

from __future__ import annotations


class MissingPathValue:
    """表示 dotted path 未匹配到任何值的哨兵对象。"""


MISSING_PATH_VALUE = MissingPathValue()


def read_dotted_path(source: object, dotted_path: str) -> object:
    """从 dict 或 list 结构中读取 dotted path 指向的值。

    参数：
    - source：要读取的结构化对象。
    - dotted_path：点分路径，例如 payload.image 或 metadata.trace_id。

    返回：
    - object：读取到的值；路径缺失时返回 MISSING_PATH_VALUE。
    """

    normalized_path = dotted_path.strip()
    if not normalized_path:
        return MISSING_PATH_VALUE

    current_value = source
    for segment in normalized_path.split("."):
        if not segment:
            return MISSING_PATH_VALUE
        if isinstance(current_value, dict):
            if segment not in current_value:
                return MISSING_PATH_VALUE
            current_value = current_value[segment]
            continue
        if isinstance(current_value, list) and segment.isdigit():
            item_index = int(segment)
            if item_index >= len(current_value):
                return MISSING_PATH_VALUE
            current_value = current_value[item_index]
            continue
        return MISSING_PATH_VALUE
    return current_value
