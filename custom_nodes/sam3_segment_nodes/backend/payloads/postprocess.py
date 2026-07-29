"""SAM3 后处理参数的规范化定义。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from backend.service.application.errors import InvalidRequestError


@dataclass(frozen=True)
class Sam3PostprocessOptions:
    """描述一次 SAM3 mask 后处理参数。"""

    mask_threshold: float
    stability_offset: float
    min_component_area: int | None
    polygon_simplify_ratio: float


def resolve_sam3_postprocess_options(
    parameters: Mapping[str, object],
) -> Sam3PostprocessOptions:
    """读取并校验节点后处理参数。"""

    return Sam3PostprocessOptions(
        mask_threshold=_read_float(
            parameters.get("mask_threshold"),
            field_name="mask_threshold",
            default=0.0,
        ),
        stability_offset=_read_float(
            parameters.get("stability_offset"),
            field_name="stability_offset",
            default=0.05,
            minimum=0.0,
        ),
        min_component_area=_read_optional_int(
            parameters.get("min_component_area"),
            field_name="min_component_area",
            minimum=0,
        ),
        polygon_simplify_ratio=_read_float(
            parameters.get("polygon_simplify_ratio"),
            field_name="polygon_simplify_ratio",
            default=0.002,
            minimum=0.0,
            maximum=0.1,
        ),
    )


def _read_float(
    value: object,
    *,
    field_name: str,
    default: float,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    """读取浮点参数并校验范围。"""

    if value is None or value == "":
        normalized_value = float(default)
    else:
        try:
            normalized_value = float(value)
        except (TypeError, ValueError) as exc:
            raise InvalidRequestError(f"{field_name} 必须是数字") from exc
    if minimum is not None and normalized_value < minimum:
        raise InvalidRequestError(
            f"{field_name} 不能小于 {minimum}",
            details={field_name: normalized_value},
        )
    if maximum is not None and normalized_value > maximum:
        raise InvalidRequestError(
            f"{field_name} 不能大于 {maximum}",
            details={field_name: normalized_value},
        )
    return normalized_value


def _read_optional_int(
    value: object,
    *,
    field_name: str,
    minimum: int,
) -> int | None:
    """读取可选整数参数。"""

    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise InvalidRequestError(f"{field_name} 必须是整数")
    try:
        normalized_value = int(value)
    except (TypeError, ValueError) as exc:
        raise InvalidRequestError(f"{field_name} 必须是整数") from exc
    if normalized_value < minimum:
        raise InvalidRequestError(
            f"{field_name} 不能小于 {minimum}",
            details={field_name: normalized_value},
        )
    return normalized_value


__all__ = ["Sam3PostprocessOptions", "resolve_sam3_postprocess_options"]
