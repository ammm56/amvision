"""M2 闭边界裁剪：解析坐标真值、原始行号、预算和取消。"""

from copy import deepcopy

import numpy as np
import pytest
from pydantic import ValidationError

from backend.contracts.workflows.geometry3d import CropCloudParameters
from backend.contracts.workflows.point_cloud_runtime import (
    FilterCloudValid,
    NormalizeCloudUnits,
)
from backend.service.application.errors import InvalidRequestError
from custom_nodes._metrology3d_nodes.shared.crop_roi import crop_roi
from custom_nodes._metrology3d_nodes.shared.filter_valid import filter_valid
from custom_nodes._metrology3d_nodes.shared.normalize_units import normalize_units
from tests.test_metrology3d_preprocess import make_cloud


def box(**geometry):
    """整数轴测试盒，无生产默认参数。"""
    return dict(
        kind="box",
        roi_id="roi",
        frame_id="fixture",
        length_unit="mm",
        geometry=dict(
            center=[0, 0, 0],
            size=[2, 4, 6],
            rotation=[[1, 0, 0], [0, 1, 0], [0, 0, 1]],
            **geometry,
        ),
    )


def parameters(*rois):
    """首项为显式目标，其余为受控依赖。"""
    return CropCloudParameters(roi_id=rois[0]["roi_id"], rois=rois)


@pytest.mark.parametrize("dtype", [np.float32, np.float64])
def test_box_closed_boundary_and_empty(dtype):
    points = np.array([[1, 2, 3], [-1, -2, -3], [0, 0, 0], [1.01, 0, 0]], dtype=dtype)
    scope, runtime, source = make_cloud(unit="mm", coordinates=points)
    cloud, summary = crop_roi(runtime, source, parameters(box()), cancel=lambda: None)
    assert summary == dict(
        state="ready", reason=None, input_count=4, kept_count=3, removed_count=1
    )
    with runtime.borrow(cloud) as view:
        np.testing.assert_array_equal(view.chunk(0, 2)["positions"], points[:2])
        np.testing.assert_array_equal(view.source_indices(0, 2), [0, 1])
    roi = box()
    roi["geometry"]["center"] = [100, 0, 0]
    empty, _ = crop_roi(runtime, cloud, parameters(roi), cancel=lambda: None)
    assert empty.state == "ready" and empty.point_count == 0 and empty.cloud_id
    assert runtime.source_point_count(empty) == 4
    assert not scope.close()
    assert runtime.budget.used == 0


def test_rotated_box_and_chained_original_rows():
    scope, runtime, source = make_cloud(
        unit="mm",
        coordinates=np.array(
            [[9, 0, 0], [0, 2, 0], [2, 0, 0], [0, 1, 0]], dtype=np.float32
        ),
    )
    roi = box()
    roi["geometry"].update(size=[4, 2, 6], rotation=[[0, -1, 0], [1, 0, 0], [0, 0, 1]])
    cloud, _ = crop_roi(runtime, source, parameters(roi), cancel=lambda: None)
    cloud, _ = crop_roi(runtime, cloud, parameters(box()), cancel=lambda: None)
    with runtime.borrow(cloud) as view:
        np.testing.assert_array_equal(view.source_indices(0, 2), [1, 3])
    assert runtime.source_point_count(cloud) == 4
    assert not scope.close()


def test_cylinder_and_bounded_section():
    scope, runtime, source = make_cloud(
        unit="mm",
        coordinates=np.array(
            [[1, 0, 1], [0, 0, 2], [0, 1, 0], [2, 0, 0]], dtype=np.float64
        ),
    )
    cylinder = dict(
        kind="cylinder",
        roi_id="cylinder",
        frame_id="fixture",
        length_unit="mm",
        geometry=dict(center=[0, 0, 0], axis=[0, 0, 1], radius=1, length=2),
    )
    section = dict(
        kind="section-band",
        roi_id="section",
        frame_id="fixture",
        length_unit="mm",
        geometry=dict(
            origin=[0, 0, 0], normal=[0, 0, 1], thickness=1, bounds_roi_id="cylinder"
        ),
    )
    cloud, _ = crop_roi(runtime, source, parameters(cylinder), cancel=lambda: None)
    assert cloud.point_count == 2
    cloud, _ = crop_roi(
        runtime, source, parameters(section, cylinder), cancel=lambda: None
    )
    with runtime.borrow(cloud) as view:
        np.testing.assert_array_equal(view.source_indices(0, 1), [2])
    assert not scope.close()


@pytest.mark.parametrize("change", ["cycle", "missing", "mirror", "unit", "duplicate"])
def test_bad_roi_contract(change):
    roi = box()
    rois = [roi]
    if change in {"cycle", "missing"}:
        roi.update(
            kind="section-band",
            geometry=dict(
                origin=[0, 0, 0],
                normal=[0, 0, 1],
                thickness=1,
                bounds_roi_id="roi" if change == "cycle" else "missing",
            ),
        )
    elif change == "mirror":
        roi["geometry"]["rotation"][0][0] = -1
    elif change == "unit":
        rois.append({**deepcopy(roi), "roi_id": "other", "length_unit": "m"})
    else:
        rois.append(deepcopy(roi))
    with pytest.raises(ValidationError):
        parameters(*rois)


def test_mismatch_bad_points_and_cancel_leave_no_allocation():
    scope, runtime, source = make_cloud(unit="m")
    before = runtime.budget.used
    with pytest.raises(InvalidRequestError, match="坐标或单位"):
        crop_roi(runtime, source, parameters(box()), cancel=lambda: None)
    assert runtime.budget.used == before
    assert not scope.close()
    scope, runtime, source = make_cloud(
        unit="mm", coordinates=np.array([[np.nan, 0, 0]], dtype=np.float32)
    )
    before = runtime.budget.used
    with pytest.raises(InvalidRequestError, match="无效位置"):
        crop_roi(runtime, source, parameters(box()), cancel=lambda: None)
    assert runtime.budget.used == before
    assert not scope.close()
    scope, runtime, source = make_cloud(unit="mm")
    before = runtime.budget.used
    calls = 0

    def cancel():
        nonlocal calls
        calls += 1
        if calls == 3:
            raise RuntimeError("cancelled")

    with pytest.raises(RuntimeError, match="cancelled"):
        crop_roi(runtime, source, parameters(box()), cancel=cancel)
    assert runtime.budget.used == before
    assert not scope.close()


def test_unavailable_consumers_do_not_borrow_or_allocate():
    scope, runtime, source = make_cloud(unit="mm")
    unavailable = source.model_copy(
        update=dict(
            state="unavailable",
            reason="datum_missing",
            cloud_id=None,
            revision=None,
            point_count=None,
            fields=None,
            sample_origin=None,
        )
    )
    before = runtime.budget.used
    assert (
        normalize_units(
            runtime, unavailable, NormalizeCloudUnits(), cancel=lambda: None
        )
        == unavailable
    )
    with pytest.raises(InvalidRequestError, match="单位不一致"):
        normalize_units(
            runtime,
            unavailable,
            NormalizeCloudUnits(source_unit="m"),
            cancel=lambda: None,
        )
    filtered, summary = filter_valid(
        runtime,
        unavailable,
        FilterCloudValid(finite_fields=("positions",), sentinels=()),
        cancel=lambda: None,
    )
    assert filtered == unavailable and summary["input_count"] is None
    cropped, summary = crop_roi(
        runtime, unavailable, parameters(box()), cancel=lambda: None
    )
    assert cropped == unavailable and summary["input_count"] is None
    assert runtime.budget.used == before
    with pytest.raises(InvalidRequestError, match="当前运行"):
        crop_roi(
            runtime,
            unavailable.model_copy(update={"run_id": "other"}),
            parameters(box()),
            cancel=lambda: None,
        )
    assert not scope.close()
