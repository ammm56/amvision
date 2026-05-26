"""REST v1 列表接口分页辅助函数。"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TypeVar

from fastapi import Response


DEFAULT_LIST_LIMIT = 100
MAX_LIST_LIMIT = 500

ItemT = TypeVar("ItemT")


def paginate_sequence(
    items: Sequence[ItemT],
    *,
    response: Response,
    offset: int,
    limit: int,
) -> list[ItemT]:
    """按统一的 offset/limit 规则分页一个有序序列。

    参数：
    - items：待分页的有序序列。
    - response：当前响应对象，用于写入分页响应头。
    - offset：当前页起始偏移。
    - limit：当前页最大条数。

    返回：
    - list[ItemT]：当前页切片结果。
    """

    total_count = len(items)
    page_items = list(items[offset : offset + limit])
    next_offset = offset + len(page_items)
    has_more = next_offset < total_count

    response.headers["x-offset"] = str(offset)
    response.headers["x-limit"] = str(limit)
    response.headers["x-total-count"] = str(total_count)
    response.headers["x-has-more"] = "true" if has_more else "false"
    if has_more:
        response.headers["x-next-offset"] = str(next_offset)

    return page_items