"""B09 完整原云及 A_top_L 全支持候选验证；不冒称完整边节点或生产节拍。"""

import json
from collections import Counter
from hashlib import sha256
from pathlib import Path
from time import perf_counter

import numpy as np
import pytest

from backend.contracts.workflows.edge3d import (
    HeightJumpCandidateSettings,
    HeightJumpPairingSettings,
    EdgeChainSettings,
    NormalCreaseSettings,
    NormalEdgeSettings,
)
from backend.contracts.workflows.height_map3d import HeightMapParameters
from custom_nodes.metrology3d_nodes.shared.crop_roi import crop_roi
from custom_nodes.metrology3d_nodes.shared.edge_height_candidates import (
    height_jump_candidates,
    pair_evidence,
)
from custom_nodes.metrology3d_nodes.shared.height_map import cloud_to_height_map
from custom_nodes.metrology3d_nodes.shared.edge_pair_runtime import (
    pair_height_candidates,
)
from custom_nodes.metrology3d_nodes.shared.edge_pairing import PairStatus
from custom_nodes.metrology3d_nodes.shared.edge_chains import build_edge_chains
from custom_nodes.metrology3d_nodes.shared.edge_targets import select_edge_targets
from custom_nodes.metrology3d_nodes.shared.edge_targets import height_evaluation
from custom_nodes.metrology3d_nodes.shared.edge_normal_runtime import (
    pair_normal_candidates,
    build_normal_edge_chains,
)
from custom_nodes.metrology3d_nodes.shared.edge_normal_candidates import (
    normal_crease_candidates,
    NormalNeighborhoodStatus,
    SUPPORT_REASONS,
)
from custom_nodes.metrology3d_nodes.shared.estimate_normals import estimate_normals
from tests.integration.metrology3d.test_normals_full_sample import sample_parameters
from backend.contracts.workflows.edge3d_selection import EdgeTargetSelection
from custom_nodes.metrology3d_nodes.shared.height_map_reference import (
    publish_height_map,
)
from tests.integration.metrology3d.full_cloud_sample import sample_array
from tests.integration.metrology3d.representative_recipe import boxes
from tests.integration.metrology3d.workpiece_recipe import STEEL
from tests.point_cloud_support import policy
from tests.test_metrology3d_height_map import parameters
from tests.test_metrology3d_preprocess import make_cloud


def verify_edge_asset(runtime, cloud, result, height, directory):
    """完整支持的所有候选/失败记录随资产恢复，不重新计算拟合或配对。"""
    from backend.service.application.runtime.resource_scope import ResourceScope
    from backend.service.application.workflows.point_cloud.runtime import (
        get_cloud_runtime,
    )
    from backend.service.application.workflows.documents.cloud_resource_blobs import (
        CloudAssetPolicy,
    )
    from custom_nodes.metrology3d_nodes.shared.cloud_assets import (
        save_cloud,
        read_asset,
    )
    from custom_nodes.metrology3d_nodes.shared.edge_assets import read_edge
    from tests.point_cloud_support import create_resource_service

    service = create_resource_service(directory)
    limits = CloudAssetPolicy(
        max_asset_bytes=128 * 1024**2,
        max_archive_bytes=129 * 1024**2,
        chunk_bytes=65536,
    )
    asset = save_cloud(
        runtime,
        cloud,
        edge=result,
        height_map=height,
        service=service,
        project_id="test",
        name="full-edge",
        mode="derived",
        write_identity="8" * 64,
        policy=limits,
        cancel=lambda: None,
    )
    scope = ResourceScope(kind="full-edge-restore")
    restored_runtime = get_cloud_runtime(
        scope,
        run_id="restored-edge",
        policy=runtime.policy.model_copy(
            update={"max_decoded_bytes": limits.max_asset_bytes}
        ),
    )
    digest = sha256()
    try:
        loaded = read_asset(
            restored_runtime,
            asset,
            service=service,
            project_id="test",
            policy=limits,
            cancel=lambda: None,
        )
        restored = read_edge(
            restored_runtime,
            loaded,
            document=service.read(asset, project_id="test"),
            service=service,
            project_id="test",
            policy=limits,
            cancel=lambda: None,
        )
        objects = (
            result.chains.pairs.candidates,
            result.chains.pairs,
            result.chains,
            result,
        )
        with restored.borrow(restored_runtime) as after:
            for group, obj in zip(
                ("candidates", "pairs", "chains", "targets"), objects
            ):
                with obj.borrow(runtime) as before:
                    for name in sorted(before):
                        np.testing.assert_array_equal(before[name], after[group][name])
                        digest.update(before[name].tobytes())
        assert [r.reason for r in restored.reports(loaded)] == [
            json.loads(raw)["reason"] for raw in result.reports_json
        ]
        return dict(sha256=digest.hexdigest(), asset_roundtrip=True)
    finally:
        assert scope.close() == () and restored_runtime.budget.used == 0


def test_full_input_and_complete_steel_support(tmp_path, request):
    """读完并核验完整源文件，用既有工程搜索 ROI，不使用显示采样。"""
    sample = request.config.getoption("--cloud-sample")
    if not sample:
        pytest.skip("完整样本必须显式提供")
    binary = tmp_path / "input.bin"
    descriptor = sample_array(Path(sample), binary)
    points = np.memmap(binary, mode="r", shape=(descriptor.point_count, 3), dtype="<f4")
    scope, runtime, source = make_cloud(
        unit="mm",
        coordinates=points,
        runtime_policy=policy(
            max_working_bytes=4 * 1024**3,
            max_live_array_bytes=1024**3,
            chunk_rows=65536,
        ),
    )
    try:
        bounds = STEEL["A_top_L"][3]
        selected, _ = crop_roi(
            runtime,
            source,
            boxes("edge-steel", [[*bounds, -30, 0]]),
            cancel=lambda: None,
        )
        # 原配方搜索窗只决定有限支持；此格距和质量为一次显式工程诊断配置。
        raw = parameters("median").model_dump()
        raw.update(width=40, height=44)
        raw["grid"].update(origin=(-38, -24, 0), column_step=0.25, row_step=0.25)
        grid = HeightMapParameters.model_validate(raw)
        result = cloud_to_height_map(runtime, selected, grid, cancel=lambda: None)
        assert result.outside_count == 0
        ref = publish_height_map(runtime, result)
        settings = HeightJumpCandidateSettings.model_validate(
            dict(
                kind="height-jump",
                adjacency=4,
                candidate_delta=0.2,
                support_a=boxes("lower-band", [[*bounds, -16.5, -15.4]]),
                support_b=boxes("upper-band", [[*bounds, -15.2, -14.0]]),
                max_unassigned_fraction=0.4,
                support=dict(
                    radius=0.5,
                    min_points=20,
                    min_tangent_ratio=0.1,
                    min_normal_gap=0.1,
                    max_rms=0.05,
                    max_residual=0.15,
                    min_joint_rms=0.08,
                ),
                min_height_axis_cosine=0.5,
            )
        )
        baseline = runtime.budget.used
        started = perf_counter()
        candidates = height_jump_candidates(
            runtime, selected, ref, settings, cancel=lambda: None
        )
        seconds = perf_counter() - started
        with runtime.borrow(selected) as view:
            actual = np.concatenate(
                [
                    view.chunk(start, min(start + 65536, selected.point_count))[
                        "positions"
                    ]
                    for start in range(0, selected.point_count, 65536)
                ]
            )
            source_rows = np.concatenate(
                [
                    view.source_indices(start, min(start + 65536, selected.point_count))
                    for start in range(0, selected.point_count, 65536)
                ]
            )
        np.testing.assert_array_equal(actual, points[source_rows])
        assert runtime.source_point_count(selected) == len(points)
        reasons = Counter()
        with candidates.borrow(runtime) as data:
            assert candidates.candidate_count > 0
            for index in range(candidates.candidate_count):
                item = pair_evidence(data, index)
                reasons[item.reason or "supported"] += 1
                # 与被测格成员/窗口实现无关，直接比较完整 ROI 的物理圆窗口。
                first, second = item.cells
                r1, c1 = divmod(first, grid.width)
                r2, c2 = divmod(second, grid.width)
                center = np.array([-38 + (c1 + c2) * 0.125, -24 + (r1 + r2) * 0.125])
                delta = actual[:, :2].astype(float) - center
                inside = np.sqrt((delta * delta).sum(axis=1)) <= 0.5
                left = (actual[:, 2] >= -16.5) & (actual[:, 2] <= -15.4)
                right = (actual[:, 2] >= -15.2) & (actual[:, 2] <= -14.0)
                assert item.side_counts == (
                    int((inside & left).sum()),
                    int((inside & right).sum()),
                )
                assert item.unassigned_count == int((inside & ~(left | right)).sum())
                assert item.overlap_count == 0
            digest = sha256(
                data["cells"].tobytes()
                + data["counts"].tobytes()
                + data["reason"].tobytes()
            ).hexdigest()
        record = dict(
            source_count=len(points),
            support_count=selected.point_count,
            candidates=candidates.candidate_count,
            supported=candidates.supported_count,
            missing_pairs=candidates.missing_pair_count,
            reasons=dict(reasons),
            identity_sha256=digest,
            seconds=seconds,
            settings=settings.model_dump(mode="json"),
        )
        # 与双侧支持半径一致的有限诊断范围，不写入正式工件配方或节点默认。
        pairing = HeightJumpPairingSettings(max_planar_gap=0.5, tie_tolerance=1e-9)
        chain_settings = EdgeChainSettings(
            side="high", max_link_distance=0.5, max_turn_angle=np.pi / 4
        )
        started = perf_counter()
        pairs = pair_height_candidates(
            runtime, selected, candidates, pairing, cancel=lambda: None
        )
        pair_seconds = perf_counter() - started
        with pairs.borrow(runtime) as data:
            statuses = Counter(PairStatus(int(v)).name for v in data["status"][:, 0])
            logical = data["input_rows"][:, 0]
            np.testing.assert_array_equal(
                data["source_rows"][:, 0], source_rows[logical]
            )
            np.testing.assert_allclose(
                data["positions"],
                actual[logical].astype(float) - (-38, -24, 0),
                rtol=0,
                atol=1e-12,
            )
            assert pairs.pair_count * 2 == statuses["PAIRED"]
            # 与 KDTree 无关的全距离直接对照；两侧计数/所有记录均保留。
            for first, last in zip(data["offsets"][:-1, 0], data["offsets"][1:, 0]):
                first, last = int(first), int(last)
                for row in range(first, last):
                    if data["status"][row, 0] != PairStatus.PAIRED:
                        continue
                    other = int(data["partners"][row, 0])
                    assert first <= other < last and data["partners"][other, 0] == row
                    side = int(data["sides"][row, 0])
                    opposite = (
                        np.flatnonzero(data["sides"][first:last, 0] == 1 - side) + first
                    )
                    d = data["positions"][opposite] - data["positions"][row]
                    gap = np.sqrt((d[:, :2] ** 2).sum(axis=1))
                    ordered = np.argsort(gap)
                    assert opposite[ordered[0]] == other
                    assert (
                        len(gap) == 1
                        or gap[ordered[1]] - gap[ordered[0]] > pairing.tie_tolerance
                    )
                    delta = data["positions"][other] - data["positions"][row]
                    np.testing.assert_allclose(
                        data["metrics"][row],
                        (gap[ordered[0]], np.linalg.norm(delta), delta[2]),
                        rtol=1e-12,
                        atol=1e-12,
                    )
            pair_digest = sha256(
                data["input_rows"].tobytes()
                + data["source_rows"].tobytes()
                + data["status"].tobytes()
                + data["partners"].tobytes()
            ).hexdigest()
        started = perf_counter()
        chains = build_edge_chains(runtime, pairs, chain_settings, cancel=lambda: None)
        chain_seconds = perf_counter() - started
        with chains.borrow(runtime) as data:
            np.testing.assert_array_equal(
                data["source_rows"][:, 0], source_rows[data["input_rows"][:, 0]]
            )
            chain_digest = sha256(
                data["source_rows"].tobytes()
                + data["edges"].tobytes()
                + data["segment_rows"].tobytes()
            ).hexdigest()
            record.update(
                pair_count=pairs.pair_count,
                pair_statuses=dict(statuses),
                pair_identity_sha256=pair_digest,
                pair_seconds=pair_seconds,
                pairing=pairing.model_dump(mode="json"),
                chain_settings=chain_settings.model_dump(mode="json"),
                chain_reason=chains.reason,
                chain_points=len(data["positions"]),
                chain_edges=len(data["edges"]),
                chain_segments=len(data["closed"]),
                chain_isolated=len(data["isolated"]),
                chain_identity_sha256=chain_digest,
                chain_seconds=chain_seconds,
            )
        target_parameters = EdgeTargetSelection.model_validate(
            dict(
                targets=[
                    dict(
                        segment_id=name,
                        region=boxes(
                            name, [[bounds[0], bounds[1], y0, y1, -15.2, -14.0]]
                        ),
                        closed=False,
                        role="open",
                    )
                    for name, y0, y1 in (
                        ("upper-half", bounds[2], (bounds[2] + bounds[3]) / 2),
                        ("lower-half", (bounds[2] + bounds[3]) / 2, bounds[3]),
                    )
                ],
                min_projected_area=1e-6,
                quality_policy=dict(
                    policy_id="diagnostic-edge",
                    policy_version=1,
                    rules=[
                        dict(item_id="support_count", unit="1", lower=3),
                        dict(item_id="length", unit="mm", lower=0.1),
                        dict(item_id="max_planar_gap", unit="mm", upper=0.5),
                    ],
                ),
            )
        )
        targets = select_edge_targets(
            runtime, chains, target_parameters, cancel=lambda: None
        )
        target_reports = [json.loads(raw) for raw in targets.reports_json]
        assert [r["target_id"] for r in target_reports] == ["upper-half", "lower-half"]
        with targets.borrow(runtime) as target_data:
            np.testing.assert_array_equal(
                target_data["source_rows"][:, 0],
                source_rows[target_data["input_rows"][:, 0]],
            )
        record.update(
            targets=target_reports,
            target_parameters=target_parameters.model_dump(mode="json"),
        )
        record["height_edge_asset"] = verify_edge_asset(
            runtime, selected, targets, result, tmp_path / "height-assets"
        )
        runtime.storage_scope.close_resource(targets.resource_key)
        runtime.storage_scope.close_resource(chains.resource_key)
        runtime.storage_scope.close_resource(pairs.resource_key)
        runtime.storage_scope.close_resource(candidates.resource_key)
        assert runtime.budget.used == baseline
        # 全部 ROI 实测点参与 B03，沿用既有工程法向限值，候选仍只是诊断。
        normal_cloud, normal_summary = estimate_normals(
            runtime,
            selected,
            sample_parameters(frame_id=selected.spatial.frame_id),
            cancel=lambda: None,
        )
        crease_settings = NormalCreaseSettings(
            kind="normal-crease",
            radius=0.3,
            max_neighbors=256,
            min_angle=0.35,
            support=settings.support,
            support_a=settings.support_a,
            support_b=settings.support_b,
            max_unassigned_fraction=settings.max_unassigned_fraction,
            max_pair_distance=0.25,
        )
        started = perf_counter()
        crease = normal_crease_candidates(
            runtime, normal_cloud, crease_settings, cancel=lambda: None
        )
        crease_seconds = perf_counter() - started
        with crease.borrow(runtime) as data:
            np.testing.assert_array_equal(data["source_rows"][:, 0], source_rows)
            assert len(data["status"]) == selected.point_count
            for row in np.linspace(0, len(actual) - 1, 9, dtype=int):
                distance = np.linalg.norm(
                    actual.astype(float) - actual[row].astype(float), axis=1
                )
                assert data["neighbors"][row, 0] == np.count_nonzero(
                    distance <= crease_settings.radius
                )
            normal_record = dict(
                candidate_count=crease.candidate_count,
                supported_count=crease.supported_count,
                status_counts=dict(
                    Counter(
                        NormalNeighborhoodStatus(int(v)).name
                        for v in data["status"][:, 0]
                    )
                ),
                support_reasons=dict(
                    Counter(
                        SUPPORT_REASONS[int(v)] or "supported"
                        for v in data["reason"][:, 0]
                    )
                ),
                identity_sha256=sha256(
                    data["source_rows"].tobytes()
                    + data["pairs"].tobytes()
                    + data["status"].tobytes()
                    + data["reason"].tobytes()
                ).hexdigest(),
                seconds=crease_seconds,
                settings=crease_settings.model_dump(mode="json"),
                normals=normal_summary,
            )
        normal_options = NormalEdgeSettings(
            side="b",
            tie_tolerance=1e-9,
            max_link_distance=0.25,
            max_turn_angle=np.pi / 4,
        )
        started = perf_counter()
        normal_pairs = pair_normal_candidates(
            runtime, crease, normal_options, cancel=lambda: None
        )
        normal_chains = build_normal_edge_chains(
            runtime, normal_pairs, cancel=lambda: None
        )
        normal_targets_raw = target_parameters.model_dump()
        normal_targets_raw["quality_policy"]["rules"][2]["item_id"] = (
            "max_pair_distance"
        )
        normal_targets = select_edge_targets(
            runtime,
            normal_chains,
            EdgeTargetSelection.model_validate(normal_targets_raw),
            evaluation=height_evaluation(ref),
            cancel=lambda: None,
        )
        with normal_pairs.borrow(runtime) as data:
            np.testing.assert_array_equal(data["source_rows"][:, 0], source_rows)
            np.testing.assert_array_equal(data["positions"], actual.astype(float))
            assert len(data["status"]) == len(actual)
            normal_record.update(
                paired_count=normal_pairs.pair_count,
                pair_statuses=dict(
                    Counter(PairStatus(int(v)).name for v in data["status"][:, 0])
                ),
                pair_identity_sha256=sha256(
                    data["source_rows"].tobytes()
                    + data["status"].tobytes()
                    + data["reason_bits"].tobytes()
                    + data["partners"].tobytes()
                ).hexdigest(),
                targets=[json.loads(s) for s in normal_targets.reports_json],
                pair_chain_target_seconds=perf_counter() - started,
            )
        normal_record["edge_asset"] = verify_edge_asset(
            runtime, normal_cloud, normal_targets, None, tmp_path / "normal-assets"
        )
        for resource in (normal_targets, normal_chains, normal_pairs, crease):
            runtime.storage_scope.close_resource(resource.resource_key)
        record["normal_candidates"] = normal_record
        from backend.contracts.workflows.edge3d import SamplingBoundarySettings
        from custom_nodes.metrology3d_nodes.shared.edge_sampling import (
            sampling_candidates,
        )
        from custom_nodes.metrology3d_nodes.shared.edge_sampling_context import (
            sampling_context,
        )

        sampling_settings = SamplingBoundarySettings(
            kind="sampling-boundary",
            radius=0.3,
            max_neighbors=256,
            min_neighbors=3,
            angle_degrees=120,
        )
        sampling_baseline = runtime.budget.used
        sampling = sampling_candidates(
            runtime, normal_cloud, sampling_settings, cancel=lambda: None
        )
        diagnostic = sampling_context(runtime, sampling, cancel=lambda: None)
        with diagnostic.borrow(runtime) as (data, facts):
            np.testing.assert_array_equal(data["identity_rows"][:, 0], source_rows)
            assert len(data["candidate"]) == len(actual)
            assert not data["candidate"][data["status"] != 0].any()
            assert np.all(facts["context"][data["candidate"] == 0] == 0)
            record["sampling"] = dict(
                candidate_count=sampling.candidate_count,
                status_counts=dict(Counter(map(int, data["status"][:, 0]))),
                context_counts=dict(Counter(map(int, facts["context"][:, 0]))),
                sha256=sha256(
                    data["candidate"].tobytes()
                    + data["status"].tobytes()
                    + facts["context"].tobytes()
                ).hexdigest(),
                settings=sampling_settings.model_dump(mode="json"),
            )
        from backend.service.application.runtime.resource_scope import ResourceScope
        from backend.service.application.workflows.point_cloud.runtime import (
            get_cloud_runtime,
        )
        from backend.service.application.workflows.documents.cloud_resource_blobs import (
            CloudAssetPolicy,
        )
        from custom_nodes.metrology3d_nodes.shared.cloud_assets import (
            save_cloud,
            read_asset,
        )
        from custom_nodes.metrology3d_nodes.shared.edge_sampling_assets import (
            read_sampling,
        )
        from tests.point_cloud_support import create_resource_service

        service = create_resource_service(tmp_path / "sampling-assets")
        limits = CloudAssetPolicy(
            max_asset_bytes=128 * 1024**2,
            max_archive_bytes=129 * 1024**2,
            chunk_bytes=65536,
        )
        asset = save_cloud(
            runtime,
            normal_cloud,
            sampling=diagnostic,
            service=service,
            project_id="test",
            name="full-sample-diagnostic",
            mode="derived",
            write_identity="9" * 64,
            policy=limits,
            cancel=lambda: None,
        )
        restored_scope = ResourceScope(kind="full-sampling-restore")
        restored_runtime = get_cloud_runtime(
            restored_scope,
            run_id="restored-sampling",
            policy=runtime.policy.model_copy(
                update={"max_decoded_bytes": limits.max_asset_bytes}
            ),
        )
        try:
            loaded = read_asset(
                restored_runtime,
                asset,
                service=service,
                project_id="test",
                policy=limits,
                cancel=lambda: None,
            )
            restored = read_sampling(
                restored_runtime,
                loaded,
                document=service.read(asset, project_id="test"),
                service=service,
                project_id="test",
                policy=limits,
                cancel=lambda: None,
            )
            with (
                diagnostic.borrow(runtime) as (before, before_facts),
                restored.borrow(restored_runtime) as (after, after_facts),
            ):
                for name, array in {**before, **before_facts}.items():
                    np.testing.assert_array_equal(array, {**after, **after_facts}[name])
            record["sampling"]["asset_roundtrip"] = True
        finally:
            assert restored_scope.close() == () and restored_runtime.budget.used == 0
        runtime.storage_scope.close_resource(diagnostic.resource_key)
        runtime.storage_scope.close_resource(sampling.resource_key)
        assert runtime.budget.used == sampling_baseline
        report = request.config.getoption("--cloud-report-dir")
        if report:
            destination = Path(report)
            destination.mkdir(parents=True, exist_ok=True)
            (destination / "b09-height-candidates.json").write_text(
                json.dumps(record, indent=2), encoding="utf-8"
            )
    finally:
        assert scope.close() == ()
        del points
    assert runtime.budget.used == 0
