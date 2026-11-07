"""实测点对沿已有 Scope 持有；完整候选诊断和原始行号一起保留。"""

from contextlib import contextmanager
from dataclasses import dataclass

import numpy as np

from backend.contracts.workflows.edge3d import (
    HeightJumpCandidateSettings,
    HeightJumpPairingSettings,
)
from backend.contracts.workflows.height_map_reference import HeightMapReference
from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.exception_cleanup import (
    release_exception_frames,
)
from backend.service.application.workflows.point_cloud.arrays import OwnedCloudArrays
from custom_nodes.metrology3d_nodes.shared.boundary_runtime import own_output
from custom_nodes.metrology3d_nodes.shared.edge_height_candidates import (
    HeightJumpCandidates,
)
from custom_nodes.metrology3d_nodes.shared.edge_pairing import pair_points, PairStatus
from custom_nodes.metrology3d_nodes.shared.height_grid import grid_local_points
from custom_nodes.metrology3d_nodes.shared.height_map_reference import (
    resolve_height_map,
)


@dataclass(frozen=True)
class HeightJumpPairs:
    """候选 CSR 内的记录保持输入身份；不是新的点云或持久资产协议。"""

    candidates: HeightJumpCandidates
    settings_json: str
    owner: OwnedCloudArrays
    resource_key: tuple
    pair_count: int

    @contextmanager
    def borrow(self, runtime):
        """父候选、父云或自身任一释放后不能继续读取。"""
        if not runtime.storage_scope.owns(self.owner):
            raise InvalidRequestError("实测配对资源已释放")
        with self.candidates.borrow(runtime), self.owner.borrow() as arrays:
            yield arrays


def pair_height_candidates(runtime, cloud, candidates, settings, *, cancel):
    """仅实测源点形成边证据；生成点不伪装唯一原始行，拟面不重复计算。"""
    settings = HeightJumpPairingSettings.model_validate(settings.model_dump())
    if cloud.vertex_kind != "source":
        raise InvalidRequestError("实测边配对需要原始点，生成点不能冒充实测边")
    ref = HeightMapReference.model_validate_json(candidates.height_map_json)
    support = HeightJumpCandidateSettings.model_validate_json(candidates.settings_json)
    keys, output = [], None
    with runtime.producing():
        parent = resolve_height_map(runtime, ref, cloud=cloud)
        try:
            with (
                candidates.borrow(runtime) as evidence,
                parent.borrow(runtime) as grid,
                runtime.borrow(cloud) as view,
            ):
                cancel()
                count = len(evidence["cells"])
                sizes = grid["counts"][:, 0]
                # 保留所有候选两格贡献，包括模型失败的候选；每格对独立追溯。
                total, largest = 0, 0
                for a, b in evidence["cells"]:
                    cancel()
                    size = int(sizes[a]) + int(sizes[b])
                    total += size
                    largest = max(largest, size)
                held = (
                    sum(a.nbytes for a in (*evidence.values(), *grid.values()))
                    + (count + 1) * 8
                    + total * 82
                )
                width = sum(
                    np.dtype(f.dtype).itemsize * f.components for f in cloud.fields
                )
                available = runtime.policy.max_working_bytes - held - largest * 512
                rows = min(runtime.policy.chunk_rows, available // (width * 2 + 256))
                if rows < 1:
                    raise InvalidRequestError("实测配对完整证据及邻域超过工作预算")
                output = dict(
                    offsets=np.zeros((count + 1, 1), dtype="<u8"),
                    input_rows=np.empty((total, 1), dtype="<u8"),
                    source_rows=np.empty((total, 1), dtype="<u8"),
                    cells=np.empty((total, 1), dtype="<u8"),
                    positions=np.empty((total, 3), dtype="<f8"),
                    sides=np.full((total, 1), 2, dtype="u1"),
                    status=np.full((total, 1), PairStatus.SUPPORT_INVALID, dtype="u1"),
                    partners=np.full((total, 1), -1, dtype="<i8"),
                    metrics=np.full((total, 3), np.nan, dtype="<f8"),
                )
                transform = (
                    np.asarray(ref.evidence.pose.transform.matrix)
                    if ref.evidence.pose
                    else None
                )
                member_offsets = grid["member_offsets"][:, 0]
                cursor, pairs = 0, 0
                for index, cells in enumerate(evidence["cells"]):
                    cancel()
                    begin = cursor
                    for cell in cells:
                        first, last = (
                            int(member_offsets[cell]),
                            int(member_offsets[cell + 1]),
                        )
                        for start in range(first, last, rows):
                            cancel()
                            stop = min(start + rows, last)
                            logical = grid["input_rows"][start:stop, 0]
                            values, original = view.gather(logical)
                            end = cursor + len(logical)
                            output["input_rows"][cursor:end, 0] = logical
                            output["source_rows"][cursor:end, 0] = original
                            output["cells"][cursor:end, 0] = cell
                            output["positions"][cursor:end] = grid_local_points(
                                values["positions"],
                                ref.evidence.parameters,
                                target_from_source=transform,
                            )
                            cursor = end
                    output["offsets"][index + 1, 0] = cursor
                    if evidence["reason"][index, 0] != 0:
                        continue
                    sides, state, partners, metrics = pair_points(
                        output["positions"][begin:cursor],
                        evidence["model_origins"][index].reshape(2, 3),
                        evidence["model_normals"][index].reshape(2, 3),
                        support,
                        settings,
                        chunk_rows=rows,
                        cancel=cancel,
                    )
                    paired = partners >= 0
                    partners[paired] += begin
                    output["sides"][begin:cursor, 0] = sides
                    output["status"][begin:cursor, 0] = state
                    output["partners"][begin:cursor, 0] = partners
                    output["metrics"][begin:cursor] = metrics
                    pairs += int(paired.sum()) // 2
                cancel()
                owner = own_output(runtime, output, keys)
                output = None
                cancel()
                return HeightJumpPairs(
                    candidates, settings.model_dump_json(), owner, keys[0], pairs
                )
        except BaseException as error:
            output = None
            release_exception_frames(error)
            for key in reversed(keys):
                runtime.storage_scope.close_resource(key)
            raise
