"""实测边沿现有完整点云资产保存；候选、失败和目标证据不可分开裁减。"""

from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from uuid import uuid4

import numpy as np

from backend.contracts.workflows.edge3d import (
    EdgeChainSettings,
    HeightJumpCandidateSettings,
    HeightJumpPairingSettings,
    NormalCreaseSettings,
    NormalEdgeSettings,
)
from backend.contracts.workflows.edge3d_selection import (
    EdgeTargetReport,
    EdgeTargetSelection,
)
from backend.contracts.workflows.edge_evidence import EdgeEvidence
from backend.contracts.workflows.edge_extraction import MeasuredEdgeParameters
from backend.contracts.workflows.evaluation3d import EvaluationPlane3d
from backend.contracts.workflows.height_map_reference import HeightMapReference
from backend.contracts.workflows.point_cloud_runtime import CloudReference
from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.exception_cleanup import (
    release_exception_frames,
)
from backend.service.application.workflows.documents.cloud_resource_blobs import (
    CheckedBlobStream,
    cloud_blob_key,
)
from backend.service.application.workflows.point_cloud.arrays import OwnedCloudArrays
from custom_nodes.metrology3d_nodes.shared.edge_normal_runtime import NormalEdgePairs
from custom_nodes.metrology3d_nodes.shared.edge_pairing import PairStatus


@dataclass(frozen=True)
class StoredEdgeResult:
    """恢复的只读证据依赖本次完整云；不接续旧运行或自动重算。"""

    cloud_json: str
    evidence_json: str
    owner: OwnedCloudArrays
    resource_key: tuple
    height_evidence_json: str | None = None

    @contextmanager
    def borrow(self, runtime):
        """通过相同 Scope 和父云检查借用所有固定组。"""
        if not runtime.storage_scope.owns(self.owner):
            raise InvalidRequestError("实测边持久证据已释放")
        cloud = CloudReference.model_validate_json(self.cloud_json)
        with runtime.borrow(cloud), self.owner.borrow() as arrays:
            yield {
                group: {
                    key.split(".", 1)[1]: value
                    for key, value in arrays.items()
                    if key.startswith(group + ".")
                }
                for group in ("candidates", "pairs", "chains", "targets")
            }

    def reports(self, reference):
        """只重绑定质量观测身份，失败理由、数值和规则不变。"""
        if CloudReference.model_validate_json(self.cloud_json) != reference:
            raise InvalidRequestError("实测边报告与当前点云不一致")
        result = []
        for report in EdgeEvidence.model_validate_json(self.evidence_json).reports:
            data = report.model_dump(mode="json")
            if data["quality"] is not None:
                data["quality"]["metrics"]["observation_id"] = reference.observation_id
            for segment in data["segments"]:
                segment["quality"]["metrics"]["observation_id"] = (
                    reference.observation_id
                )
            result.append(EdgeTargetReport.model_validate(data))
        return tuple(result)


def _metadata(reference, result, groups):
    """冻结现有参数和报告，不保存父高度图的运行引用。"""
    chains, pairs = result.chains, result.chains.pairs
    candidates = pairs.candidates
    normal = isinstance(pairs, NormalEdgePairs)
    parent = (
        CloudReference.model_validate_json(candidates.cloud_json)
        if normal
        else HeightMapReference.model_validate_json(candidates.height_map_json).cloud
    )
    if parent != reference or reference.vertex_kind != "source":
        raise InvalidRequestError("实测边保存必须使用同一完整源云")
    if normal:
        method = dict(
            kind="normal-crease",
            candidates=NormalCreaseSettings.model_validate_json(
                candidates.settings_json
            ),
            pairing=NormalEdgeSettings.model_validate_json(pairs.settings_json),
        )
    else:
        method = dict(
            kind="height-jump",
            candidates=HeightJumpCandidateSettings.model_validate_json(
                candidates.settings_json
            ),
            pairing=HeightJumpPairingSettings.model_validate_json(pairs.settings_json),
            chains=EdgeChainSettings.model_validate_json(chains.settings_json),
            missing_pair_count=candidates.missing_pair_count,
        )
    p, c, t = (groups[k] for k in ("pairs", "chains", "targets"))
    return EdgeEvidence(
        extraction=MeasuredEdgeParameters.model_validate_json(result.extraction_json)
        if result.extraction_json is not None
        else None,
        method=method,
        selection=EdgeTargetSelection.model_validate_json(result.settings_json),
        evaluation=EvaluationPlane3d.model_validate_json(result.evaluation_json),
        reports=tuple(
            EdgeTargetReport.model_validate_json(raw) for raw in result.reports_json
        ),
        chain_reason=chains.reason,
        input_count=reference.point_count,
        candidate_count=candidates.candidate_count,
        supported_count=candidates.supported_count,
        record_count=len(p["input_rows"]),
        pair_count=pairs.pair_count,
        pair_edge_count=len(p["edges"]) if normal else 0,
        vertex_count=len(c["positions"]),
        edge_count=len(c["edges"]),
        issue_count=len(c["issues"]),
        segment_count=len(c["closed"]),
        segment_row_count=len(c["segment_rows"]),
        isolated_count=len(c["isolated"]),
        selected_count=len(t["chain_rows"]),
    )


def _offsets(values, count):
    """CSR 精确覆盖，失败目标允许零段，不允许倒序或漏尾。"""
    flat = values[:, 0]
    if (
        not len(flat)
        or flat[0] != 0
        or flat[-1] != count
        or np.any(flat[1:] < flat[:-1])
    ):
        raise InvalidRequestError("实测边偏移与记录数不一致")


def validate_edge(runtime, reference, evidence, groups, cancel, height_evidence=None):
    """交叉检查完整来源、互配及目标切片，不重算拟合、选择或限值。"""
    expected = {g: set() for g in ("candidates", "pairs", "chains", "targets")}
    for group, name, dtype, count, width in evidence.layout():
        expected[group].add(name)
        array = groups[group][name]
        if array.shape != (count, width) or array.dtype != np.dtype(dtype):
            raise InvalidRequestError(f"实测边数组 {group}.{name} 布局不一致")
    if set(groups) != set(expected) or any(
        set(groups[g]) != expected[g] for g in expected
    ):
        raise InvalidRequestError("实测边数组集合不完整")
    width = sum(np.dtype(f.dtype).itemsize * f.components for f in reference.fields)
    rows = min(
        runtime.policy.chunk_rows, runtime.policy.max_working_bytes // (width * 2 + 512)
    )
    if rows < 1:
        raise InvalidRequestError("实测边来源核对工作预算不足")
    candidate, pairs, chains, targets = (
        groups[k] for k in ("candidates", "pairs", "chains", "targets")
    )
    supported = int(np.count_nonzero(candidate["reason"] == 0))
    if supported != evidence.supported_count:
        raise InvalidRequestError("实测边支持计数不一致")
    for start in range(0, evidence.candidate_count, rows):
        cancel()
        stop = min(start + rows, evidence.candidate_count)
        counts = candidate["counts"][start:stop]
        window = candidate["window_counts"][start:stop]
        if (
            np.any(counts > evidence.input_count)
            or np.any(window > evidence.input_count)
            or np.any(window[:, 2] > counts.min(axis=1))
            or np.any(window[:, 0] != counts.sum(axis=1) - window[:, 2] + window[:, 1])
        ):
            raise InvalidRequestError("实测边完整窗口计数不守恒")
        accepted = candidate["reason"][start:stop, 0] == 0
        if any(
            not np.isfinite(candidate[name][start:stop][accepted]).all()
            for name in ("rms", "maximum", "model_origins", "model_normals")
        ):
            raise InvalidRequestError("有效双侧支持缺少完整模型或残差")
        normals = candidate["model_normals"][start:stop][accepted].reshape(-1, 3)
        if not np.allclose(np.linalg.norm(normals, axis=1), 1, rtol=1e-10, atol=0):
            raise InvalidRequestError("双侧支持法向不是单位向量")
    partner, state = pairs["partners"][:, 0], pairs["status"][:, 0]
    paired_count = 0
    if evidence.method.kind == "height-jump" and height_evidence is None:
        raise InvalidRequestError("高度实测边缺少同次高度图证据")
    if evidence.method.kind == "height-jump":
        from custom_nodes.metrology3d_nodes.shared.edge_targets import (
            height_evaluation_from_evidence,
        )

        if evidence.evaluation != height_evaluation_from_evidence(
            height_evidence, reference
        ):
            raise InvalidRequestError("高度实测边评价面与高度图不一致")
    with runtime.borrow(reference) as view:
        for start in range(0, evidence.record_count, rows):
            cancel()
            stop = min(start + rows, evidence.record_count)
            ids = pairs["input_rows"][start:stop, 0]
            if np.any(ids >= reference.point_count):
                raise InvalidRequestError("实测边输入记录越界")
            block, original = view.gather(ids)
            if not np.array_equal(original, pairs["source_rows"][start:stop, 0]):
                raise InvalidRequestError("实测边最初行号与源云不一致")
            if evidence.method.kind == "normal-crease":
                if not np.array_equal(
                    ids, np.arange(start, stop)
                ) or not np.array_equal(
                    block["positions"], pairs["positions"][start:stop]
                ):
                    raise InvalidRequestError("法向实测边未保留完整源坐标")
                if not np.array_equal(
                    candidate["source_rows"][start:stop, 0], original
                ):
                    raise InvalidRequestError("法向候选原始行号不一致")
            else:
                from custom_nodes.metrology3d_nodes.shared.height_grid import (
                    grid_local_points,
                )

                transform = (
                    np.asarray(height_evidence.pose.transform.matrix)
                    if height_evidence.pose is not None
                    else None
                )
                expected = grid_local_points(
                    block["positions"],
                    height_evidence.parameters,
                    target_from_source=transform,
                )
                if not np.array_equal(expected, pairs["positions"][start:stop]):
                    raise InvalidRequestError("高度实测边位置与原始输入不一致")
            accepted = state[start:stop] == PairStatus.PAIRED
            local = partner[start:stop]
            if (
                np.any((local >= 0) != accepted)
                or np.any(local < -1)
                or np.any(local >= evidence.record_count)
            ):
                raise InvalidRequestError("实测配对状态与对点不一致")
            selected = np.arange(start, stop)[accepted]
            other = local[accepted]
            if (
                np.any(partner[other] != selected)
                or np.any(state[other] != PairStatus.PAIRED)
                or np.any(selected == other)
            ):
                raise InvalidRequestError("实测点对不是互相配对")
            if np.any(pairs["sides"][selected, 0] + pairs["sides"][other, 0] != 1):
                raise InvalidRequestError("实测点对未来自不同侧")
            metrics = pairs["metrics"][start:stop]
            if not np.isnan(metrics[~accepted]).all():
                raise InvalidRequestError("失败点对不能保留可消费距离")
            delta = pairs["positions"][other] - pairs["positions"][selected]
            if evidence.method.kind == "normal-crease":
                if not np.isnan(metrics[:, (0, 2)]).all():
                    raise InvalidRequestError("法向点对不能伪造面内间隙或高度差")
                actual = metrics[accepted, 1]
                expected = np.linalg.norm(delta, axis=1)
            else:
                actual = metrics[accepted]
                expected = np.column_stack(
                    (
                        np.linalg.norm(delta[:, :2], axis=1),
                        np.linalg.norm(delta, axis=1),
                        delta[:, 2],
                    )
                )
            if not np.allclose(actual, expected, rtol=1e-12, atol=0):
                raise InvalidRequestError("实测点对距离与原始位置不一致")
            paired_count += len(selected)
    if paired_count != evidence.pair_count * 2:
        raise InvalidRequestError("实测点对总数不一致")
    if evidence.method.kind == "height-jump":
        _offsets(pairs["offsets"], evidence.record_count)
    _offsets(chains["segment_offsets"], evidence.segment_row_count)
    _offsets(targets["offsets"], evidence.selected_count)
    for start in range(0, evidence.vertex_count, rows):
        cancel()
        stop = min(start + rows, evidence.vertex_count)
        selected = chains["pair_rows"][start:stop, 0]
        other = chains["other_rows"][start:stop, 0]
        if (
            np.any(selected < 0)
            or np.any(selected >= evidence.record_count)
            or not np.array_equal(partner[selected], other)
        ):
            raise InvalidRequestError("实测连续段对点来源不一致")
        for name in ("input_rows", "source_rows", "positions"):
            if not np.array_equal(chains[name][start:stop], pairs[name][selected]):
                raise InvalidRequestError("实测连续段来源与配对记录不一致")
    for index, report in enumerate(evidence.reports):
        cancel()
        start, stop = map(int, targets["offsets"][index : index + 2, 0])
        expected_count = report.topology.point_count if report.topology else 0
        if stop - start != expected_count:
            raise InvalidRequestError("实测目标切片与报告不一致")
        for begin in range(start, stop, rows):
            cancel()
            end = min(begin + rows, stop)
            selected = targets["chain_rows"][begin:end, 0]
            if np.any(selected < 0) or np.any(selected >= evidence.vertex_count):
                raise InvalidRequestError("实测目标来源越界")
            for name in ("input_rows", "source_rows"):
                if not np.array_equal(targets[name][begin:end], chains[name][selected]):
                    raise InvalidRequestError("实测目标来源与连续段不一致")


@contextmanager
def prepare_edge(
    runtime, reference, result, *, mode, chunk_bytes, cancel, height_evidence=None
):
    """同次只读证据逐字段流式保存到既有事务，不丢失败记录。"""
    from custom_nodes.metrology3d_nodes.shared.cloud_assets import _Chunks, _blob

    if mode != "derived":
        raise InvalidRequestError("实测边需要派生模式保存完整参与云")
    with ExitStack() as stack:
        if isinstance(result, StoredEdgeResult):
            if CloudReference.model_validate_json(result.cloud_json) != reference:
                raise InvalidRequestError("实测边恢复引用与保存云不一致")
            groups = stack.enter_context(result.borrow(runtime))
            evidence = EdgeEvidence.model_validate_json(result.evidence_json)
        else:
            objects = (
                result.chains.pairs.candidates,
                result.chains.pairs,
                result.chains,
                result,
            )
            groups = {
                name: stack.enter_context(value.borrow(runtime))
                for name, value in zip(
                    ("candidates", "pairs", "chains", "targets"), objects
                )
            }
            evidence = _metadata(reference, result, groups)
            if evidence.method.kind == "height-jump":
                parent = HeightMapReference.model_validate_json(
                    result.chains.pairs.candidates.height_map_json
                )
                if parent.evidence != height_evidence:
                    raise InvalidRequestError("高度实测边与保存高度图不是同次计算")
        validate_edge(runtime, reference, evidence, groups, cancel, height_evidence)

        def chunks():
            for group, name, dtype, count, width in evidence.layout():
                rows = min(
                    runtime.policy.chunk_rows,
                    chunk_bytes // (np.dtype(dtype).itemsize * width),
                )
                if rows < 1:
                    raise InvalidRequestError("实测边写出块不足一个完整记录")
                for start in range(0, count, rows):
                    cancel()
                    yield groups[group][name][start : start + rows].tobytes(order="C")

        blob = _blob("edge", "edge.bin", chunks())
        yield evidence, blob, _Chunks(chunks())


def read_edge(runtime, reference, *, document, service, project_id, policy, cancel):
    """恢复同一次全部证据并绑定新 Scope；失败不升级为成功，不调用算法。"""
    from custom_nodes.metrology3d_nodes.shared.cloud_assets import _fill

    if (
        service.read(document.reference, project_id=project_id) != document
        or reference.source.kind != "asset"
        or reference.source.reference != document.reference
    ):
        raise InvalidRequestError("实测边与读取资产身份不一致")
    asset = document.content.point_cloud
    evidence = asset.edge
    if evidence is None:
        return None
    size = evidence.byte_length()
    if size > min(policy.max_asset_bytes, runtime.policy.max_decoded_bytes):
        raise InvalidRequestError("实测边证据超过显式读取容量")
    chunk = min(
        policy.chunk_bytes, runtime.policy.chunk_bytes, runtime.policy.max_working_bytes
    )
    arrays, owner, key = {}, None, ("edge-evidence", uuid4().hex)
    with runtime.producing(), runtime.borrow(reference):
        reservation = runtime.budget.reserve(size)
        try:
            for group, name, dtype, count, width in evidence.layout():
                cancel()
                arrays[f"{group}.{name}"] = np.empty((count, width), dtype=dtype)
            blob = next(b for b in asset.blobs if b.role == "edge")
            with service.storage.open_read_snapshot(
                cloud_blob_key(service, document.reference, blob)
            ) as snapshot:
                stream = CheckedBlobStream(snapshot.stream, blob, cancel, asset)
                for array in arrays.values():
                    _fill(stream, array, chunk, cancel)
                array = None
                if stream.read(1):
                    raise InvalidRequestError("实测边含多余字节")
            groups = {
                group: {
                    key.split(".", 1)[1]: value
                    for key, value in arrays.items()
                    if key.startswith(group + ".")
                }
                for group in ("candidates", "pairs", "chains", "targets")
            }
            validate_edge(
                runtime, reference, evidence, groups, cancel, asset.height_map
            )
            owner = OwnedCloudArrays(arrays, reservation)
            arrays.clear()
            runtime.storage_scope.register(key, owner, lambda value: value.close())
            cancel()
            return StoredEdgeResult(
                reference.model_dump_json(),
                evidence.model_dump_json(),
                owner,
                key,
                asset.height_map.model_dump_json()
                if asset.height_map is not None
                else None,
            )
        except BaseException as error:
            arrays.clear()
            release_exception_frames(error)
            runtime.storage_scope.close_resource(key)
            if owner is not None:
                owner.close()
            reservation.close()
            raise
