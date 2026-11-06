"""高度图运行期结果复用 CloudRuntime/Scope，不另建句柄或缓存系统。"""

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator, Mapping

import numpy as np

from backend.contracts.workflows.height_map3d import HeightMapParameters, PoseGridFrame
from backend.contracts.workflows.point_cloud import canonical_cloud_json
from backend.contracts.workflows.point_cloud_runtime import CloudReference
from backend.contracts.workflows.pose3d_operations import PoseEvidence
from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.exception_cleanup import (
    release_exception_frames,
)
from backend.service.application.workflows.point_cloud.arrays import OwnedCloudArrays
from custom_nodes.metrology3d_nodes.shared.boundary_runtime import own_output
from custom_nodes.metrology3d_nodes.shared.height_grid import (
    aggregate_grid,
    grid_edges,
    grid_working_bytes,
    project_grid_block,
)
from custom_nodes.metrology3d_nodes.shared.pose_source import require_pose


@dataclass(frozen=True)
class HeightMapResult:
    """内部计算结果；父引用与生成来源仍由同一次 Runtime 核验和持有。"""

    input_json: bytes
    parameters_json: bytes
    pose_json: bytes | None
    owner: OwnedCloudArrays | None
    resource_key: tuple | None
    reason: str | None
    outside_count: int
    occupied_count: int
    max_rounding_error: float

    @contextmanager
    def borrow(self, runtime) -> Iterator[Mapping[str, np.ndarray]]:
        """借用同时保护父来源和格数组；不能在 Scope 结束后重用运行结果。"""
        if self.owner is None:
            raise InvalidRequestError(self.reason or "高度图没有可用数组")
        parent = CloudReference.model_validate_json(self.input_json)
        if not runtime.storage_scope.owns(self.owner):
            raise InvalidRequestError("高度图不属于当前运行")
        with runtime.borrow(parent), self.owner.borrow() as arrays:
            yield arrays


def resolve_grid_pose(runtime, reference, parameters, pose, cancel):
    """与现有测量共用位姿质量/支持验证，失效位姿不回退当前坐标。"""
    if (reference.run_id, reference.spatial.length_unit) != (
        runtime.run_id,
        parameters.length_unit,
    ) or reference.spatial.axes.handedness != "right":
        raise InvalidRequestError("高度图运行、单位或坐标轴不一致")
    frame = parameters.frame
    if not isinstance(frame, PoseGridFrame):
        if pose is not None or frame.frame_id != reference.spatial.frame_id:
            raise InvalidRequestError("高度图当前坐标与配置不一致")
        return None, None, None
    if pose is None or (pose.pose_id, pose.target_frame_id) != (
        frame.pose_id,
        frame.target_frame_id,
    ):
        raise InvalidRequestError("高度图缺少指定的本次位姿")
    require_pose(
        runtime,
        pose,
        observation_id=reference.observation_id,
        frame_id=reference.spatial.frame_id,
        length_unit=parameters.length_unit,
        cancel=cancel,
    )
    evidence = (
        PoseEvidence.model_validate(
            pose.model_dump(include=set(PoseEvidence.model_fields))
        )
        .model_dump_json()
        .encode("utf-8")
    )
    if pose.state != "found":
        return None, evidence, pose.reason
    return np.asarray(pose.transform.matrix, dtype=np.float64), evidence, None


def cloud_to_height_map(
    runtime, reference, parameters: HeightMapParameters, *, cancel, pose=None
):
    """分块投影完整输入；每格聚合当前记录，不把生成点展开成额外权重。"""
    with runtime.producing():
        return _build_height_map(runtime, reference, parameters, cancel=cancel, pose=pose)


def _build_height_map(runtime, reference, parameters, *, cancel, pose):
    """完整计算期间保持现有运行生命周期，只有成功结果移交数组所有权。"""
    cancel()
    parameters = HeightMapParameters.model_validate(parameters.model_dump())
    if reference.state == "ready":
        with runtime.borrow(reference):
            pass
    transform, evidence, reason = resolve_grid_pose(
        runtime, reference, parameters, pose, cancel
    )
    identity = dict(
        input_json=canonical_cloud_json(reference.model_dump(mode="json")),
        parameters_json=parameters.model_dump_json().encode("utf-8"),
        pose_json=evidence,
    )
    reason = reason or (reference.reason if reference.state == "unavailable" else None)
    if reason is not None:
        return HeightMapResult(
            **identity,
            owner=None,
            resource_key=None,
            reason=reason,
            outside_count=0,
            occupied_count=0,
            max_rounding_error=0.0,
        )
    count = reference.point_count
    base = grid_working_bytes(count, parameters)
    width = sum(np.dtype(f.dtype).itemsize * f.components for f in reference.fields)
    rows = min(
        runtime.policy.chunk_rows,
        (runtime.policy.max_working_bytes - base) // (width * 2 + 192),
    )
    if rows < 1:
        raise InvalidRequestError("高度图完整格、来源与工作块超过工作预算")
    dtype = next(f.dtype for f in reference.fields if f.name == "positions")
    keys, cells, heights, identities, result, block = [], None, None, None, None, None
    try:
        cells = np.empty(count, dtype=np.int64)
        heights = np.empty(count, dtype=np.float64)
        identities = np.empty(count, dtype="<u8")
        edges = grid_edges(parameters)
        with runtime.borrow(reference) as view:
            for start in range(0, count, rows):
                cancel()
                stop = min(count, start + rows)
                block = view.chunk(start, stop)
                if not np.isfinite(block["positions"]).all() or (
                    "validity" in block and not block["validity"].all()
                ):
                    raise InvalidRequestError(
                        "高度图输入包含无效点，请先执行 Filter Valid"
                    )
                cells[start:stop], heights[start:stop] = project_grid_block(
                    block["positions"], parameters, edges, target_from_source=transform
                )
                identities[start:stop] = (
                    view.source_indices(start, stop)
                    if reference.vertex_kind == "source"
                    else np.arange(start, stop, dtype=np.uint64)
                )
            block = None
        result = aggregate_grid(
            cells, heights, identities, parameters, dtype=dtype, cancel=cancel
        )
        if reference.vertex_kind == "source":
            result.arrays["source_rows"] = identities[
                result.arrays["input_rows"][:, 0]
            ].reshape(-1, 1)
        cancel()
        owner = own_output(runtime, result.arrays, keys)
        cancel()
        return HeightMapResult(
            **identity,
            owner=owner,
            resource_key=keys[0],
            reason=None,
            outside_count=result.outside_count,
            occupied_count=result.occupied_count,
            max_rounding_error=result.max_rounding_error,
        )
    except BaseException as error:
        cells = heights = identities = result = block = None
        release_exception_frames(error)
        for key in reversed(keys):
            runtime.storage_scope.close_resource(key)
        raise
