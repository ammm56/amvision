"""完整曲线的传输计数不侵占通用元数据预算，也不放开任意 JSON。"""

import pytest

from backend.service.application.workflows.runtime_preview import (
    MAX_PREVIEW_BYTES,
    MAX_PREVIEW_VALUES,
    _DisplayLimit,
    _copy_json,
    _copy_preview,
    cloud_sample_values,
)


def payload(count=30_000):
    """构造完整曲线的显示形状，不依赖算法生成大量几何。"""
    return dict(
        type="point-cloud-preview",
        format_id="amvision.point-cloud-preview.v1",
        display_point_count=100,
        geometry=dict(
            planes=[],
            curves=[
                dict(
                    kind="circle",
                    support_point_count=count,
                    points=[[1.0, 2.0, 3.0]] * count,
                    inlier_flags=[True] * count,
                    radial_residuals=[0.01] * count,
                    fit_weights=[1.0] * count,
                    angular_sectors=[0] * count,
                )
            ],
        ),
    )


def test_complete_curve_uses_byte_budget():
    """三万个点及四条逐点数组可交付，但普通 metadata 仍有原上限。"""
    value = payload()
    assert cloud_sample_values(value) == 240_000
    assert (
        _copy_json(
            value, [MAX_PREVIEW_BYTES, MAX_PREVIEW_VALUES + cloud_sample_values(value)]
        )
        == value
    )
    value["metadata"] = list(range(MAX_PREVIEW_VALUES + 1))
    with pytest.raises(_DisplayLimit, match="preview_structure_limit"):
        _copy_json(
            value, [MAX_PREVIEW_BYTES, MAX_PREVIEW_VALUES + cloud_sample_values(value)]
        )


@pytest.mark.parametrize(
    "key,bad",
    [
        ("points", [[1, 2, float("nan")]]),
        ("points", [[1, 2]]),
        ("inlier_flags", [1]),
        ("radial_residuals", [float("inf")]),
        ("fit_weights", [0]),
        ("angular_sectors", [-1]),
        ("profile_kinds", [4]),
    ],
)
def test_malformed_curve_arrays_rejected(key, bad):
    """类型、长度、有限值和逐点标记均需有效。"""
    value = payload(1)
    value["geometry"]["curves"][0][key] = bad
    with pytest.raises(_DisplayLimit, match="preview_not_json"):
        cloud_sample_values(value)


def test_curve_bytes_cannot_bypass_limit():
    """使用引用构造越限数组，验证校验先于逐点遍历。"""
    with pytest.raises(_DisplayLimit, match="preview_size_limit"):
        cloud_sample_values(payload(600_000))


def test_measurement_items_have_individual_structure_budget():
    """完整工件不会因测量项相加误报，但每项必须仍是合法证据。"""
    from custom_nodes.metrology3d_nodes.shared.measure_step import measure_step
    from tests.test_metrology3d_height_step import two_planes
    from tests.test_metrology3d_measurement_contracts import step_parameters

    scope, runtime, _, _, _, groups = two_planes()
    try:
        evidence = None
        items = []
        for index in range(200):
            parameters = step_parameters().model_copy(
                update={"item_id": f"step-{index}"}
            )
            evidence = measure_step(
                runtime, parameters, groups=groups, cancel=lambda: None
            ).model_dump(mode="json")
            items.extend(evidence["items"])
        evidence["items"] = items
        value = payload(1)
        value["measurements"] = evidence

        def budget():
            """每次复制从相同的完整预算开始。"""
            return [MAX_PREVIEW_BYTES, MAX_PREVIEW_VALUES + cloud_sample_values(value)]

        with pytest.raises(_DisplayLimit, match="preview_structure_limit"):
            _copy_json(value, budget())
        assert _copy_preview(value, budget()) == value
        evidence["items"][0]["extra"] = "not allowed"
        with pytest.raises(_DisplayLimit, match="preview_not_json"):
            _copy_preview(value, budget())
    finally:
        assert not scope.close()
        assert runtime.budget.used == 0
