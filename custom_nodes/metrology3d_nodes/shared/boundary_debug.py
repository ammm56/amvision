"""同次算法证据的有界临时正文；复用运行 Scope，不保留原云或新增资源服务。"""

import base64
from hashlib import sha256
from tempfile import TemporaryFile
from threading import RLock
from uuid import uuid4

import numpy as np

from backend.contracts.workflows.boundary3d_debug import (
    BoundaryDebugDisplay,
    BoundaryDebugReference,
    DebugArray,
    DebugGrid,
)
from backend.contracts.workflows.geometry3d_methods import parameter_digest
from backend.contracts.workflows.point_cloud import canonical_cloud_json
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.point_cloud.budget import CloudArrayBudget


class BoundaryCapture:
    """仅捕获已有计算值，按块冻结到临时文件，避免占用后续量测的活跃数组额度。"""

    def __init__(
        self,
        runtime,
        reference,
        parameters,
        *,
        policy,
        directory,
        node_id,
        invocation_id,
        cancel,
    ):
        """容量来自原 Preview 策略；文件归属现有 storage_scope，退出后自动删除。"""
        self.identity = BoundaryDebugReference(
            capture_id=uuid4().hex,
            run_id=runtime.run_id,
            node_id=node_id,
            invocation_id=invocation_id,
            observation_id=reference.observation_id,
            feature_id=parameters.feature_id,
            parameters_sha256=parameter_digest(parameters),
        )
        self.policy, self.cancel = policy, cancel
        self.chunk_bytes = min(runtime.policy.chunk_bytes, policy.max_working_bytes)
        self.working_limit = 0
        self.source_rows = None
        self.evaluation = None
        self.grid = None
        self.target_ids = tuple(t.target_id for t in parameters.targets)
        self.stage, self.selection_complete = "input", False
        self.reason, self.measurement_reason = None, None
        self.failure_field, self.required_bytes = None, None
        self.fields, self.reservations, self.events = [], [], []
        self.length, self.event_bytes = 0, 0
        self._digest = sha256()
        self._stream, self._closed, self._finished = None, False, False
        self._lock = RLock()
        self._quota = runtime.storage_scope.get_or_create(
            ("boundary-debug-capacity",),
            lambda: CloudArrayBudget(policy.max_data_bytes),
            lambda _: None,
        )
        if self._quota.limit != policy.max_data_bytes:
            raise InvalidRequestError("同 Run 调试策略不一致")
        self.key = ("boundary-debug", self.identity.capture_id)
        runtime.storage_scope.register(self.key, self, lambda value: value.close())
        try:
            self._stream = TemporaryFile(mode="w+b", dir=directory)
        except OSError:
            self.unavailable("debug_storage_failed")

    def unavailable(self, reason):
        """只影响此附件；没有内容时不保留临时文件或容量。"""
        with self._lock:
            self.reason = reason
            if self._stream is not None:
                self._stream.close()
                self._stream = None
            self.fields.clear()
            self.events.clear()
            self.event_bytes = self.length = 0
            for reservation in self.reservations:
                reservation.close()
            self.reservations.clear()

    def close(self):
        """由原 Scope 幂等回收；调用方不得在关闭后重新获取正文。"""
        with self._lock:
            self.unavailable("debug_scope_closed")
            self._closed = True
            self.source_rows = None

    def put(self, name, values, *, dtype=None, missing=False):
        """只增加冻结输出，不持有数组；先准入，再分块进行小端转换与写入。"""
        if self.reason is not None:
            return
        self.cancel()
        if self._closed or self._finished:
            raise RuntimeError("调试捕获已关闭或完成")
        array = np.asarray(values)
        if array.ndim == 1:
            array = array.reshape(-1, 1)
        target = np.dtype(dtype or array.dtype).newbyteorder("<")
        if (
            array.ndim != 2
            or not 1 <= array.shape[1] <= 4
            or target.name not in {"float32", "float64", "uint8", "uint64", "int64"}
        ):
            raise ValueError("调试数组形状或类型错误")
        if len(self.fields) >= 48 or any(f.name == name for f in self.fields):
            raise ValueError("调试字段重复或超出契约")
        width = target.itemsize
        offset = (self.length + width - 1) // width * width
        size = int(array.size) * width
        row_bytes = array.shape[1] * (array.dtype.itemsize + width) * 4
        rows = min(
            len(array) or 1,
            min(self.chunk_bytes, self.working_limit - self.event_bytes)
            // max(1, row_bytes),
        )
        if rows < 1 or offset + size > self.policy.max_data_bytes:
            self.failure_field, self.required_bytes = name, offset + size
            self.unavailable("debug_size_limit")
            return
        try:
            reservation = self._quota.reserve(offset + size - self.length)
        except InvalidRequestError:
            self.failure_field, self.required_bytes = (
                name,
                self._quota.used + offset + size - self.length,
            )
            self.unavailable("debug_size_limit")
            return
        self.reservations.append(reservation)
        try:
            padding = bytes(offset - self.length)
            self._stream.write(padding)
            self._digest.update(padding)
            for start in range(0, len(array), rows):
                self.cancel()
                block = np.array(
                    array[start : start + rows], dtype=target, order="C", copy=True
                )
                if target.kind == "f":
                    if missing:
                        # 空格的值只作占位，前端必须结合 counts/usable 掩码读取。
                        block[np.isnan(block)] = 0
                    if not np.isfinite(block).all():
                        raise ValueError("调试数组含未声明的非有限值")
                binary = memoryview(block).cast("B")
                self._stream.write(binary)
                self._digest.update(binary)
            self.fields.append(
                DebugArray(
                    name=name,
                    dtype=target.name,
                    count=len(array),
                    components=array.shape[1],
                    offset=offset,
                    byte_length=size,
                )
            )
            self.length = offset + size
        except OSError:
            self.unavailable("debug_storage_failed")
        except MemoryError:
            self.unavailable("debug_allocation_failed")

    def event(self, target_index, candidate_index, state, count):
        """0 未匹配、1 命中、2 闭环拒绝；尚未遍历的候选没有事件，不能当作排除。"""
        if self.reason is not None:
            return
        if (len(self.events) + 1) * 256 > min(
            self.policy.max_data_bytes, self.working_limit // 2
        ):
            self.unavailable("debug_size_limit")
            return
        try:
            self.events.append((target_index, candidate_index, state, count))
            self.event_bytes += 256
        except MemoryError:
            self.unavailable("debug_allocation_failed")

    def finish(self, reason):
        """在节点输出确定后封口；失败几何与显示状态分别记录。"""
        self.measurement_reason = reason
        if self.events:
            try:
                self.put("selection_events", np.asarray(self.events, dtype="<u8"))
            except MemoryError:
                self.unavailable("debug_allocation_failed")
        self.events.clear()
        self.event_bytes = 0
        if reason is None:
            self.stage, self.selection_complete = "complete", True
        self._finished = True
        return self.identity

    def display(self, *, max_bytes, cancel, max_data_bytes=None):
        """借用文件生成独立有界正文；跨进程只传冻结内容，不交付文件句柄。"""
        with self._lock:
            if self._closed or not self._finished:
                raise InvalidRequestError("调试证据已释放或尚未完成")
            state = (
                "unavailable"
                if self.reason
                else "not-executed"
                if self.stage == "input" or not self.fields
                else "ready"
            )
            data = None
            reason = self.reason or (
                "debug_not_executed" if state == "not-executed" else None
            )
            if state == "ready":
                encoded_size = 4 * ((self.length + 2) // 3)
                if (
                    encoded_size * 2 + 8192 > max_bytes
                    or self.length * 8 + 8192 > self.policy.max_working_bytes
                    or max_data_bytes is not None
                    and self.length > max_data_bytes
                ):
                    state, reason = "unavailable", "debug_size_limit"
                else:
                    try:
                        cancel()
                        self._stream.seek(0)
                        raw = self._stream.read(self.length)
                        if (
                            len(raw) != self.length
                            or sha256(raw).digest() != self._digest.digest()
                        ):
                            raise ValueError("调试正文截断或摘要不一致")
                        data = dict(
                            content_length=len(raw),
                            checksum=sha256(raw).hexdigest(),
                            content=base64.b64encode(raw).decode("ascii"),
                            fields=self.fields,
                        )
                        cancel()
                    except MemoryError:
                        state, reason, data = (
                            "unavailable",
                            "debug_allocation_failed",
                            None,
                        )
                    except OSError:
                        state, reason, data = (
                            "unavailable",
                            "debug_storage_failed",
                            None,
                        )
            return BoundaryDebugDisplay(
                identity=self.identity,
                state=state,
                reason=reason,
                failure_field=self.failure_field
                or ("display" if state == "unavailable" and not self.reason else None),
                required_bytes=self.required_bytes
                or (self.length if state == "unavailable" else None),
                stage=self.stage,
                selection_complete=self.selection_complete,
                measurement_reason=self.measurement_reason,
                evaluation=self.evaluation,
                grid=self.grid,
                target_ids=self.target_ids,
                data=data,
            )


def capture_display(runtime, feature, *, max_bytes, cancel, max_data_bytes=None):
    """只解析当前可信 Scope 中与完整引用相同的记录，不按名称猜测。"""
    reference = feature.debug_capture
    if reference is None:
        return None
    if reference.run_id != runtime.run_id:
        raise InvalidRequestError("调试证据不属于当前 Run")

    def absent():
        raise InvalidRequestError("调试引用不存在或已释放")

    owner = runtime.storage_scope.get_or_create(
        ("boundary-debug", reference.capture_id), absent, lambda value: value.close()
    )
    if not isinstance(owner, BoundaryCapture) or owner.identity != reference:
        raise InvalidRequestError("调试引用身份不匹配")
    return owner.display(
        max_bytes=max_bytes, max_data_bytes=max_data_bytes, cancel=cancel
    )


def capture_grid(
    capture, grid, settings, *, usable, foreground, grouped, labels, selected_component
):
    """保留原分箱/分区值；闭运算新增位置与真实前景明确分开。"""
    capture.stage, capture.selection_complete = "selection", True
    capture.grid = DebugGrid(
        origin=settings.grid.origin,
        step=settings.grid.step,
        shape=settings.grid.shape,
        seed_min=settings.selection.seed_min,
        seed_max=settings.selection.seed_max,
        selection=settings.selection.kind,
        selected_component=selected_component,
    )
    for name, value, dtype in (
        ("counts", grid.counts, "uint64"),
        ("heights", grid.heights, "float64"),
        ("spread", grid.spread, "float64"),
        ("usable", usable, "uint8"),
        ("foreground", foreground, "uint8"),
        ("grouped", grouped, "uint8"),
        ("selected", grid.selected, "uint8"),
        ("components", labels, "int64"),
    ):
        if value is not None:
            capture.put(
                name, value.reshape(-1, 1), dtype=dtype, missing=name == "heights"
            )


def capture_profiles(capture, positions, layouts, records, columns):
    """只冻结已有四侧站位；额外分配失败不得改变测量结果。"""
    if len(records) * 256 > capture.working_limit:
        capture.unavailable("debug_size_limit")
        return
    try:
        capture.put("profile_positions", positions)
        capture.put(
            "profile_offsets",
            np.asarray([0, *[p["start"] + p["count"] for p in layouts]]),
            dtype="uint64",
        )
        breaks = np.zeros(len(records), dtype=np.uint8)
        for layout in layouts:
            breaks[layout["start"]] = 1
            for index in layout["profile"]["breaks"]:
                breaks[layout["start"] + index] = 1
        capture.put("profile_breaks", breaks)
        capture.put("profile_kinds", np.asarray([r[4] for r in records]), dtype="uint8")
        capture.put(
            "profile_cells",
            np.asarray([[a * columns + b for a, b in (r[1], r[2])] for r in records]),
            dtype="uint64",
        )
        capture.put(
            "profile_weights",
            np.asarray([[1 - r[3], r[3]] for r in records]),
            dtype="float64",
        )
    except MemoryError:
        capture.unavailable("debug_allocation_failed")


def capture_candidates(capture, vertices, selected, candidates, section, faces):
    """冻结全部候选，仅保留实际引用的源点/面；局部重编号不改变原始行号。"""
    capture.stage = "candidates"
    if capture.reason is not None:
        return
    count = sum(len(c.indices) for c in candidates)
    work = (count + len(candidates) + 1) * 64
    if section is not None:
        work += (len(section.face_indices) + len(section.positions)) * 256
    if work > capture.working_limit:
        capture.unavailable("debug_size_limit")
        return
    capture.cancel()
    joined = (
        np.concatenate([c.indices for c in candidates])
        if candidates
        else np.empty(0, dtype=np.int64)
    )
    if section is None:
        used, compact = np.unique(joined, return_inverse=True)
        capture.put("candidate_positions", vertices[used])
        source_rows = capture.source_rows[selected[used]]
    else:
        face_ids, face_rows = np.unique(section.face_indices, return_inverse=True)
        source_faces = faces[face_ids]
        used = np.unique(
            np.concatenate(
                (section.source_vertices.reshape(-1), source_faces.reshape(-1))
            )
        )
        source_rows = capture.source_rows[selected[used]]
        compact = joined
        capture.put("candidate_positions", vertices)
        capture.put(
            "source_edges",
            np.searchsorted(used, section.source_vertices),
            dtype="uint64",
        )
        capture.put("source_weights", section.weights, dtype="float64")
        capture.put("surface_face_ids", face_ids, dtype="uint64")
        capture.put(
            "surface_faces", np.searchsorted(used, source_faces), dtype="uint64"
        )
        capture.put("section_edges", section.edges, dtype="uint64")
        capture.put("section_face_offsets", section.face_offsets, dtype="uint64")
        capture.put("section_faces", face_rows, dtype="uint64")
    capture.put("input_source_indices", source_rows, dtype="uint64")
    capture.put("local_source_rows", np.arange(len(source_rows), dtype="<u8"))
    capture.put("candidate_indices", compact, dtype="uint64")
    capture.put(
        "candidate_offsets",
        np.concatenate(([0], np.cumsum([len(c.indices) for c in candidates]))),
        dtype="uint64",
    )
    capture.put(
        "candidate_closed", np.asarray([c.closed for c in candidates]), dtype="uint8"
    )


def attach_debug(runtime, cloud, body, values, *, policy, cancel):
    """沿现有 features 连线读取可选诊断；容量不足不删除基础显示或测量结果。"""
    from backend.contracts.workflows.geometry3d_observations import Features3d

    if body["state"] not in {"ready", "empty"}:
        return body
    attached = []
    remaining_status = (
        policy.max_body_bytes
        - preview_base_policy(runtime, values, policy, cancel=cancel).max_body_bytes
    )
    size = len(canonical_cloud_json({**body, "boundary_debug": []}))
    data_remaining = policy.max_data_bytes - (body.get("data") or {}).get(
        "content_length", 0
    )
    data_remaining -= ((body.get("height_map") or {}).get("data") or {}).get(
        "content_length", 0
    )
    for raw in values.get("features") or ():
        features = Features3d.model_validate(raw)
        if (
            features.run_id,
            features.observation_id,
            features.frame_id,
            features.length_unit,
        ) != (
            runtime.run_id,
            cloud.observation_id,
            cloud.spatial.frame_id,
            cloud.spatial.length_unit,
        ):
            raise InvalidRequestError("调试显示运行、观测或空间不一致")
        for feature in features.items:
            if feature.kind != "boundary" or feature.debug_capture is None:
                continue
            cancel()
            status = capture_display(runtime, feature, max_bytes=0, cancel=cancel)
            remaining_status -= (
                len(canonical_cloud_json(status.model_dump(mode="json"))) + 1
            )
            display = capture_display(
                runtime,
                feature,
                max_bytes=policy.max_body_bytes - size - remaining_status,
                max_data_bytes=data_remaining,
                cancel=cancel,
            )
            raw_display = display.model_dump(mode="json")
            length = len(canonical_cloud_json(raw_display))
            if size + length > policy.max_body_bytes:
                raise InvalidRequestError("基础显示没有容纳调试状态的空间")
            attached.append(raw_display)
            size += length + 1
            data_remaining -= display.data.content_length if display.data else 0
    return {**body, "boundary_debug": attached} if attached else body


def preview_base_policy(runtime, values, policy, *, cancel):
    """预留全部状态的最小正文；调试容量不足不能挤掉已经生成的基础显示。"""
    from backend.contracts.workflows.geometry3d_observations import Features3d

    statuses = []
    seen = set()
    for raw in values.get("features") or ():
        for feature in Features3d.model_validate(raw).items:
            if feature.kind != "boundary" or feature.debug_capture is None:
                continue
            if feature.debug_capture.capture_id in seen:
                raise InvalidRequestError("调试显示重复引用")
            seen.add(feature.debug_capture.capture_id)
            statuses.append(
                capture_display(
                    runtime, feature, max_bytes=0, cancel=cancel
                ).model_dump(mode="json")
            )
    if not statuses:
        return policy
    reserve = len(canonical_cloud_json({"boundary_debug": statuses})) + 32
    if reserve >= policy.max_body_bytes:
        raise InvalidRequestError("调试状态数量超过显示正文限额")
    return policy.model_copy(update={"max_body_bytes": policy.max_body_bytes - reserve})
