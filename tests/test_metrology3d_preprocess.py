"""M1 单位归一和有效点过滤的独立数值、精度与取消验证。"""

from copy import deepcopy

import numpy as np
import pytest

from backend.contracts.workflows.point_cloud import CloudField
from backend.contracts.workflows.point_cloud_runtime import (
    CloudLocalSource,
    FilterCloudSummary,
    FilterCloudValid,
    NormalizeCloudUnits,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.resource_scope import ResourceScope
from backend.service.application.workflows.point_cloud.runtime import get_cloud_runtime
from custom_nodes._metrology3d_nodes.shared.normalize_units import normalize_units
from custom_nodes._metrology3d_nodes.shared.filter_valid import filter_valid
from tests.point_cloud_support import policy, spatial
from tests.test_point_cloud_runtime import own


def make_cloud(*, unit="m", attributes=(), coordinates=None, runtime_policy=None):
    """显式构造源数据及元数据，不使用被测换算计算期望值。"""
    scope = ResourceScope(kind="workflow")
    runtime = get_cloud_runtime(scope, run_id="run", policy=runtime_policy or policy())
    coordinates = (
        np.array([[1, 2, 3], [4, 5, 6]], dtype=np.float32)
        if coordinates is None
        else coordinates
    )
    fields = [
        CloudField(
            name="positions",
            semantic="position",
            dtype=coordinates.dtype.name,
            components=3,
            unit=None,
        )
    ]
    arrays = {"positions": coordinates}
    for name, values, length_unit in attributes:
        components = 3 if name in {"normals", "colors"} else 1
        arrays[name] = np.asarray(values).reshape(len(coordinates), components)
        fields.append(
            CloudField(
                name=name,
                semantic={
                    "validity": "validity",
                    "normals": "normal",
                    "colors": "color-rgb",
                }.get(name, "scalar"),
                dtype=arrays[name].dtype.name,
                components=components,
                unit=length_unit,
            )
        )
    source_spatial = spatial().model_copy(
        update={
            "length_unit": unit,
            "unit_source": "unknown" if unit is None else "configuration",
        }
    )
    reference = runtime.register_source(
        owner=own(runtime, arrays),
        point_count=len(coordinates),
        fields=tuple(fields),
        spatial=source_spatial,
        source=CloudLocalSource(
            kind="local-array",
            content_sha256="1" * 64,
            descriptor_sha256="2" * 64,
            source_observation_id=None,
        ),
        source_metadata=None,
        cancel=lambda: None,
    )
    return scope, runtime, reference


@pytest.mark.parametrize(
    "unit,source,expected",
    [
        ("m", [[1, 2, 3], [4, 5, 6]], [[1000, 2000, 3000], [4000, 5000, 6000]]),
        ("um", [[1000, 2000, 3000], [4000, 5000, 6000]], [[1, 2, 3], [4, 5, 6]]),
    ],
)
@pytest.mark.parametrize("dtype", [np.float32, np.float64])
def test_normalize_preserves_dtype_original_and_exact_values(
    unit, source, expected, dtype
):
    coordinates = np.array(source, dtype=dtype)
    scope, runtime, reference = make_cloud(unit=unit, coordinates=coordinates)
    result = normalize_units(
        runtime, reference, NormalizeCloudUnits(), cancel=lambda: None
    )
    with runtime.borrow(result) as view:
        actual = view.chunk(0, 2)["positions"]
        assert actual.dtype == dtype
        np.testing.assert_array_equal(actual, expected)
    np.testing.assert_array_equal(coordinates, source)
    assert runtime.original_source(result)[0] == reference
    assert (
        normalize_units(runtime, result, NormalizeCloudUnits(), cancel=lambda: None)
        == result
    )
    assert scope.close() == () and runtime.budget.used == 0


def test_integer_length_attributes_never_round_through_double():
    value = 18_446_744_073_709_551_000
    scope, runtime, reference = make_cloud(
        unit="mm",
        attributes=(
            ("length", np.array([value, 1000], dtype=np.uint64), "um"),
            ("label", np.array([2**64 - 1, 7], dtype=np.uint64), "1"),
            ("small", np.array([0, 0], dtype=np.int8), "m"),
        ),
    )
    result = normalize_units(
        runtime, reference, NormalizeCloudUnits(), cancel=lambda: None
    )
    with runtime.borrow(result) as view:
        block = view.chunk(0, 2)
        assert int(block["length"][0, 0]) == 18_446_744_073_709_551
        assert int(block["label"][0, 0]) == 2**64 - 1
        assert block["small"].dtype == np.int8
    assert scope.close() == ()


@pytest.mark.parametrize("values,unit", [([1, 1000], "um"), ([2**63 - 1, 0], "m")])
def test_nonrepresentable_integer_conversion_rejects_without_budget_leak(values, unit):
    scope, runtime, reference = make_cloud(
        attributes=(("length", np.array(values, dtype=np.int64), unit),)
    )
    before = runtime.budget.used
    with pytest.raises(InvalidRequestError):
        normalize_units(runtime, reference, NormalizeCloudUnits(), cancel=lambda: None)
    assert runtime.budget.used == before
    assert scope.close() == ()


@pytest.mark.parametrize(
    "value", [np.finfo(np.float32).max, np.nextafter(np.float32(0), np.float32(1))]
)
def test_float_overflow_and_underflow_are_not_silently_turned_into_invalid_points(
    value,
):
    unit = "m" if value > 1 else "um"
    scope, runtime, reference = make_cloud(
        unit=unit, coordinates=np.full((2, 3), value, dtype=np.float32)
    )
    before = runtime.budget.used
    with pytest.raises(InvalidRequestError, match="可表示"):
        normalize_units(runtime, reference, NormalizeCloudUnits(), cancel=lambda: None)
    assert runtime.budget.used == before
    assert scope.close() == ()


def test_unknown_or_conflicting_unit_is_never_guessed():
    scope, runtime, reference = make_cloud(unit=None)
    with pytest.raises(InvalidRequestError, match="未知"):
        normalize_units(runtime, reference, NormalizeCloudUnits(), cancel=lambda: None)
    result = normalize_units(
        runtime, reference, NormalizeCloudUnits(source_unit="mm"), cancel=lambda: None
    )
    assert result.spatial.length_unit == "mm" and result.cloud_id != reference.cloud_id
    with pytest.raises(InvalidRequestError, match="不一致"):
        normalize_units(
            runtime, result, NormalizeCloudUnits(source_unit="m"), cancel=lambda: None
        )
    assert scope.close() == ()


def test_filter_summary_rejects_removed_points_without_any_invalid_reason():
    with pytest.raises(ValueError, match="计数"):
        FilterCloudSummary(
            state="ready",
            reason=None,
            input_count=1,
            kept_count=0,
            removed_count=1,
            invalid_counts={"mask": 0, "non_finite": 0, "sentinel": 0},
        )


def test_explicit_null_is_not_a_source_unit_confirmation():
    with pytest.raises(ValueError, match="null"):
        NormalizeCloudUnits.model_validate({"source_unit": None})


def test_filter_counts_overlap_preserves_zero_and_all_fields():
    source = np.array(
        [[0, 0, 0], [np.nan, 2, 3], [4, 5, 6], [7, 8, 9]], dtype=np.float32
    )
    scope, runtime, reference = make_cloud(
        unit="mm",
        coordinates=source,
        attributes=(
            ("validity", np.array([1, 0, 1, 1], dtype=np.uint8), "1"),
            ("label", np.array([2**64 - 1, 7, 7, 9], dtype=np.uint64), "1"),
        ),
    )
    parameters = FilterCloudValid.model_validate(
        {
            "finite_fields": ["positions"],
            "sentinels": [{"field": "label", "values": ["7"], "match": "all"}],
        }
    )
    result, summary = filter_valid(runtime, reference, parameters, cancel=lambda: None)
    assert summary == {
        "state": "ready",
        "reason": None,
        "input_count": 4,
        "kept_count": 2,
        "removed_count": 2,
        "invalid_counts": {"mask": 1, "non_finite": 1, "sentinel": 2},
    }
    with runtime.borrow(result) as view:
        block = view.chunk(0, 2)
        np.testing.assert_array_equal(block["positions"], [[0, 0, 0], [7, 8, 9]])
        assert block["positions"].dtype == np.float32
        assert int(block["label"][0, 0]) == 2**64 - 1
        np.testing.assert_array_equal(view.source_indices(0, 2), [0, 3])
    assert result.source_metadata is None
    assert scope.close() == () and runtime.budget.used == 0


@pytest.mark.parametrize("values", [[0.1, 0.1, 0.1], ["1", "2", "3"]])
def test_float_sentinel_must_be_exact_and_correct_type(values):
    scope, runtime, reference = make_cloud()
    parameters = FilterCloudValid.model_validate(
        {
            "finite_fields": ["positions"],
            "sentinels": [{"field": "positions", "values": values, "match": "all"}],
        }
    )
    with pytest.raises(InvalidRequestError):
        filter_valid(runtime, reference, parameters, cancel=lambda: None)
    assert scope.close() == ()


@pytest.mark.parametrize("operation", ["normalize", "filter"])
def test_cancel_at_each_stage_releases_new_allocations(operation):
    for at in range(1, 16):
        scope, runtime, reference = make_cloud()
        before = runtime.budget.used
        original = deepcopy(reference.model_dump())
        count = 0

        def cancel():
            nonlocal count
            count += 1
            if count == at:
                raise InterruptedError("controlled cancel")

        try:
            if operation == "normalize":
                normalize_units(
                    runtime, reference, NormalizeCloudUnits(), cancel=cancel
                )
            else:
                filter_valid(
                    runtime,
                    reference,
                    FilterCloudValid(finite_fields=("positions",), sentinels=()),
                    cancel=cancel,
                )
        except InterruptedError:
            assert runtime.budget.used == before
        assert reference.model_dump() == original
        assert scope.close() == () and runtime.budget.used == 0
