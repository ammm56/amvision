"""B06 独立像素坐标真值、精度、无效语义与作用域回收。"""

import numpy as np
import pytest
from pydantic import ValidationError

from backend.contracts.workflows.raster3d import (
    CalibratedRaster,
    RasterBufferDescriptor,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.resource_scope import ResourceScope
from backend.service.application.workflows.point_cloud.budget import CloudArrayBudget
from custom_nodes.metrology3d_nodes.shared.raster_conversion import convert_raster
from tests.point_cloud_support import policy, spatial


def specification(**updates):
    """显式测试标定，不成为生产初值或阈值。"""
    values = dict(
        format_id="amvision.calibrated-raster.v1",
        width=4,
        height=3,
        dtype="float32",
        calibration_id="test-camera",
        calibration_revision="r1",
        spatial=spatial(),
        projection=dict(
            kind="rectified-pinhole", depth_kind="axial-z", fx=2, fy=3, cx=1, cy=1
        ),
        value_scale=1,
        value_offset=0,
        validity=dict(invalid_raw_values=[], minimum=None, maximum=None),
        position_dtype="float32",
    )
    values.update(updates)
    return CalibratedRaster.model_validate(values)


def readonly(values, dtype=None):
    """模拟入口已持有且不再修改的数组。"""
    result = np.asarray(values, dtype=dtype)
    result.setflags(write=False)
    return result


def execute(data, spec, mask=None, *, p=None, cancel=lambda: None):
    """消费结果后关闭作用域，测试不得遗留可写或运行内引用。"""
    p = p or policy()
    budget = CloudArrayBudget(p.max_live_array_bytes)
    scope = ResourceScope(kind="raster-test")
    try:
        result = convert_raster(
            data, mask, spec, policy=p, budget=budget, scope=scope, cancel=cancel
        )
        with result.arrays.borrow() as arrays:
            assert all(not a.flags.writeable for a in arrays.values())
            copied = {key: value.copy() for key, value in arrays.items()}
        return copied, result.counts
    finally:
        scope.close()
        assert budget.used == 0


@pytest.mark.parametrize(
    "dtype", ["uint8", "uint16", "int16", "uint32", "int32", "float32", "float64"]
)
@pytest.mark.parametrize("kind", ["axial-z", "ray-range"])
def test_pinhole_independent_pixel_truth(dtype, kind):
    spec = specification(
        dtype=dtype,
        position_dtype="float64",
        projection=dict(
            kind="rectified-pinhole", depth_kind=kind, fx=2, fy=3, cx=1, cy=1
        ),
        value_scale=0.25,
        value_offset=0.5,
    )
    data = readonly(np.arange(1, 13).reshape(3, 4), dtype)
    result, counts = execute(data, spec)
    expected = []
    for row in range(3):
        for col in range(4):
            ray = np.array([(col - 1) / 2, (row - 1) / 3, 1])
            if kind == "ray-range":
                ray = ray / np.linalg.norm(ray)
            expected.append(ray * (float(data[row, col]) / 4 + 0.5))
    np.testing.assert_allclose(result["positions"], expected, rtol=1e-15, atol=1e-15)
    assert counts["valid"] == 12
    assert result["raw_samples"].dtype == np.dtype(dtype)
    assert result["raw_samples"].tobytes() == data.tobytes()


def test_orthographic_tilted_grid_negative_and_zero_heights():
    spec = specification(
        position_dtype="float64",
        value_scale=0.1,
        value_offset=-1,
        projection=dict(
            kind="orthographic-height",
            origin=[10, 20, 30],
            column_direction=[0.6, 0.8, 0],
            row_direction=[0, 0, 1],
            height_direction=[0.8, -0.6, 0],
            column_step=0.5,
            row_step=2,
        ),
    )
    data = readonly(np.arange(12).reshape(3, 4), "float32")
    result, counts = execute(data, spec)
    expected = []
    for row in range(3):
        for col in range(4):
            h = float(data[row, col]) / 10 - 1
            expected.append(
                [10 + 0.3 * col + 0.8 * h, 20 + 0.4 * col - 0.6 * h, 30 + 2 * row]
            )
    np.testing.assert_allclose(result["positions"], expected, rtol=0, atol=1e-14)
    assert counts["valid"] == 12


def test_invalid_priority_preserves_all_pixels_and_raw_values():
    data = readonly(
        [[np.nan, np.inf, -999, 0], [-1, 2, 20, 3], [4, 5, 6, 7]], "float32"
    )
    mask = readonly([[0, 1, 1, 1], [1, 0, 1, 1], [1, 1, 1, 1]], "uint8")
    spec = specification(
        validity=dict(invalid_raw_values=[-999], minimum=-5, maximum=10)
    )
    result, counts = execute(data, spec, mask)
    np.testing.assert_array_equal(
        result["sample_status"].ravel(), [1, 1, 3, 5, 5, 2, 4, 0, 0, 0, 0, 0]
    )
    assert result["raw_samples"].tobytes() == data.tobytes()
    assert len(result["positions"]) == spec.point_count() == 12
    assert sum(counts.values()) == 12 and counts["valid"] == 5
    assert np.isnan(result["positions"][:7]).all()
    assert result["input_mask"].tobytes() == mask.tobytes()


@pytest.mark.parametrize(
    "changes",
    [
        {"width": 0},
        {"dtype": "uint64"},
        {"position_dtype": "float16"},
        {"value_scale": 0},
        {"value_offset": float("nan")},
        {"projection": dict(kind="distorted-pinhole", fx=1, fy=1, cx=0, cy=0)},
        {
            "projection": dict(
                kind="rectified-pinhole", depth_kind="axial-z", fx=0, fy=1, cx=0, cy=0
            )
        },
        {"validity": dict(invalid_raw_values=[0, 0], minimum=None, maximum=None)},
        {"validity": dict(invalid_raw_values=[], minimum=2, maximum=1)},
        {"height": 2**53 - 1},
    ],
)
def test_bad_contracts_rejected(changes):
    with pytest.raises(ValidationError):
        specification(**changes)


def test_bad_grid_axes_and_buffer_layout():
    base = dict(
        kind="orthographic-height",
        origin=[0, 0, 0],
        column_direction=[1, 0, 0],
        row_direction=[0, 1, 0],
        height_direction=[0, 0, 1],
        column_step=1,
        row_step=1,
    )
    for change in (
        {"column_direction": [2, 0, 0]},
        {"row_direction": [1, 0, 0]},
        {"row_step": -1},
    ):
        with pytest.raises(ValidationError):
            specification(projection={**base, **change})
    spec = specification()
    valid = dict(
        format_id="amvision.raster-buffer.v1",
        raster=spec,
        has_mask=True,
        content_length=60,
    )
    assert RasterBufferDescriptor.model_validate(valid).content_length == 60
    for change in (
        {"has_mask": 1},
        {"content_length": 59},
        {"content_length": 61},
        {"row_stride": 16},
    ):
        with pytest.raises(ValidationError):
            RasterBufferDescriptor.model_validate({**valid, **change})


def test_file_decoded_size_is_not_the_array_payload_ceiling():
    """仅校验声明，不分配大数组；文件 1 GB 限额不冒充运行内存预算。"""
    from backend.contracts.workflows.raster3d import RasterToCloudParameters

    spec = specification(width=250_000_001, height=1)
    RasterToCloudParameters.model_validate(
        dict(
            settings=dict(
                kind="file",
                file_format="tiff",
                raster=spec.model_dump(),
            )
        )
    )
    with pytest.raises(ValidationError):
        RasterBufferDescriptor(
            format_id="amvision.raster-buffer.v1",
            raster=spec,
            has_mask=False,
            content_length=spec.point_count() * 4,
        )
    with pytest.raises(ValidationError):
        specification(width=2**53 - 1, height=2)


def test_bad_arrays_mask_sentinel_overflow_and_budget_release():
    data = readonly(np.ones((3, 4)), "float32")
    for bad in (
        data.copy(),
        readonly(np.ones((4, 3)), "float32"),
        readonly(data, "float64"),
        data[:, ::-1],
    ):
        with pytest.raises(InvalidRequestError):
            execute(bad, specification())
    for mask in (
        readonly(np.ones((3, 4)), "bool"),
        readonly(np.full((3, 4), 2), "uint8"),
    ):
        with pytest.raises(InvalidRequestError):
            execute(data, specification(), mask)
    with pytest.raises(InvalidRequestError, match="哨兵"):
        execute(
            data,
            specification(
                validity=dict(invalid_raw_values=[0.1], minimum=None, maximum=None)
            ),
        )
    for spec in (
        specification(value_scale=1e300),
        specification(value_scale=1e308, value_offset=1e308),
    ):
        with pytest.raises(InvalidRequestError, match="范围|溢出"):
            execute(data, spec)
    with pytest.raises(InvalidRequestError, match="预算"):
        execute(data, specification(), p=policy(max_decoded_bytes=32))


def test_chunk_equivalence_and_cancel_releases_output():
    spec = specification(position_dtype="float64")
    data = readonly(np.arange(1, 13).reshape(3, 4), "float32")
    a, _ = execute(data, spec, p=policy(chunk_rows=1))
    b, _ = execute(data, spec, p=policy(chunk_rows=12))
    for name in a:
        np.testing.assert_array_equal(a[name], b[name])
    calls = 0

    def cancel():
        nonlocal calls
        calls += 1
        if calls == 4:
            raise InterruptedError("cancel test")

    with pytest.raises(InterruptedError):
        execute(data, spec, p=policy(chunk_rows=1), cancel=cancel)
