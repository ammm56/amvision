"""逻辑比较 helper。"""

from __future__ import annotations

from backend.service.application.errors import InvalidRequestError


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
        _require_orderable_values(
            left_value=left_value,
            right_value=right_value,
            operator=normalized_operator,
        )
        return left_value > right_value
    if normalized_operator in {"ge", ">="}:
        _require_orderable_values(
            left_value=left_value,
            right_value=right_value,
            operator=normalized_operator,
        )
        return left_value >= right_value
    if normalized_operator in {"lt", "<"}:
        _require_orderable_values(
            left_value=left_value,
            right_value=right_value,
            operator=normalized_operator,
        )
        return left_value < right_value
    if normalized_operator in {"le", "<="}:
        _require_orderable_values(
            left_value=left_value,
            right_value=right_value,
            operator=normalized_operator,
        )
        return left_value <= right_value
    raise InvalidRequestError(
        "compare 节点不支持指定运算符",
        details={"operator": operator},
    )


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
