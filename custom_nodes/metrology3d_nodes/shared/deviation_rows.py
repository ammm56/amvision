"""逐点偏差二进制表与摘要的一致性检查；资产绑定另由既有事务层负责。"""

import numpy as np
from pydantic import ValidationError

from backend.contracts.workflows.deviation3d_rows import (
    DEVIATION_COLUMNS,
    MISSING_INDEX,
    STATUS_NAMES,
    DeviationStatus as Status,
)
from backend.service.application.errors import InvalidRequestError
from backend.contracts.workflows.measurement3d_directional import CoverageEvidence
from backend.contracts.workflows.measurement3d_parameters import ExtendedReference
from backend.contracts.workflows.measurement3d_reference import ReferenceExtension
from custom_nodes.metrology3d_nodes.shared.deviation_quality import deviation_quality
from custom_nodes.metrology3d_nodes.shared.deviation_statistics import (
    deviation_statistics,
)


def validate_deviation_rows(arrays, summary, *, chunk_rows, cancel):
    """分块拒绝截断、错类型、越界来源、矛盾终态和与完整表不符的摘要。"""
    if type(chunk_rows) is not int or chunk_rows < 1:
        raise InvalidRequestError("偏差证据校验块大小必须为正整数")
    if set(arrays) != {name for name, _, _ in DEVIATION_COLUMNS}:
        raise InvalidRequestError("偏差证据字段缺失或多余")
    for name, dtype, width in DEVIATION_COLUMNS:
        array = arrays[name]
        if (
            not isinstance(array, np.ndarray)
            or array.dtype != np.dtype(dtype)
            or array.shape != (summary.target_count, width)
        ):
            raise InvalidRequestError("偏差证据字段类型或行数不一致")
    totals = np.zeros(len(STATUS_NAMES), dtype=np.int64)
    for start in range(0, summary.target_count, chunk_rows):
        cancel()
        block = {
            key: value[start : start + chunk_rows] for key, value in arrays.items()
        }
        status = block["status"][:, 0]
        _require(np.all(status < len(STATUS_NAMES)))
        totals += np.bincount(status, minlength=len(STATUS_NAMES))
        _require(np.all(block["source_index"] < summary.source_point_count))
        for name, dtype, _ in DEVIATION_COLUMNS:
            if np.dtype(dtype).kind == "f":
                _require(not np.isinf(block[name]).any())
        unavailable = np.isin(status, [Status.INVALID_TARGET, Status.INVALID_REFERENCE])
        _require(np.array_equal(np.isfinite(block["deviation"][:, 0]), ~unavailable))
        _require(np.all(block["covered"] <= 1) and np.all(block["failed_checks"] < 128))
        covered = block["covered"][:, 0] == 1
        for name in ("triangle", "triangle_edge"):
            _require(np.all(np.isfinite(block[name][covered])))
            _require(np.all(np.isnan(block[name][~covered])))
        triangles = block["triangle_source_indices"]
        _require(np.all(triangles[~covered] == MISSING_INDEX))
        _require(np.all(triangles[covered] < summary.source_point_count))
        _require(np.all(block["coverage_count"][covered] >= 3))
        if covered.any():
            rows = triangles[covered]
            _require(
                np.all(
                    (rows[:, 0] != rows[:, 1])
                    & (rows[:, 0] != rows[:, 2])
                    & (rows[:, 1] != rows[:, 2])
                )
            )
        has_nearest = block["nearest_source_index"][:, 0] != MISSING_INDEX
        _require(
            np.all(
                block["nearest_source_index"][has_nearest] < summary.source_point_count
            )
        )
        for name in ("nearest_support_point", "projected_support_point", "datum_point"):
            _require(np.all(np.isfinite(block[name][has_nearest])))
            _require(np.all(np.isnan(block[name][~has_nearest])))
        _require(np.all(~has_nearest | np.isfinite(block["extension_distance"][:, 0])))
        valid = np.isin(status, [Status.COVERED, Status.EXTENDED])
        _require(np.all(block["failed_checks"][valid] == 0))
        _require(np.all(covered[status == Status.COVERED]))
        _require(np.all(~covered[status == Status.EXTENDED]))
        _require(np.all(has_nearest[status == Status.EXTENDED]))
        _require(np.all(has_nearest[status == Status.EXTENSION_LIMIT_EXCEEDED]))
        _require(
            np.all(block["failed_checks"][status == Status.SUPPORT_QUALITY_FAILED] != 0)
        )
        for name in ("failed_checks", "covered", "coverage_count"):
            _require(np.all(block[name][unavailable] == 0))
        for name, dtype, _ in DEVIATION_COLUMNS:
            if np.dtype(dtype).kind == "f":
                _require(np.all(np.isnan(block[name][unavailable])))
        _require(np.all(~has_nearest[unavailable]))
        for row in np.flatnonzero(~unavailable):
            cancel()
            _check_row(block, int(row), summary)
    _require(
        all(
            int(totals[i]) == getattr(summary.counts, name)
            for i, name in enumerate(STATUS_NAMES)
        )
    )
    _require(
        deviation_statistics(arrays, chunk_rows=chunk_rows, cancel=cancel)
        == summary.diagnostic
    )
    cancel()


def _check_row(block, row, summary):
    """重建既有支持证据并复算原质量，不信任存储的通过位。"""

    def scalar(name):
        value = float(block[name][row, 0])
        return None if np.isnan(value) else value

    covered = bool(block["covered"][row, 0])
    nearest = int(block["nearest_source_index"][row, 0])
    try:
        coverage = CoverageEvidence(
            count=int(block["coverage_count"][row, 0]),
            covered=covered,
            direction_cosine=scalar("direction_cosine"),
            nearest_distance=scalar("nearest_distance"),
            triangle_edge=scalar("triangle_edge"),
            max_residual=scalar("max_residual"),
            triangle=block["triangle"][row].reshape(3, 3).tolist() if covered else None,
            source_indices=block["triangle_source_indices"][row].tolist()
            if covered
            else None,
        )
        policy = summary.parameters.reference_policy
        extension = None
        if isinstance(policy, ExtendedReference):
            distance = scalar("extension_distance")
            state = (
                "covered"
                if covered
                else "unavailable"
                if nearest == MISSING_INDEX
                else "used"
                if distance is not None and distance <= policy.max_extension_distance
                else "limit-exceeded"
            )
            extension = ReferenceExtension(
                state=state,
                used_extension=state == "used",
                distance=distance,
                max_distance=policy.max_extension_distance,
                source_index=None if nearest == MISSING_INDEX else nearest,
                nearest_support_point=None
                if nearest == MISSING_INDEX
                else block["nearest_support_point"][row].tolist(),
                projected_support_point=None
                if nearest == MISSING_INDEX
                else block["projected_support_point"][row].tolist(),
                datum_point=None
                if nearest == MISSING_INDEX
                else block["datum_point"][row].tolist(),
                endpoint_origin={"covered": "supported", "used": "datum-extension"}.get(
                    state
                ),
            )
        else:
            _require(nearest == MISSING_INDEX and scalar("extension_distance") is None)
        state, failed = deviation_quality(
            coverage, extension, summary.parameters, summary.observation_id
        )
    except ValidationError as error:
        raise InvalidRequestError("偏差证据中的覆盖或延伸信息不合法") from error
    _require(
        state == block["status"][row, 0] and failed == block["failed_checks"][row, 0]
    )


def _require(condition):
    """二进制不一致统一归为输入错误，不能显示成功摘要。"""
    if not condition:
        raise InvalidRequestError("偏差证据逐点数据与状态或摘要不一致")
