"""已有基准平面到完整目标的偏差；支持、质量、数组与 Scope 沿用既有实现。"""

from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from uuid import uuid4

import numpy as np

from backend.contracts.workflows.deviation3d import DeviationCounts, DeviationSummary
from backend.contracts.workflows.deviation3d_rows import (
    DEVIATION_COLUMNS,
    MISSING_INDEX,
    STATUS_NAMES,
    DeviationStatus,
)
from backend.contracts.workflows.geometry3d_methods import parameter_digest
from backend.contracts.workflows.geometry3d_observations import PlaneFeature
from backend.contracts.workflows.point_cloud_runtime import CloudReference
from backend.contracts.workflows.measurement3d_parameters import (
    DirectionalEvaluation,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.exception_cleanup import (
    release_exception_frames,
)
from backend.service.application.workflows.point_cloud.arrays import OwnedCloudArrays
from custom_nodes.metrology3d_nodes.shared.deviation_statistics import (
    DeviationStatisticsAccumulator,
)
from custom_nodes.metrology3d_nodes.shared.deviation_quality import deviation_quality
from custom_nodes.metrology3d_nodes.shared.measurement_reference import (
    reference_coverage,
)
from custom_nodes.metrology3d_nodes.shared.measurement_support import (
    require_cloud,
    select_planes,
)
from custom_nodes.metrology3d_nodes.shared.prepared_plane_support import (
    prepare_plane_support,
)


@dataclass(frozen=True)
class DeviationResult:
    """内部完整计算结果；保留真实目标/基准，不能作为公开访问引用直接序列化。"""

    summary: DeviationSummary
    target: CloudReference
    reference: PlaneFeature
    owner: OwnedCloudArrays | None
    resource_key: tuple | None

    @contextmanager
    def borrow(self, runtime):
        """沿已有 Scope 和只读 owner 保护证据寿命，关闭后不能继续读取。"""
        if self.owner is None:
            raise InvalidRequestError("本次基准偏差未开启详细证据捕获")
        if not runtime.storage_scope.owns(self.owner):
            raise InvalidRequestError("基准偏差逐点证据已释放或不属于当前运行")
        require_cloud(
            runtime, self.target, self.summary.parameters, self.summary.observation_id
        )
        require_cloud(
            runtime,
            self.reference.support,
            self.summary.parameters,
            self.summary.observation_id,
        )
        with self.owner.borrow() as arrays:
            yield arrays


def deviation_row_bytes():
    """固定布局的实际数组字节数，不将索引/原生工作量混作输出大小。"""
    return sum(
        np.dtype(dtype).itemsize * width for _, dtype, width in DEVIATION_COLUMNS
    )


def _empty_rows(count, cancel):
    """准入之后分列分配，未写终态保留 255，避免零值被误认为成功。"""
    arrays = {}
    for name, dtype, width in DEVIATION_COLUMNS:
        cancel()
        fill = (
            np.nan
            if np.dtype(dtype).kind == "f"
            else MISSING_INDEX
            if name
            in {"source_index", "triangle_source_indices", "nearest_source_index"}
            else 255
            if name == "status"
            else 0
        )
        arrays[name] = np.full((count, width), fill, dtype=dtype)
    return arrays


def _store_scan(arrays, row, scan, failed):
    """显式捕获同次支持证据，不影响已经完成的质量判断。"""
    side = scan.support
    coverage = side.coverage
    arrays["covered"][row, 0] = coverage.covered
    arrays["coverage_count"][row, 0] = coverage.count
    for name in (
        "direction_cosine",
        "nearest_distance",
        "triangle_edge",
        "max_residual",
    ):
        value = getattr(coverage, name)
        if value is not None:
            arrays[name][row, 0] = value
    if coverage.triangle is not None:
        arrays["triangle"][row] = np.asarray(coverage.triangle).reshape(9)
        arrays["triangle_source_indices"][row] = coverage.source_indices
    extension = side.extension
    if extension is not None:
        if extension.distance is not None:
            arrays["extension_distance"][row, 0] = extension.distance
        if extension.source_index is not None:
            arrays["nearest_source_index"][row, 0] = extension.source_index
            for name, value in (
                ("nearest_support_point", extension.nearest_support_point),
                ("projected_support_point", extension.projected_support_point),
                ("datum_point", extension.datum_point),
            ):
                arrays[name][row] = value
    arrays["failed_checks"][row, 0] = failed


def measure_datum_deviation(
    runtime, cloud, groups, parameters, *, cancel, capture_details=False
):
    """默认只保留摘要；详细捕获独立于测量参数，不改变全目标计算与判定。"""
    arrays = reservation = owner = result = None
    key = ("datum-deviation", uuid4().hex)
    registered = False
    try:
        cancel()
        if type(capture_details) is not bool:
            raise InvalidRequestError("详细证据捕获必须显式使用布尔值")
        require_cloud(runtime, cloud, parameters, cloud.observation_id)
        reference = select_planes(
            runtime,
            groups,
            parameters,
            [parameters.reference_feature_id],
            observation_id=cloud.observation_id,
        )[0]
        if any(
            c.state == "ready"
            and (c.vertex_kind != "source" or c.sample_origin != "measured")
            for c in (cloud, reference.support)
        ):
            raise InvalidRequestError("基准偏差只接受有真实原始行号的实测目标和基准")
        # 来源在计算阶段即收口，不能等保存时才发现 A/B 无法追溯。
        if (
            cloud.state == "ready"
            and reference.support.state == "ready"
            and runtime.original_source(cloud)[0]
            != runtime.original_source(reference.support)[0]
        ):
            raise InvalidRequestError("基准偏差目标与基准不属于同一实际原云")
        count = cloud.point_count if cloud.state == "ready" else 0
        total_bytes = count * deviation_row_bytes() if capture_details else 0
        width = sum(
            np.dtype(f.dtype).itemsize * f.components for f in (cloud.fields or ())
        )
        rows = min(
            runtime.policy.chunk_rows,
            max(1, count),
            (runtime.policy.max_working_bytes - total_bytes) // (width * 2 + 512),
        )
        if rows < 1:
            raise InvalidRequestError("基准偏差完整证据和工作块超过工作预算")
        scratch_bytes = rows * (width * 2 + 512)
        if capture_details:
            reservation = runtime.budget.reserve(total_bytes)
            arrays = _empty_rows(count, cancel)
        reference_valid = reference.valid and reference.quality.usable
        preparation = (
            prepare_plane_support(
                runtime,
                reference,
                "reference",
                cancel=cancel,
                held_working_bytes=total_bytes + scratch_bytes,
            )
            if reference_valid and count
            else nullcontext(None)
        )
        with _scratch(runtime, scratch_bytes), preparation as prepared:
            if count:
                counts, statistics = _calculate_rows(
                    runtime,
                    cloud,
                    reference,
                    reference_valid,
                    parameters,
                    prepared,
                    arrays,
                    rows,
                    cancel,
                )
            else:
                statistics = None
                counts = DeviationCounts(**dict.fromkeys(STATUS_NAMES, 0))
        valid = count > 0 and reference_valid and counts.failed == 0
        summary = DeviationSummary(
            observation_id=cloud.observation_id,
            parameters=parameters,
            parameters_sha256=parameter_digest(parameters),
            target_state=cloud.state,
            target_reason=cloud.reason,
            target_count=count,
            source_point_count=runtime.source_point_count(cloud)
            if cloud.state == "ready"
            else 0,
            reference_valid=reference_valid,
            reference_reason=None
            if reference_valid
            else reference.reason or "reference_quality_failed",
            counts=counts,
            valid=valid,
            reason="target_unavailable"
            if cloud.state == "unavailable"
            else "empty_target"
            if not count
            else "reference_unavailable"
            if not reference_valid
            else "target_support_failed"
            if counts.failed
            else None,
            diagnostic=statistics,
            diagnostic_only=not valid,
        )
        cancel()
        if capture_details:
            owner = OwnedCloudArrays(arrays, reservation)
            arrays = None
            runtime.storage_scope.register(key, owner, lambda value: value.close())
            registered = True
        result = DeviationResult(
            summary, cloud, reference, owner, key if registered else None
        )
        cancel()
        return result
    except BaseException as error:
        arrays = result = None
        release_exception_frames(error)
        if registered:
            runtime.storage_scope.close_resource(key)
        elif owner is not None:
            owner.close()
        elif reservation is not None:
            reservation.close()
        raise


@contextmanager
def _scratch(runtime, size):
    """有界块工作量与输出/索引同时计费，退出后只归还本块预留。"""
    reservation = runtime.budget.reserve(size)
    try:
        yield
    finally:
        reservation.close()


def _calculate_rows(
    runtime,
    cloud,
    reference,
    reference_valid,
    parameters,
    prepared,
    arrays,
    rows,
    cancel,
):
    """每个原始目标行恰有一条终态；无效标记不隐式过滤或重编号。"""
    totals = dict.fromkeys(STATUS_NAMES, 0)
    accumulator = DeviationStatisticsAccumulator()
    with runtime.borrow(cloud) as view:
        for start in range(0, cloud.point_count, rows):
            cancel()
            stop = min(start + rows, cloud.point_count)
            positions, finite, values = _block_values(
                view, start, stop, reference, reference_valid
            )
            source = view.source_indices(start, stop).reshape(-1)
            if arrays is not None:
                arrays["source_index"][start:stop, 0] = source
                arrays["deviation"][start:stop, 0] = values
            for local, point in enumerate(positions):
                cancel()
                row = start + local
                if not finite[local]:
                    state = DeviationStatus.INVALID_TARGET
                elif not reference_valid:
                    state = DeviationStatus.INVALID_REFERENCE
                else:
                    settings = DirectionalEvaluation(
                        query_position=tuple(point),
                        direction=reference.geometry.normal,
                        support_radius=parameters.support_radius,
                        quality_policy=parameters.quality_policy,
                        reference_policy=parameters.reference_policy,
                    )
                    scan = reference_coverage(
                        runtime, reference, settings, cancel=cancel, prepared=prepared
                    )
                    state, failed = deviation_quality(
                        scan.support.coverage,
                        scan.support.extension,
                        parameters,
                        cloud.observation_id,
                    )
                    if arrays is not None:
                        _store_scan(arrays, row, scan, failed)
                totals[STATUS_NAMES[int(state)]] += 1
                if arrays is not None:
                    arrays["status"][row, 0] = state
            accumulator.update(values, source, start=start)
            positions = finite = values = source = point = None

        def chunks():
            """只重读有界坐标块做数值求和，不重复支持搜索、质量判断或拟合。"""
            for start in range(0, cloud.point_count, rows):
                cancel()
                _, _, values = _block_values(
                    view,
                    start,
                    min(start + rows, cloud.point_count),
                    reference,
                    reference_valid,
                )
                yield values

        statistics = accumulator.finish(chunks, cancel=cancel)
    return DeviationCounts(**totals), statistics


def _block_values(view, start, stop, reference, reference_valid):
    """同一块数值定义用于首遍与稳定求和；无效标记保留 NaN，不隐式删行。"""
    block = view.chunk(start, stop)
    positions = np.asarray(block["positions"], dtype=np.float64)
    finite = np.isfinite(positions).all(axis=1)
    if "validity" in block:
        finite &= block["validity"][:, 0].astype(bool)
    values = np.full(stop - start, np.nan, dtype=np.float64)
    if reference_valid and finite.any():
        with np.errstate(over="raise", invalid="raise"):
            values[finite] = (
                np.einsum(
                    "ij,j->i",
                    positions[finite],
                    reference.geometry.normal,
                    optimize=False,
                )
                + reference.geometry.offset
            )
        if not np.isfinite(values[finite]).all():
            raise InvalidRequestError("基准偏差超出有限数值范围")
    return positions, finite, values
