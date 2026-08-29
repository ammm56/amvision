"""工业视觉 payload 的有限数值矩阵校验工具。"""

from __future__ import annotations

from backend.service.application.errors import InvalidRequestError
from custom_nodes.opencv_nodes.shared.backend.runtime.validators import require_number


def require_matrix(
    raw_value: object,
    *,
    rows: int,
    columns: int,
    field_name: str,
) -> list[list[float]]:
    """读取固定尺寸的有限数值矩阵。"""

    if not isinstance(raw_value, list) or len(raw_value) != rows:
        raise InvalidRequestError(f"{field_name} 必须是 {rows}x{columns} 数值矩阵")
    normalized_rows: list[list[float]] = []
    for row_index, raw_row in enumerate(raw_value):
        if not isinstance(raw_row, list) or len(raw_row) != columns:
            raise InvalidRequestError(
                f"{field_name}[{row_index}] 必须是长度为 {columns} 的数组"
            )
        normalized_rows.append(
            [
                require_number(
                    raw_cell,
                    field_name=f"{field_name}[{row_index}][{column_index}]",
                )
                for column_index, raw_cell in enumerate(raw_row)
            ]
        )
    return normalized_rows


def require_vector(
    raw_value: object,
    *,
    length: int,
    field_name: str,
) -> list[float]:
    """读取固定长度的有限数值向量。"""

    if not isinstance(raw_value, list) or len(raw_value) != length:
        raise InvalidRequestError(f"{field_name} 必须是长度为 {length} 的数值数组")
    return [
        require_number(raw_cell, field_name=f"{field_name}[{cell_index}]")
        for cell_index, raw_cell in enumerate(raw_value)
    ]


__all__ = ["require_matrix", "require_vector"]
