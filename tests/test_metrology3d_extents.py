"""长宽独立几何真值，不用被测包络生成期望值。"""

import numpy as np
import pytest

from backend.contracts.workflows.measurement3d_evidence import MeasurementEvidence3d
from backend.service.application.errors import InvalidRequestError
from custom_nodes.metrology3d_nodes.shared.measure_extents import measure_extents
from tests.point_cloud_support import policy
from tests.test_metrology3d_dimension_contracts import extent_parameters
from tests.test_metrology3d_preprocess import make_cloud


def compute(points, parameters=None, *, budget=1024 * 1024, cancel=lambda: None):
    """真实 CloudRuntime 生命周期，关闭后不保留数组预算。"""
    scope, runtime, cloud = make_cloud(
        unit="mm", coordinates=points, runtime_policy=policy(max_working_bytes=budget)
    )
    try:
        result = measure_extents(
            runtime, parameters or extent_parameters(), cloud=cloud, cancel=cancel
        )
        assert (
            MeasurementEvidence3d.model_validate_json(result.model_dump_json())
            == result
        )
        return result
    finally:
        assert not scope.close()
        assert runtime.budget.used == 0


@pytest.mark.parametrize("dtype", [np.float32, np.float64])
@pytest.mark.parametrize("angle", [0, 0.3, 1.2])
def test_rectangle_and_fixed_axes_are_different_definitions(dtype, angle):
    c, s = np.cos(angle), np.sin(angle)
    xy = np.array([[0, 0], [8, 0], [8, 3], [0, 3], [4, 1]]) @ np.array(
        [[c, s], [-s, c]]
    )
    points = np.column_stack((xy, np.zeros(len(xy)))).astype(dtype)
    fixed = compute(points)
    np.testing.assert_allclose(
        [i.value for i in fixed.items],
        [8 * c + 3 * s, 8 * s + 3 * c],
        rtol=2e-6,
        atol=1e-6,
    )
    result = compute(points, extent_parameters(rectangle=True))
    np.testing.assert_allclose(
        [i.value for i in result.items], [8, 3], rtol=2e-6, atol=1e-6
    )
    assert all(i.valid for i in result.items)
    for contact in result.items[0].geometry.contacts:
        np.testing.assert_array_equal(contact.point, points[contact.source_index])


def test_square_keeps_dimensions_but_no_unique_orientation():
    result = compute(
        np.array([[0, 0, 0], [2, 0, 0], [2, 2, 0], [0, 2, 0]], dtype=float),
        extent_parameters(rectangle=True),
    )
    assert [i.value for i in result.items] == pytest.approx([2, 2])
    assert not result.items[0].geometry.candidates.orientation_unique


def test_triangle_tied_areas_with_inconsistent_sizes_are_invalid():
    result = compute(
        np.array([[0, 0, 0], [4, 0, 0], [0, 3, 0]], dtype=float),
        extent_parameters(rectangle=True),
    )
    assert all(
        not i.valid
        and i.value is None
        and i.geometry is None
        and i.reason == "ambiguous_dimensions"
        for i in result.items
    )
    assert not result.items[0].diagnostic.candidates.dimensions_consistent


@pytest.mark.parametrize(
    "points",
    [np.zeros((4, 3)), np.array([[0, 0, 0], [1, 1, 0], [2, 2, 0]], dtype=float)],
)
def test_degenerate_input_retains_both_output_ids(points):
    result = compute(points)
    assert [i.item_id for i in result.items] == ["u", "v"]
    assert all(not i.valid and i.value is None for i in result.items)


def test_order_translation_thin_shape_and_precision():
    points = np.array(
        [[0, 0, 0], [1e5, 0, 0], [1e5, 0.01, 0], [0, 0.01, 0]], dtype=float
    ) + [1e8, 1e8, 0]
    a = compute(points)
    b = compute(points[::-1])
    assert [i.value for i in a.items] == [i.value for i in b.items]
    assert a.items[0].value == 1e5 and a.items[1].value == pytest.approx(0.01, abs=1e-8)


def test_budget_cancel_invalid_input_and_wrong_port_are_not_missing_dimensions():
    points = np.array([[0, 0, 0], [8, 0, 0], [8, 3, 0], [0, 3, 0]], dtype=float)
    with pytest.raises(InvalidRequestError, match="预算"):
        compute(points, extent_parameters(rectangle=True), budget=2048)

    def stop():
        raise InterruptedError("cancel")

    with pytest.raises(InterruptedError):
        compute(points, cancel=stop)
    points = points.copy()
    points[0, 0] = np.nan
    with pytest.raises(InvalidRequestError, match="无效"):
        compute(points)
