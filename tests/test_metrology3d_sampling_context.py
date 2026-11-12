"""采样来源分类使用真实父链，不把未知空白判为缺陷。"""

from io import BytesIO

import numpy as np
import pytest

from backend.contracts.workflows.point_cloud_runtime import FilterCloudValid
from backend.service.application.errors import InvalidRequestError
from custom_nodes.metrology3d_nodes.shared.edge_sampling import sampling_candidates
from custom_nodes.metrology3d_nodes.shared.edge_sampling_context import (
    sampling_context,
    SamplingContext,
    _observations,
)
from custom_nodes.metrology3d_nodes.shared.crop_roi import crop_roi
from custom_nodes.metrology3d_nodes.shared.estimate_normals import estimate_normals
from custom_nodes.metrology3d_nodes.shared.filter_valid import filter_valid
from tests.test_metrology3d_sampling import prepare
from tests.test_metrology3d_normal_estimation import parameters
from tests.integration.metrology3d.representative_recipe import boxes


def test_plain_cloud_unknown_and_crop_requires_actual_excluded_points():
    scope, runtime, _, cloud, settings, _ = prepare()
    try:
        candidates = sampling_candidates(runtime, cloud, settings, cancel=lambda: None)
        diagnostic = sampling_context(runtime, candidates, cancel=lambda: None)
        with diagnostic.borrow(runtime) as (data, context):
            hit = data["candidate"][:, 0] == 1
            assert np.all(context["context"][hit, 0] == SamplingContext.UNKNOWN)
        cropped, _ = crop_roi(
            runtime, cloud, boxes("sample", [[1, 5, 0, 6, -1, 1]]), cancel=lambda: None
        )
        candidates = sampling_candidates(
            runtime, cropped, settings, cancel=lambda: None
        )
        diagnostic = sampling_context(runtime, candidates, cancel=lambda: None)
        with (
            diagnostic.borrow(runtime) as (data, context),
            runtime.borrow(cropped) as view,
        ):
            xyz = view.chunk(0, cropped.point_count)["positions"]
            selected = data["candidate"][:, 0] == 1
            cut = (xyz[:, 0] == 1) | (xyz[:, 0] == 5)
            assert np.all(
                context["context"][cut & selected, 0] == SamplingContext.ROI_CUT
            )
            assert np.all(
                context["context"][~cut & selected, 0] == SamplingContext.UNKNOWN
            )
    finally:
        assert scope.close() == ()


def test_invalid_finite_parent_points_rejected_before_crop_diagnostic():
    """既有 ROI 输入边界阻止无效记录进入裁剪，不制造虚假裁剪事实。"""
    from tests.test_metrology3d_preprocess import make_cloud
    from tests.point_cloud_support import policy

    scope, runtime, original = make_cloud(
        unit="mm",
        coordinates=np.array([[0.0, 0, 0], [1.0, 0, 0], [2.0, 0, 0]]),
        attributes=[("validity", np.array([0, 1, 1], dtype="uint8"), "1")],
        runtime_policy=policy(max_working_bytes=8_000_000),
    )
    try:
        baseline = runtime.budget.used
        with pytest.raises(InvalidRequestError, match="Filter Valid"):
            crop_roi(
                runtime,
                original,
                boxes("sample", [[0.5, 3, -1, 1, -1, 1]]),
                cancel=lambda: None,
            )
        assert runtime.budget.used == baseline
    finally:
        assert scope.close() == ()


def test_original_raster_invalid_observation_and_acquisition_limits(tmp_path):
    from tests.test_metrology3d_raster_conversion import specification
    from tests.point_cloud_support import create_resource_service
    from tests.integration.metrology3d.test_file_read import publish
    from custom_nodes.metrology3d_nodes.shared.io.read_raster import (
        read_raster_reference,
    )

    scope, runtime, _, _, settings, _ = prepare()
    try:
        service = create_resource_service(tmp_path)
        samples = np.ones((7, 7), dtype="float32")
        samples[3, 3] = np.nan
        stream = BytesIO()
        np.save(stream, samples, allow_pickle=False)
        spec = specification(
            width=7,
            height=7,
            projection=dict(
                kind="rectified-pinhole", depth_kind="axial-z", fx=1, fy=1, cx=0, cy=0
            ),
        )
        original, _ = read_raster_reference(
            runtime=runtime,
            object_store=service.storage,
            project_id="test",
            file=publish(service.storage, stream.getvalue()),
            file_format="npy",
            spec=spec,
            cancel=lambda: None,
        )
        filtered, _ = filter_valid(
            runtime,
            original,
            FilterCloudValid(finite_fields=["positions"], sentinels=[]),
            cancel=lambda: None,
        )
        cloud, _ = estimate_normals(
            runtime,
            filtered,
            parameters(
                "radius",
                neighborhood=dict(kind="radius", radius=1.8),
                frame_id=original.spatial.frame_id,
            ),
            cancel=lambda: None,
        )
        candidates = sampling_candidates(runtime, cloud, settings, cancel=lambda: None)
        diagnostic = sampling_context(runtime, candidates, cancel=lambda: None)
        with diagnostic.borrow(runtime) as (data, context):
            for index, source in enumerate(data["identity_rows"][:, 0]):
                if data["candidate"][index, 0]:
                    row, column = divmod(int(source), 7)
                    flag = int(context["context"][index, 0])
                    if abs(row - 3) + abs(column - 3) == 1:
                        assert flag & SamplingContext.INVALID_OBSERVATION
                    if row in (0, 6) or column in (0, 6):
                        assert flag & SamplingContext.ACQUISITION_LIMIT
        assert runtime.source_point_count(cloud) == 49
    finally:
        assert scope.close() == ()


def test_profile_missing_rows_and_invalid_records_are_separate(tmp_path):
    from tests.test_metrology3d_profile_runtime import source
    from tests.point_cloud_support import create_resource_service

    scope, runtime, _, _, _, _ = prepare()
    try:
        result = source(
            runtime,
            create_resource_service(tmp_path),
            method="fixed-step",
            invalid=True,
        )
        cloud = result[0] if isinstance(result, tuple) else result
        flags = np.zeros(6, dtype="u1")
        _observations(
            runtime,
            cloud,
            np.arange(6),
            flags,
            available=4_000_000,
            cancel=lambda: None,
        )
        assert flags[1] & SamplingContext.INVALID_OBSERVATION
        assert flags[1] & SamplingContext.MISSING_ACQUISITION_ROW
        assert flags[2] & SamplingContext.MISSING_ACQUISITION_ROW
    finally:
        assert scope.close() == ()


def test_context_cancellation_and_released_parent(monkeypatch):
    from custom_nodes.metrology3d_nodes.shared import edge_sampling_context as module

    scope, runtime, _, cloud, settings, _ = prepare()
    try:
        candidates = sampling_candidates(runtime, cloud, settings, cancel=lambda: None)
        baseline = runtime.budget.used
        original, registered = module.own_output, False

        def own(*args):
            nonlocal registered
            result = original(*args)
            registered = True
            return result

        def cancel():
            if registered:
                raise InterruptedError("context-after-register")

        monkeypatch.setattr(module, "own_output", own)
        with pytest.raises(InterruptedError):
            sampling_context(runtime, candidates, cancel=cancel)
        assert runtime.budget.used == baseline
        diagnostic = sampling_context(runtime, candidates, cancel=lambda: None)
        runtime.storage_scope.close_resource(candidates.resource_key)
        with pytest.raises(InvalidRequestError):
            with diagnostic.borrow(runtime):
                pass
    finally:
        assert scope.close() == ()
