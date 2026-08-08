"""VOC XML 坐标声明解析。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from xml.etree import ElementTree

from backend.service.domain.datasets.coordinates import (
    CoordinateConvention,
    PASCAL_VOC_ONE_BASED_INCLUSIVE,
    ZERO_BASED_EXCLUSIVE,
)


VOC_ZERO_BASED_ALIASES = frozenset(
    {
        "zero-based-exclusive",
        "0-based-exclusive",
        "zero_based_exclusive",
    }
)
VOC_PASCAL_ALIASES = frozenset(
    {
        "pascal-voc-1-based-inclusive",
        "1-based-inclusive",
        "one-based-inclusive",
        "official-pascal-voc",
    }
)


@dataclass(frozen=True)
class VocCoordinateDeclarationError(ValueError):
    """表示 VOC XML 坐标声明未知或互相冲突。"""

    reason: Literal["conflict", "unknown"]
    values: tuple[str, ...]


def resolve_voc_xml_coordinate_convention(
    xml_root: ElementTree.Element,
) -> CoordinateConvention:
    """解析 VOC XML 坐标声明；无声明时使用项目默认约定。"""

    raw_values = (
        xml_root.attrib.get("coordinate_convention"),
        xml_root.findtext("coordinate_convention"),
        xml_root.findtext("coordinateConvention"),
        xml_root.findtext("source/coordinate_convention"),
        xml_root.findtext("source/coordinateConvention"),
    )
    normalized_values = tuple(
        sorted(
            {
                value.strip().lower()
                for value in raw_values
                if isinstance(value, str) and value.strip()
            }
        )
    )
    if len(normalized_values) > 1:
        raise VocCoordinateDeclarationError("conflict", normalized_values)
    if not normalized_values:
        return ZERO_BASED_EXCLUSIVE
    value = normalized_values[0]
    if value in VOC_ZERO_BASED_ALIASES:
        return ZERO_BASED_EXCLUSIVE
    if value in VOC_PASCAL_ALIASES:
        return PASCAL_VOC_ONE_BASED_INCLUSIVE
    raise VocCoordinateDeclarationError("unknown", normalized_values)
