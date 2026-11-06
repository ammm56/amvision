"""B07 独立轮廓真值、缺行身份、原值精度和取消/预算回收。"""

import numpy as np
import pytest
from pydantic import ValidationError

from backend.contracts.workflows.profile3d import (
    CalibratedProfiles,
    ProfileBufferDescriptor,
    ProfilesToCloudParameters,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.resource_scope import ResourceScope
from backend.service.application.workflows.point_cloud.budget import CloudArrayBudget
from custom_nodes.metrology3d_nodes.shared.profile_conversion import convert_profiles
from tests.point_cloud_support import policy, spatial


def specification(**updates):
    """仅用于独立真值的显式标定，非节点默认值。"""
    values = dict(
        format_id="amvision.calibrated-profiles.v1",
        point_count=6,
        profile_count=4,
        dtype="float32",
        calibration_id="test-scanner",
        calibration_revision="r1",
        spatial=spatial(),
        origin=[10, 20, 30],
        x_direction=[0.6, 0.8, 0],
        scan_direction=[0, 0, 1],
        height_direction=[0.8, -0.6, 0],
        displacement=dict(kind="fixed-step", origin_line_id=5, step=2),
        position_dtype="float64",
    )
    values.update(updates)
    return CalibratedProfiles.model_validate(values)


def readonly(value, dtype):
    """模拟已经准入的不可变数组。"""
    result = np.asarray(value, dtype=dtype)
    result.setflags(write=False)
    return result


def inputs(dtype="float32", encoder=None):
    """原采集行 5 为空，行号 4、6、7 缺失，不能据此缩短扫描位移。"""
    result = dict(
        profiles=readonly(
            [[1, 2], [2, 3], [3, 4], [4, 0], [5, -1], [6, 0.123456789]], dtype
        ),
        line_offsets=readonly([0, 2, 2, 5, 6], "uint64"),
        line_ids=readonly([3, 5, 8, 9], "uint64"),
    )
    if encoder is not None:
        result["encoder_positions"] = readonly(encoder, "float64")
    return result


def execute(arrays, spec, *, p=None, cancel=lambda: None):
    """复制测试观察结果后关闭唯一 Scope；失败也检查容量归零。"""
    p = p or policy()
    budget = CloudArrayBudget(p.max_live_array_bytes)
    scope = ResourceScope(kind="profile-test")
    try:
        result = convert_profiles(
            arrays,
            spec,
            has_validity="validity" in arrays,
            policy=p,
            budget=budget,
            scope=scope,
            cancel=cancel,
        )
        with result.arrays.borrow() as values:
            assert all(not a.flags.writeable for a in values.values())
            copied = {key: value.copy() for key, value in values.items()}
        return copied, result.counts
    finally:
        scope.close()
        assert budget.used == 0


@pytest.mark.parametrize("dtype", ["float32", "float64"])
@pytest.mark.parametrize("chunk_rows", [1, 3, 8])
@pytest.mark.parametrize("method", ["fixed-step", "encoder-positions"])
def test_independent_tilted_profile_truth(dtype, chunk_rows, method):
    encoder = [12, 3, 8, 8] if method == "encoder-positions" else None
    arrays = inputs(dtype, encoder)
    displacement = (
        dict(kind="encoder-positions", dtype="float64", scale=0.5, origin=10)
        if encoder
        else dict(kind="fixed-step", origin_line_id=5, step=2)
    )
    spec = specification(dtype=dtype, displacement=displacement)
    actual, counts = execute(arrays, spec, p=policy(chunk_rows=chunk_rows))
    expected, ids, samples = [], [], []
    for line, identity in enumerate([3, 5, 8, 9]):
        for sample, index in enumerate(
            range(
                int(arrays["line_offsets"][line]), int(arrays["line_offsets"][line + 1])
            )
        ):
            x, h = map(float, arrays["profiles"][index])
            distance = (encoder[line] - 10) / 2 if encoder else (identity - 5) * 2
            expected.append(
                [10 + x * 0.6 + h * 0.8, 20 + x * 0.8 - h * 0.6, 30 + distance]
            )
            ids.append(identity)
            samples.append(sample)
    np.testing.assert_allclose(actual["positions"], expected, rtol=0, atol=1e-14)
    np.testing.assert_array_equal(actual["acquisition_line_id"][:, 0], ids)
    np.testing.assert_array_equal(actual["profile_sample_index"][:, 0], samples)
    assert counts == {
        "valid": 6,
        "non_finite_profile": 0,
        "non_finite_encoder": 0,
        "masked": 0,
    }
    for index, field in enumerate(("raw_profile_x", "raw_profile_height")):
        assert actual[field].dtype.name == dtype
        assert actual[field][:, 0].tobytes() == arrays["profiles"][:, index].tobytes()


def test_invalid_records_retained_without_filling_or_reordering():
    arrays = inputs(encoder=[12, 3, float("nan"), 8])
    raw = arrays["profiles"].copy()
    raw[0, 0] = np.nan
    raw[4, 1] = np.inf
    arrays["profiles"] = readonly(raw, "float32")
    arrays["validity"] = readonly([0, 0, 0, 1, 1, 1], "uint8")
    spec = specification(
        displacement=dict(kind="encoder-positions", dtype="float64", scale=1, origin=0)
    )
    actual, counts = execute(arrays, spec)
    np.testing.assert_array_equal(actual["sample_status"][:, 0], [1, 3, 2, 2, 1, 0])
    np.testing.assert_array_equal(actual["validity"][:, 0], [0, 0, 0, 0, 0, 1])
    assert np.isnan(actual["positions"][:5]).all()
    assert actual["raw_profile_x"][0, 0].tobytes() == raw[0, 0].tobytes()
    assert sum(counts.values()) == spec.point_count == len(actual["positions"])


@pytest.mark.parametrize(
    "field,value,dtype",
    [
        ("line_offsets", [1, 2, 2, 5, 6], "uint64"),
        ("line_offsets", [0, 2, 2, 5, 7], "uint64"),
        ("line_offsets", [0, 3, 2, 5, 6], "uint64"),
        ("line_ids", [3, 8, 5, 9], "uint64"),
        ("line_ids", [3, 5, 5, 9], "uint64"),
        ("line_ids", [3, 5, 8, 2**53], "uint64"),
        ("line_ids", [3, 5, 8, 9], "int64"),
        ("validity", [1, 1, 1, 2, 1, 1], "uint8"),
    ],
)
def test_malformed_structure_is_not_a_measurement_result(field, value, dtype):
    arrays = inputs()
    arrays[field] = readonly(value, dtype)
    with pytest.raises(InvalidRequestError):
        execute(arrays, specification())


@pytest.mark.parametrize("change", ["extra", "missing", "writable", "strided"])
def test_strict_input_fields(change):
    arrays = inputs()
    if change == "extra":
        arrays["unused"] = readonly([1], "uint8")
    elif change == "missing":
        del arrays["line_ids"]
    elif change == "writable":
        arrays["profiles"] = arrays["profiles"].copy()
    else:
        arrays["profiles"] = readonly(np.zeros((6, 4)), "float32")[:, ::2]
    with pytest.raises(InvalidRequestError):
        execute(arrays, specification())


@pytest.mark.parametrize("limit", ["max_decoded_bytes", "max_working_bytes"])
def test_budget_rejection_releases_all_allocations(limit):
    with pytest.raises(InvalidRequestError):
        execute(inputs(), specification(), p=policy(**{limit: 1, "chunk_bytes": 1}))


def test_shared_live_budget_rejection_preserves_existing_owner():
    p = policy()
    budget = CloudArrayBudget(p.max_live_array_bytes)
    held = budget.reserve(p.max_live_array_bytes - 1)
    scope = ResourceScope(kind="profile-budget")
    try:
        with pytest.raises(InvalidRequestError):
            convert_profiles(
                inputs(),
                specification(),
                has_validity=False,
                policy=p,
                budget=budget,
                scope=scope,
                cancel=lambda: None,
            )
        assert budget.used == p.max_live_array_bytes - 1
    finally:
        scope.close()
        held.close()
        assert budget.used == 0


@pytest.mark.parametrize("stop_at", [1, 3, 5, 8, 11])
def test_cancel_at_input_and_conversion_boundaries(stop_at):
    calls = 0

    def cancel():
        nonlocal calls
        calls += 1
        if calls == stop_at:
            raise InterruptedError("cancel profile")

    with pytest.raises(InterruptedError):
        execute(inputs(), specification(), p=policy(chunk_rows=1), cancel=cancel)


def test_position_overflow_rejects_instead_of_downgrading_validity():
    with pytest.raises(InvalidRequestError):
        execute(inputs(), specification(origin=[1e300, 0, 0], position_dtype="float32"))


def test_leading_and_trailing_empty_profiles_do_not_take_point_identity():
    arrays = inputs()
    arrays["line_offsets"] = readonly([0, 0, 6, 6, 6], "uint64")
    result, counts = execute(arrays, specification())
    np.testing.assert_array_equal(result["acquisition_line_id"][:, 0], [5] * 6)
    np.testing.assert_array_equal(result["profile_sample_index"][:, 0], np.arange(6))
    assert counts["valid"] == 6


def test_encoder_float32_original_values_and_float32_output():
    arrays = inputs()
    arrays["encoder_positions"] = readonly([0.12345, 2, -0.25, -0.25], "float32")
    spec = specification(
        position_dtype="float32",
        displacement=dict(
            kind="encoder-positions",
            dtype="float32",
            scale=1,
            origin=0,
        ),
    )
    result, _ = execute(arrays, spec)
    assert result["positions"].dtype == np.float32
    assert result["raw_encoder_position"].dtype == np.float32
    np.testing.assert_array_equal(
        result["raw_encoder_position"][:, 0],
        arrays["encoder_positions"][[0, 0, 2, 2, 2, 3]],
    )


def test_contract_layout_origin_and_explicit_sources():
    spec = specification()
    size = 6 * 2 * 4 + 5 * 8 + 4 * 8 + 6
    descriptor = ProfileBufferDescriptor(
        format_id="amvision.profile-buffer.v1",
        profiles=spec,
        has_validity=True,
        content_length=size,
    )
    assert descriptor.profiles.input_bytes(has_validity=True) == size
    with pytest.raises(ValidationError):
        ProfileBufferDescriptor.model_validate(
            descriptor.model_dump() | {"content_length": size + 1}
        )
    with pytest.raises(ValidationError):
        specification(scan_direction=[1, 0, 0])
    large = specification(point_count=125_000_000)
    # 文件载荷与解码内存不是同一个限额；数组入口仍精确限制 1 GB。
    ProfilesToCloudParameters.model_validate(
        dict(
            settings=dict(
                kind="file",
                file_format="npz",
                profiles=large.model_dump(),
                has_validity=False,
            )
        )
    )
    with pytest.raises(ValidationError):
        ProfileBufferDescriptor(
            format_id="amvision.profile-buffer.v1",
            profiles=large,
            has_validity=False,
            content_length=large.input_bytes(has_validity=False),
        )
    with pytest.raises(ValidationError):
        ProfilesToCloudParameters.model_validate(
            dict(settings=dict(kind="local-array", profiles=spec.model_dump()))
        )
    with pytest.raises(ValidationError):
        specification(displacement=dict(kind="fixed-step", origin_line_id=5, step=0))
