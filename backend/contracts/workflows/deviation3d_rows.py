"""偏差逐点表固定布局；小端字段、状态与质量位定义独立于存储路径。"""

from enum import IntEnum


class DeviationStatus(IntEnum):
    """合法终态必须覆盖每个目标逻辑行，255 只用于计算中未写记录。"""

    COVERED = 0
    EXTENDED = 1
    INVALID_TARGET = 2
    INVALID_REFERENCE = 3
    OUTSIDE_SUPPORT = 4
    SUPPORT_QUALITY_FAILED = 5
    EXTENSION_LIMIT_EXCEEDED = 6


# 顺序也用于摘要计数和质量失败位，读写方不得自行重新编号。
STATUS_NAMES = (
    "covered",
    "extended",
    "invalid_target",
    "invalid_reference",
    "outside_support",
    "support_quality_failed",
    "extension_limit_exceeded",
)
QUALITY_METRICS = (
    "reference_count",
    "reference_covered",
    "reference_direction_cosine",
    "reference_nearest_distance",
    "reference_triangle_edge",
    "reference_max_residual",
    "reference_extension_distance",
)
MISSING_INDEX = 2**64 - 1

# (名称、小端 dtype、列数)；无几何时浮点列填 NaN，来源列填 MISSING_INDEX。
# NaN 仅允许出现在二进制无数据列，JSON 摘要仍禁止非有限数。
DEVIATION_COLUMNS = (
    ("source_index", "<u8", 1),
    ("deviation", "<f8", 1),
    ("status", "|u1", 1),
    ("failed_checks", "|u1", 1),
    ("covered", "|u1", 1),
    ("coverage_count", "<u8", 1),
    ("direction_cosine", "<f8", 1),
    ("nearest_distance", "<f8", 1),
    ("triangle_edge", "<f8", 1),
    ("max_residual", "<f8", 1),
    ("triangle", "<f8", 9),
    ("triangle_source_indices", "<u8", 3),
    ("extension_distance", "<f8", 1),
    ("nearest_support_point", "<f8", 3),
    ("projected_support_point", "<f8", 3),
    ("datum_point", "<f8", 3),
    ("nearest_source_index", "<u8", 1),
)
