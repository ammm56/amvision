"""同一 Scope 内准备有限平面支持；索引只找候选，最终仍用原精度规则。"""

from contextlib import contextmanager
from threading import RLock
from uuid import uuid4

import numpy as np
from scipy.spatial import cKDTree

from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.exception_cleanup import (
    release_exception_frames,
)
from custom_nodes.metrology3d_nodes.shared.fit_plane import _positions, _rows
from custom_nodes.metrology3d_nodes.shared.measurement_support import (
    NearestSupport,
    PlaneCoverageScan,
    _tangent,
    coverage_query,
    support_snapshot,
    tangent_coordinates,
    normal_residuals,
    triangulated_coverage,
)


class _SupportIndex:
    """完整支持的只读坐标、原行号及切向索引；预算由外层统一持有。"""

    def __init__(self, runtime, cloud, basis, *, held_bytes, cancel):
        """按现有块读取全部点；不以采样或拟面内点替代原邻域。"""
        self.positions = np.empty((cloud.point_count, 3), dtype=np.float64)
        self.indices = np.empty(cloud.point_count, dtype=np.uint64)
        rows = _rows(runtime, cloud, held_bytes=held_bytes)
        with runtime.borrow(cloud) as view:
            for start in range(0, cloud.point_count, rows):
                cancel()
                stop = min(start + rows, cloud.point_count)
                self.positions[start:stop] = _positions(view, start, stop)
                self.indices[start:stop] = view.source_indices(start, stop).reshape(-1)
        self.origin = self.positions[0].copy()
        self.scale = max(1.0, float(np.abs(self.positions).max()))
        self.basis = basis
        with np.errstate(over="raise", invalid="raise"):
            projected = (self.positions - self.origin) @ basis
        cancel()
        self.tree = cKDTree(projected, copy_data=False)
        self.positions.flags.writeable = False
        self.indices.flags.writeable = False
        cancel()

    def query(self, point, radius):
        """扩大的范围仅抵消索引投影舍入；精确半径比较在候选上重新执行。"""
        with np.errstate(over="raise", invalid="raise"):
            query = (point - self.origin) @ self.basis
            guard = (
                64
                * np.finfo(np.float64).eps
                * (self.scale + float(np.abs(point).max()) + 1)
            )
            expanded = np.nextafter(radius + guard, np.inf)
        return query, expanded


class PreparedPlaneSupport:
    """一次准备、多次检查；不得跨运行、特征或角色使用，关闭即不可查询。"""

    def __init__(self, runtime, feature, role, held_working_bytes=0):
        """记录当前身份；实际分配由 prepare_plane_support 管理异常回收。"""
        self.runtime = runtime
        self.feature = feature.model_copy(deep=True)
        self.role = role
        self.key = ("prepared-plane-support", uuid4().hex)
        self.index = self.raw = self.support = self.reservation = None
        self.held_bytes = 0
        self.held_working_bytes = held_working_bytes
        self.closed = False
        self._lock = RLock()
        self._active = False

    def close(self):
        """先解除原生索引和数组，再释放预算；可重复关闭。"""
        with self._lock:
            if self._active:
                raise RuntimeError("平面支持仍有活跃查询，禁止提前释放")
            self.index = self.raw = None
            if self.reservation is not None:
                self.reservation.close()
                self.reservation = None
            self.closed = True

    @contextmanager
    def _borrow(self):
        """遵循现有数组借用关闭规则；同一批处理不排队接受并发查询。"""
        with self._lock:
            if self.closed or self._active:
                raise InvalidRequestError("平面支持已失效或仍有活跃查询")
            self._active = True
        try:
            yield
        finally:
            with self._lock:
                self._active = False

    @contextmanager
    def _candidates(self, index, point, radius, *, cancel):
        """先数邻域、核对并预留工作量，再创建完整候选列表。"""
        cancel()
        query, expanded = index.query(point, radius)
        count = int(index.tree.query_ball_point(query, expanded, return_length=True))
        # 包括 Python 邻接列表、排序、坐标 gather、unique 和局部 Qhull。
        size = max(1024, count * 1024)
        if (
            size
            > self.runtime.policy.max_working_bytes
            - self.held_bytes
            - self.held_working_bytes
        ):
            raise InvalidRequestError("平面支持候选超过工作预算")
        reservation = self.runtime.budget.reserve(size)
        selected = positions = distances = None
        try:
            cancel()
            selected = np.asarray(
                index.tree.query_ball_point(query, expanded, return_sorted=True),
                dtype=np.int64,
            )
            positions = index.positions[selected]
            local = tangent_coordinates(positions, point, index.basis)
            distances = np.hypot(local[:, 0], local[:, 1])
            yield selected, positions, distances
            cancel()
        except BaseException as error:
            release_exception_frames(error)
            raise
        finally:
            selected = positions = distances = local = None
            reservation.close()

    def coverage(self, runtime, feature, settings, role, *, cancel, capture_nearest):
        """与逐查询全扫描保持相同邻域、排序、三角形、残差和最近点平局规则。"""
        if (
            self.closed
            or runtime is not self.runtime
            or feature != self.feature
            or role != self.role
            or not runtime.storage_scope.owns(self)
        ):
            raise InvalidRequestError("已准备平面支持失效或身份不一致")
        with self._borrow():
            if feature.support.state == "ready":
                with runtime.borrow(feature.support):
                    return self._coverage(
                        feature,
                        settings,
                        cancel=cancel,
                        capture_nearest=capture_nearest,
                    )
            return self._coverage(
                feature, settings, cancel=cancel, capture_nearest=capture_nearest
            )

    def _coverage(self, feature, settings, *, cancel, capture_nearest):
        """整个查询持有当前索引和源引用的借用，关闭失败交由原 Scope 上报。"""
        cancel()
        if not feature.valid:
            return PlaneCoverageScan(self.support, None)
        point, cosine = coverage_query(feature, settings, self.role)
        if point is None:
            coverage = triangulated_coverage(
                np.empty((0, 3)),
                np.empty(0, dtype=np.uint64),
                np.zeros(3),
                self.index.basis,
                nearest=np.inf,
                residual=0.0,
                cosine=cosine,
                cancel=cancel,
            )
            return PlaneCoverageScan(
                self.support.model_copy(update={"coverage": coverage}), None
            )
        normal = np.asarray(feature.geometry.normal)
        # 原拟面支持父层先复核；不在局部 Qhull 尚存活时叠加第二份候选。
        residual = 0.0
        if self.raw is not None:
            with self._candidates(
                self.raw, point, settings.support_radius, cancel=cancel
            ) as (_raw_selected, xyz, distances):
                mask = distances <= settings.support_radius
                if mask.any():
                    residual = float(normal_residuals(xyz[mask], point, normal).max())
            _raw_selected = xyz = distances = mask = None
        with self._candidates(
            self.index, point, settings.support_radius, cancel=cancel
        ) as (selected, xyz, distances):
            mask = distances <= settings.support_radius
            nearest = float(distances[mask].min()) if mask.any() else np.inf
            if mask.any():
                residual = max(
                    residual, float(normal_residuals(xyz[mask], point, normal).max())
                )
            coverage = triangulated_coverage(
                xyz[mask],
                self.index.indices[selected[mask]],
                point,
                self.index.basis,
                nearest=nearest,
                residual=residual,
                cosine=cosine,
                cancel=cancel,
            )
        selected = xyz = distances = mask = None
        nearest_support = None
        if capture_nearest:
            query, _ = self.index.query(point, 0)
            distance, _ = self.index.tree.query(query, workers=1)
            with self._candidates(
                self.index, point, float(distance), cancel=cancel
            ) as (selected, xyz, distances):
                minimum = float(distances.min())
                ties = np.flatnonzero(distances == minimum)
                chosen = int(ties[np.argmin(self.index.indices[selected[ties]])])
                nearest_support = NearestSupport(
                    minimum,
                    tuple(float(x) for x in xyz[chosen]),
                    int(self.index.indices[selected[chosen]]),
                )
            selected = xyz = distances = ties = None
        cancel()
        return PlaneCoverageScan(
            self.support.model_copy(update={"coverage": coverage}),
            tuple(point),
            nearest_support,
        )


@contextmanager
def prepare_plane_support(runtime, feature, role, *, cancel, held_working_bytes=0):
    """原支持/父层索引共同计费并归现有 Scope，退出或取消不留下索引。"""
    if type(held_working_bytes) is not int or held_working_bytes < 0:
        raise ValueError("已有平面查询工作量必须为非负整数")
    prepared = PreparedPlaneSupport(runtime, feature, role, held_working_bytes)
    registered = False
    try:
        cancel()
        prepared.support = support_snapshot(
            runtime, feature.support, role, cancel=cancel, plane=feature
        )
        if feature.valid:
            cloud = feature.support
            method = cloud.provenance.method
            raw = (
                runtime.parent_reference(cloud)
                if method and method.method_id == "fit-plane-support"
                else None
            )
            # 含双精度位置/投影、原行号、树节点和构建副本；原生 RSS 另验。
            prepared.held_bytes = 1024 + 256 * (
                cloud.point_count + (raw.point_count if raw else 0)
            )
            combined = prepared.held_bytes + held_working_bytes
            _rows(runtime, cloud, held_bytes=combined)
            prepared.reservation = runtime.budget.reserve(prepared.held_bytes)
            basis = _tangent(np.asarray(feature.geometry.normal))
            prepared.index = _SupportIndex(
                runtime, cloud, basis, held_bytes=combined, cancel=cancel
            )
            if raw is not None:
                prepared.raw = _SupportIndex(
                    runtime, raw, basis, held_bytes=combined, cancel=cancel
                )
        runtime.storage_scope.register(
            prepared.key, prepared, lambda value: value.close()
        )
        registered = True
        yield prepared
    except BaseException as error:
        release_exception_frames(error)
        raise
    finally:
        if registered:
            runtime.storage_scope.close_resource(prepared.key)
        else:
            prepared.close()
