"""数据集、模型和运行时共用的有序类别名称约束。"""

from __future__ import annotations


def parse_category_names(value: object, *, field_name: str) -> tuple[str, ...]:
    """校验有序类别列表；禁止丢弃条目后改变模型输出索引。"""

    if not isinstance(value, list | tuple) or not value:
        raise ValueError(f"{field_name} 必须是非空类别列表")
    labels: list[str] = []
    for index, item in enumerate(value):
        if (
            not isinstance(item, str)
            or not item.strip()
            or item.splitlines() != [item]
        ):
            raise ValueError(f"{field_name}[{index}] 必须是非空单行类别名称")
        labels.append(item.strip())
    if len(set(labels)) != len(labels):
        raise ValueError(f"{field_name} 不能包含重复类别名称")
    return tuple(labels)
