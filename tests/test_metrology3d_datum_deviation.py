"""B17 全目标偏差独立真值、失败传播、预算与 Scope 验证。"""

from math import fsum, sqrt

import numpy as np
import pytest
from pydantic import ValidationError

from backend.contracts.workflows.deviation3d import (
    COMPONENTS,
    DeviationParameters,
    DeviationSummary,
)
from backend.service.application.errors import InvalidRequestError
from custom_nodes.metrology3d_nodes.shared.datum_deviation import (
    deviation_row_bytes,
    measure_datum_deviation as run_deviation,
)
from custom_nodes.metrology3d_nodes.shared.deviation_statistics import (
    deviation_statistics,
)
from custom_nodes.metrology3d_nodes.shared.deviation_rows import validate_deviation_rows
from tests.test_metrology3d_height_step import two_planes as _two_planes
from tests.test_metrology3d_measurement_contracts import measurement_policy


def measure_datum_deviation(*args, **kwargs):
    """原逐点证据回归明确开启捕获；默认路径在下方独立核对。"""
    return run_deviation(*args, capture_details=True, **kwargs)


def assert_default_matches(runtime, captured, groups):
    """同一失败场景关闭捕获后不丢失原因、统计或无效输出。"""
    baseline = runtime.budget.used
    normal = run_deviation(
        runtime,
        captured.target,
        groups,
        captured.summary.parameters,
        cancel=lambda: None,
    )
    assert normal.summary == captured.summary
    assert normal.summary.numeric_table() == captured.summary.numeric_table()
    assert normal.owner is None and normal.resource_key is None
    assert runtime.budget.used == baseline


def two_planes(**kwargs):
    """完整逐点证据同时持有输出和索引，显式扩大测试数组预算。"""
    result = _two_planes(**kwargs)
    runtime = result[1]
    runtime.policy = runtime.policy.model_copy(
        update=dict(max_live_array_bytes=1024**2)
    )
    runtime.budget.limit = 1024**2
    return result


def parameters(**changes):
    """只用于解析真值的显式配置，不成为节点生产默认值。"""
    data = dict(
        reference_feature_id="reference",
        frame_id="fixture",
        length_unit="mm",
        support_radius=2,
        reference_policy=dict(kind="measured-support"),
        quality_policy={
            **measurement_policy(),
            "rules": [
                r
                for r in measurement_policy()["rules"]
                if r["item_id"].startswith("reference_")
            ],
        },
        outputs=[dict(component=c, item_id=f"test-{c}") for c in COMPONENTS],
    )
    data.update(changes)
    return DeviationParameters.model_validate(data)


@pytest.mark.parametrize("dtype", [np.float32, np.float64])
@pytest.mark.parametrize("slope", [0, 0.25])
def test_complete_target_statistics_and_original_rows(dtype, slope):
    scope, runtime, _, _, target, groups = two_planes(dtype=dtype, slope=slope)
    baseline = runtime.budget.used
    try:
        result = measure_datum_deviation(
            runtime, target, groups[:1], parameters(), cancel=lambda: None
        )
        assert result.summary.valid
        expected = np.array([5 + slope * x for x in (-1, 0, 1) for _ in range(3)])
        stats = result.summary.diagnostic
        assert stats.count == 9
        assert stats.minimum == pytest.approx(min(expected))
        assert stats.maximum == pytest.approx(max(expected))
        assert stats.peak_to_valley == pytest.approx(2 * slope)
        assert stats.mean == pytest.approx(fsum(expected) / 9)
        assert stats.rms == pytest.approx(sqrt(fsum(v * v for v in expected) / 9))
        assert stats.minimum_source.source_index == 9
        assert stats.minimum_source.tie_count == (9 if not slope else 3)
        assert all(v.valid for v in result.summary.numeric_table().items)
        assert (
            DeviationSummary.model_validate_json(result.summary.model_dump_json())
            == result.summary
        )
        with result.borrow(runtime) as arrays:
            validate_deviation_rows(
                arrays, result.summary, chunk_rows=2, cancel=lambda: None
            )
            np.testing.assert_array_equal(
                arrays["source_index"][:, 0], np.arange(9, 18)
            )
            np.testing.assert_allclose(
                arrays["deviation"][:, 0], expected, rtol=0, atol=1e-12
            )
            assert all(not a.flags.writeable for a in arrays.values())
        assert (
            runtime.budget.used == baseline + target.point_count * deviation_row_bytes()
        )
        runtime.storage_scope.close_resource(result.resource_key)
        assert runtime.budget.used == baseline
        with pytest.raises(InvalidRequestError):
            with result.borrow(runtime):
                pass
    finally:
        assert not scope.close()
        assert runtime.budget.used == 0


def test_failed_support_keeps_all_diagnostic_values_and_nulls_all_outputs():
    scope, runtime, _, _, target, groups = two_planes(slope=0.25)
    try:
        result = measure_datum_deviation(
            runtime,
            target,
            groups[:1],
            parameters(support_radius=0.01),
            cancel=lambda: None,
        )
        assert not result.summary.valid
        assert result.summary.counts.failed == 9
        assert result.summary.diagnostic.count == 9
        assert result.summary.diagnostic.mean == pytest.approx(5)
        assert result.summary.diagnostic_only
        assert all(
            not i.valid and i.value is None
            for i in result.summary.numeric_table().items
        )
    finally:
        assert not scope.close()


@pytest.mark.parametrize(
    "change",
    [
        dict(outputs=[dict(component="min", item_id=str(i)) for i in range(5)]),
        dict(outputs=[dict(component=c, item_id="same") for c in COMPONENTS]),
        dict(support_radius=0),
        dict(quality_policy=dict(rules=[])),
    ],
)
def test_parameters_reject_incomplete_or_ambiguous_contract(change):
    with pytest.raises(ValidationError):
        parameters(**change)


@pytest.mark.parametrize("chunk_rows", [1, 2, 10])
def test_statistics_keep_zero_signed_values_and_ties(chunk_rows):
    values = np.array([2.0, -3.0, np.nan, 2.0, -3.0, 0.0])
    arrays = dict(
        deviation=values[:, None],
        source_index=np.array([8, 7, 6, 2, 1, 9], dtype=np.uint64)[:, None],
    )
    stats = deviation_statistics(arrays, chunk_rows=chunk_rows, cancel=lambda: None)
    assert stats.count == 5
    assert stats.mean == pytest.approx(-0.4)
    assert stats.rms == pytest.approx(sqrt(26 / 5))
    assert stats.minimum_source.source_index == 1
    assert stats.minimum_source.logical_index == 4
    assert stats.minimum_source.tie_count == 2
    assert stats.maximum_source.source_index == 2
    assert stats.maximum_source.tie_count == 2


@pytest.mark.parametrize("value", [0.0, 1e200, -1e200])
def test_constant_statistics_do_not_overflow_or_use_standard_deviation(value):
    arrays = dict(
        deviation=np.full((5, 1), value),
        source_index=np.arange(5, dtype=np.uint64)[:, None],
    )
    stats = deviation_statistics(arrays, chunk_rows=2, cancel=lambda: None)
    assert stats.mean == value
    assert stats.rms == abs(value)
    assert stats.peak_to_valley == 0


@pytest.mark.parametrize("stop", [1, 5, 20, 40, 80, 120])
def test_cancellation_returns_owned_budget(stop):
    scope, runtime, _, _, target, groups = two_planes()
    baseline = runtime.budget.used
    calls = 0

    def cancel():
        nonlocal calls
        calls += 1
        if calls == stop:
            raise InterruptedError("explicit test cancellation")

    try:
        with pytest.raises(InterruptedError):
            measure_datum_deviation(
                runtime, target, groups[:1], parameters(), cancel=cancel
            )
        assert runtime.budget.used == baseline
        with runtime.borrow(target) as view:
            assert len(view.chunk(0, 1)["positions"]) == 1
    finally:
        assert not scope.close()
        assert runtime.budget.used == 0


def test_working_budget_rejects_combined_output_index_and_scratch():
    scope, runtime, _, _, target, groups = two_planes()
    baseline = runtime.budget.used
    runtime.policy = runtime.policy.model_copy(update=dict(max_working_bytes=5000))
    try:
        with pytest.raises(InvalidRequestError):
            measure_datum_deviation(
                runtime, target, groups[:1], parameters(), cancel=lambda: None
            )
        assert runtime.budget.used == baseline
    finally:
        assert not scope.close()


@pytest.mark.parametrize("limit", [1.0, 2.0])
@pytest.mark.parametrize("reverse", [False, True])
def test_finite_extension_partial_failure_preserves_full_statistics(limit, reverse):
    from tests.test_metrology3d_reference_extension import offset_planes

    angle = np.pi / 6
    rotation = np.array(
        [
            [np.cos(angle), 0, np.sin(angle)],
            [0, 1, 0],
            [-np.sin(angle), 0, np.cos(angle)],
        ]
    )
    scope, runtime, _, groups = offset_planes(
        reverse=reverse, transform=(rotation, np.array([17.0, -23.0, 31.0]))
    )
    runtime.budget.limit = 1024**2
    try:
        result = measure_datum_deviation(
            runtime,
            groups[1].items[0].support,
            groups[:1],
            parameters(
                support_radius=0.25,
                reference_policy=dict(
                    kind="plane-extension", max_extension_distance=limit
                ),
            ),
            cancel=lambda: None,
        )
        assert result.summary.valid == (limit == 2.0)
        assert_default_matches(runtime, result, groups[:1])
        assert result.summary.diagnostic.count == 9
        assert result.summary.diagnostic.mean == pytest.approx(-5 if reverse else 5)
        if limit == 1.0:
            assert 0 < result.summary.counts.failed < 9
            assert all(i.value is None for i in result.summary.numeric_table().items)
        with result.borrow(runtime) as arrays:
            validate_deviation_rows(
                arrays, result.summary, chunk_rows=2, cancel=lambda: None
            )
            expected = [
                np.hypot(x + 1, y) for x in (-0.1, 0, 0.1) for y in (-0.1, 0, 0.1)
            ]
            np.testing.assert_allclose(
                arrays["extension_distance"][:, 0], expected, atol=1e-12
            )
    finally:
        assert not scope.close()
        assert runtime.budget.used == 0


def test_covered_quality_failure_cannot_escape_through_extension():
    scope, runtime, _, _, target, groups = two_planes()
    try:
        quality = parameters().quality_policy.model_dump()
        for rule in quality["rules"]:
            if rule["item_id"] == "reference_triangle_edge":
                rule["upper"] = 0.5
        result = measure_datum_deviation(
            runtime,
            target,
            groups[:1],
            parameters(
                quality_policy=quality,
                reference_policy=dict(
                    kind="plane-extension", max_extension_distance=100
                ),
            ),
            cancel=lambda: None,
        )
        assert not result.summary.valid
        assert result.summary.counts.support_quality_failed == 9
        assert_default_matches(runtime, result, groups[:1])
        assert result.summary.counts.extended == 0
        with result.borrow(runtime) as arrays:
            validate_deviation_rows(
                arrays, result.summary, chunk_rows=2, cancel=lambda: None
            )
    finally:
        assert not scope.close()


def test_nonfinite_and_explicit_invalid_observations_are_not_silently_filtered():
    from tests.test_metrology3d_preprocess import make_cloud
    from tests.point_cloud_support import policy
    from tests.test_metrology3d_plane import plane_parameters
    from tests.test_metrology3d_height_step import roi
    from custom_nodes.metrology3d_nodes.shared.fit_plane import fit_plane
    from custom_nodes.metrology3d_nodes.shared.filter_valid import filter_valid
    from backend.contracts.workflows.point_cloud_runtime import FilterCloudValid

    xyz = np.array(
        [(x, y, 0) for x in (-1, 0, 1) for y in (-1, 0, 1)]
        + [(0, 0, 5), (np.nan, 0, 5), (0, 0, 6)],
        dtype=np.float64,
    )
    scope, runtime, cloud = make_cloud(
        unit="mm",
        coordinates=xyz,
        attributes=[("validity", np.array([1] * 11 + [0], dtype=np.uint8), "1")],
        runtime_policy=policy(max_working_bytes=1024**2, max_live_array_bytes=1024**2),
    )
    try:
        filtered, _ = filter_valid(
            runtime,
            cloud,
            FilterCloudValid(finite_fields=["positions"], sentinels=[]),
            cancel=lambda: None,
        )
        group = fit_plane(
            runtime,
            roi(runtime, filtered, 0),
            plane_parameters(feature_id="reference"),
            cancel=lambda: None,
        )
        result = measure_datum_deviation(
            runtime, cloud, [group], parameters(), cancel=lambda: None
        )
        assert result.summary.target_count == 12
        assert result.summary.counts.invalid_target == 2
        assert_default_matches(runtime, result, [group])
        assert result.summary.diagnostic.count == 10
        assert result.summary.diagnostic.mean == pytest.approx(0.5)
        assert not result.summary.valid
        from custom_nodes.metrology3d_nodes.shared.deviation_result import (
            deviation_evidence,
        )

        public = deviation_evidence(
            runtime, cloud, [group], parameters(), cancel=lambda: None
        )
        assert len(public.items) == 5 and all(not item.valid for item in public.items)
        assert public.items[0].support[1].bounds is None
        assert public.items[0].summary.counts.invalid_target == 2
        assert public.items[0].summary.diagnostic.count == 10
        with result.borrow(runtime) as arrays:
            np.testing.assert_array_equal(arrays["source_index"][:, 0], np.arange(12))
            assert np.isnan(arrays["deviation"][-2:]).all()
            validate_deviation_rows(
                arrays, result.summary, chunk_rows=3, cancel=lambda: None
            )
    finally:
        assert not scope.close()


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_index", 500),
        ("status", 255),
        ("deviation", 100.0),
        ("failed_checks", 128),
        ("triangle_source_indices", 500),
        ("triangle", np.nan),
        ("nearest_support_point", 0.0),
    ],
)
def test_binary_evidence_rejects_tampering(field, value):
    scope, runtime, _, _, target, groups = two_planes()
    try:
        result = measure_datum_deviation(
            runtime, target, groups[:1], parameters(), cancel=lambda: None
        )
        with result.borrow(runtime) as arrays:
            altered = {key: a.copy() for key, a in arrays.items()}
        altered[field][0] = value
        with pytest.raises(InvalidRequestError):
            validate_deviation_rows(
                altered, result.summary, chunk_rows=2, cancel=lambda: None
            )
    finally:
        assert not scope.close()


@pytest.mark.parametrize(
    "change",
    [
        dict(frame_id="other"),
        dict(length_unit="m"),
        dict(reference_feature_id="missing"),
    ],
)
def test_wrong_input_identity_or_reference_id_is_input_error(change):
    scope, runtime, _, _, target, groups = two_planes()
    baseline = runtime.budget.used
    try:
        configured = parameters().model_copy(update=change)
        with pytest.raises(InvalidRequestError):
            measure_datum_deviation(
                runtime, target, groups[:1], configured, cancel=lambda: None
            )
        assert runtime.budget.used == baseline
    finally:
        assert not scope.close()


def test_empty_target_and_invalid_reference_do_not_reuse_values():
    from tests.test_metrology3d_height_step import roi
    from tests.test_metrology3d_plane import plane_parameters
    from custom_nodes.metrology3d_nodes.shared.fit_plane import fit_plane

    scope, runtime, cloud, _, target, groups = two_planes()
    try:
        empty = roi(runtime, cloud, 100)
        result = measure_datum_deviation(
            runtime, empty, groups[:1], parameters(), cancel=lambda: None
        )
        assert result.summary.reason == "empty_target"
        assert_default_matches(runtime, result, groups[:1])
        assert result.summary.diagnostic is None
        with result.borrow(runtime) as arrays:
            validate_deviation_rows(
                arrays, result.summary, chunk_rows=2, cancel=lambda: None
            )
        unavailable = cloud.unavailable("upstream_failed")
        result = measure_datum_deviation(
            runtime, unavailable, groups[:1], parameters(), cancel=lambda: None
        )
        assert result.summary.reason == "target_unavailable"
        assert_default_matches(runtime, result, groups[:1])
        assert result.summary.target_reason == "upstream_failed"
        with result.borrow(runtime) as arrays:
            validate_deviation_rows(
                arrays, result.summary, chunk_rows=2, cancel=lambda: None
            )
        invalid = fit_plane(
            runtime,
            unavailable,
            plane_parameters(feature_id="reference"),
            cancel=lambda: None,
        )
        result = measure_datum_deviation(
            runtime, target, [invalid], parameters(), cancel=lambda: None
        )
        assert result.summary.reason == "reference_unavailable"
        assert_default_matches(runtime, result, [invalid])
        assert result.summary.counts.invalid_reference == 9
        invalid = fit_plane(
            runtime,
            empty,
            plane_parameters(feature_id="reference"),
            cancel=lambda: None,
        )
        result = measure_datum_deviation(
            runtime, target, [invalid], parameters(), cancel=lambda: None
        )
        assert result.summary.reason == "reference_unavailable"
        assert result.summary.counts.invalid_reference == 9
        assert result.summary.diagnostic is None
        assert all(
            not i.valid and i.value is None
            for i in result.summary.numeric_table().items
        )
        assert_default_matches(runtime, result, [invalid])
        with result.borrow(runtime) as arrays:
            validate_deviation_rows(
                arrays, result.summary, chunk_rows=2, cancel=lambda: None
            )
    finally:
        assert not scope.close()
        assert runtime.budget.used == 0


def test_cancel_after_evidence_registration_returns_budget(monkeypatch):
    scope, runtime, _, _, target, groups = two_planes()
    baseline = runtime.budget.used
    register = runtime.storage_scope.register
    registered = False

    def track(key, value, cleanup):
        nonlocal registered
        register(key, value, cleanup)
        if isinstance(key, tuple) and key[0] == "datum-deviation":
            registered = True

    def cancel():
        if registered:
            raise InterruptedError("cancel after register")

    monkeypatch.setattr(runtime.storage_scope, "register", track)
    try:
        with pytest.raises(InterruptedError):
            measure_datum_deviation(
                runtime, target, groups[:1], parameters(), cancel=cancel
            )
        assert registered
        assert runtime.budget.used == baseline
    finally:
        assert not scope.close()


@pytest.mark.parametrize(
    "damage", ["missing", "extra", "truncated", "dtype", "count", "quality", "mean"]
)
def test_evidence_shape_summary_and_quality_are_recomputed(damage):
    from backend.contracts.workflows.geometry3d_methods import parameter_digest

    scope, runtime, _, _, target, groups = two_planes()
    try:
        result = measure_datum_deviation(
            runtime, target, groups[:1], parameters(), cancel=lambda: None
        )
        summary = result.summary
        with result.borrow(runtime) as arrays:
            altered = {key: a.copy() for key, a in arrays.items()}
        if damage == "missing":
            altered.pop("status")
        elif damage == "extra":
            altered["extra"] = altered["status"]
        elif damage == "truncated":
            altered["status"] = altered["status"][:-1]
        elif damage == "dtype":
            altered["deviation"] = altered["deviation"].astype(np.float32)
        elif damage == "count":
            altered["coverage_count"][0, 0] = 2
        elif damage == "quality":
            data = summary.model_dump()
            for rule in data["parameters"]["quality_policy"]["rules"]:
                if rule["item_id"] == "reference_triangle_edge":
                    rule["upper"] = 0.01
            configured = DeviationParameters.model_validate(data["parameters"])
            data["parameters_sha256"] = parameter_digest(configured)
            summary = DeviationSummary.model_validate(data)
        else:
            altered["deviation"][1, 0] = 5.1
        with pytest.raises(InvalidRequestError):
            validate_deviation_rows(altered, summary, chunk_rows=2, cancel=lambda: None)
    finally:
        assert not scope.close()


def test_exactly_one_failed_target_invalidates_five_outputs():
    from tests.test_metrology3d_preprocess import make_cloud
    from tests.point_cloud_support import policy
    from tests.test_metrology3d_height_step import roi
    from tests.test_metrology3d_plane import plane_parameters
    from custom_nodes.metrology3d_nodes.shared.fit_plane import fit_plane

    points = np.array(
        [(x, y, 0) for x in (-1, 0, 1) for y in (-1, 0, 1)] + [(0, 0, 5), (3, 0, 7)],
        dtype=float,
    )
    scope, runtime, cloud = make_cloud(
        unit="mm",
        coordinates=points,
        runtime_policy=policy(max_working_bytes=1024**2, max_live_array_bytes=1024**2),
    )
    try:
        reference = fit_plane(
            runtime,
            roi(runtime, cloud, 0),
            plane_parameters(feature_id="reference"),
            cancel=lambda: None,
        )
        result = measure_datum_deviation(
            runtime, cloud, [reference], parameters(), cancel=lambda: None
        )
        assert result.summary.counts.covered == 10
        assert result.summary.counts.failed == 1
        assert result.summary.diagnostic.maximum == 7
        assert result.summary.diagnostic.mean == pytest.approx(12 / 11)
        assert all(item.value is None for item in result.summary.numeric_table().items)
    finally:
        assert not scope.close()


def test_active_borrow_rejects_close_and_scope_release_invalidates_result():
    scope, runtime, _, _, target, groups = two_planes()
    try:
        result = measure_datum_deviation(
            runtime, target, groups[:1], parameters(), cancel=lambda: None
        )
        with result.borrow(runtime) as arrays:
            with pytest.raises(RuntimeError, match="活跃借用"):
                result.owner.close()
            assert arrays["deviation"][0, 0] == 5
        assert not scope.close()
        assert runtime.budget.used == 0
        with pytest.raises(InvalidRequestError):
            with result.borrow(runtime):
                pass
    finally:
        assert not scope.close()


@pytest.mark.parametrize("slope,radius", [(0, 2), (0.25, 2), (0.25, 0.01)])
@pytest.mark.parametrize("chunk_rows", [1, 2, 9])
def test_default_and_capture_exactly_agree_without_default_output_allocation(
    monkeypatch, slope, radius, chunk_rows
):
    import custom_nodes.metrology3d_nodes.shared.datum_deviation as module

    scope, runtime, _, _, target, groups = two_planes(slope=slope)
    runtime.policy = runtime.policy.model_copy(update=dict(chunk_rows=chunk_rows))
    baseline = runtime.budget.used
    try:
        captured = run_deviation(
            runtime,
            target,
            groups[:1],
            parameters(support_radius=radius),
            cancel=lambda: None,
            capture_details=True,
        )
        expected = captured.summary
        runtime.storage_scope.close_resource(captured.resource_key)

        def forbidden(*args, **kwargs):
            raise AssertionError("default path allocated a full evidence table")

        monkeypatch.setattr(module, "_empty_rows", forbidden)
        normal = run_deviation(
            runtime,
            target,
            groups[:1],
            parameters(support_radius=radius),
            cancel=lambda: None,
        )
        assert normal.summary == expected
        assert normal.summary.numeric_table() == expected.numeric_table()
        assert normal.owner is None and normal.resource_key is None
        assert runtime.budget.used == baseline
        with pytest.raises(InvalidRequestError, match="未开启"):
            with normal.borrow(runtime):
                pass
    finally:
        assert not scope.close()
        assert runtime.budget.used == 0


@pytest.mark.parametrize("bad", [0, 1, "false", None])
def test_capture_setting_rejects_implicit_coercion(bad):
    scope, runtime, _, _, target, groups = two_planes()
    baseline = runtime.budget.used
    try:
        with pytest.raises(InvalidRequestError, match="布尔"):
            run_deviation(
                runtime,
                target,
                groups[:1],
                parameters(),
                cancel=lambda: None,
                capture_details=bad,
            )
        assert runtime.budget.used == baseline
    finally:
        assert not scope.close()


def test_default_fits_budget_that_cannot_hold_detailed_output():
    scope, runtime, _, _, target, groups = two_planes()
    runtime.budget.limit = 16384
    baseline = runtime.budget.used
    try:
        normal = run_deviation(
            runtime, target, groups[:1], parameters(), cancel=lambda: None
        )
        assert normal.summary.valid
        assert runtime.budget.used == baseline
        with pytest.raises(InvalidRequestError, match="预算"):
            run_deviation(
                runtime,
                target,
                groups[:1],
                parameters(),
                cancel=lambda: None,
                capture_details=True,
            )
        assert runtime.budget.used == baseline
        with runtime.borrow(target) as view:
            assert len(view.chunk(0, 1)["positions"]) == 1
    finally:
        assert not scope.close()


@pytest.mark.parametrize("capture", [False, True])
def test_support_and_quality_evaluated_once_per_target(monkeypatch, capture):
    import custom_nodes.metrology3d_nodes.shared.datum_deviation as module

    scope, runtime, _, _, target, groups = two_planes(slope=0.25)
    calls = dict(support=0, quality=0)
    support, quality = module.reference_coverage, module.deviation_quality

    def check_support(*args, **kwargs):
        calls["support"] += 1
        return support(*args, **kwargs)

    def check_quality(*args, **kwargs):
        calls["quality"] += 1
        return quality(*args, **kwargs)

    monkeypatch.setattr(module, "reference_coverage", check_support)
    monkeypatch.setattr(module, "deviation_quality", check_quality)
    try:
        result = run_deviation(
            runtime,
            target,
            groups[:1],
            parameters(),
            cancel=lambda: None,
            capture_details=capture,
        )
        assert result.summary.valid
        assert calls == dict(support=9, quality=9)
    finally:
        assert not scope.close()


@pytest.mark.parametrize("stop", [1, 5, 20, 40, 80])
def test_default_cancellation_releases_support_and_working_budget(stop):
    scope, runtime, _, _, target, groups = two_planes(slope=0.25)
    baseline = runtime.budget.used
    calls = 0

    def cancel():
        nonlocal calls
        calls += 1
        if calls == stop:
            raise InterruptedError("cancel default measurement")

    try:
        with pytest.raises(InterruptedError):
            run_deviation(runtime, target, groups[:1], parameters(), cancel=cancel)
        assert runtime.budget.used == baseline
        with runtime.borrow(target):
            pass
    finally:
        assert not scope.close()


def test_default_cancellation_during_statistic_reread_releases_borrow(monkeypatch):
    import custom_nodes.metrology3d_nodes.shared.datum_deviation as module

    scope, runtime, _, _, target, groups = two_planes(slope=0.25)
    baseline = runtime.budget.used
    finish = module.DeviationStatisticsAccumulator.finish

    def cancel_on_finish(self, chunks, *, cancel):
        calls = 0

        def stop():
            nonlocal calls
            calls += 1
            if calls == 2:
                raise InterruptedError("cancel statistic reread")

        return finish(self, chunks, cancel=stop)

    monkeypatch.setattr(
        module.DeviationStatisticsAccumulator, "finish", cancel_on_finish
    )
    try:
        with pytest.raises(InterruptedError):
            run_deviation(
                runtime, target, groups[:1], parameters(), cancel=lambda: None
            )
        assert runtime.budget.used == baseline
        with runtime.borrow(target):
            pass
    finally:
        assert not scope.close()
