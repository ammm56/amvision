"""M3.2 严格参数和拓扑；测试阈值不作为节点默认值。"""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from backend.contracts.workflows.boundary3d import (
    BoundaryTopology,
    CircleSolverSettings,
    EvaluationPlane3d,
    ExtractBoundaryParameters,
    FitCircleParameters,
    FitLineParameters,
)


def evaluation(**changes):
    """显式测试空间，坐标轴不来自屏幕。"""
    return EvaluationPlane3d(
        **{
            **dict(
                frame_id="fixture",
                length_unit="mm",
                origin=[0, 0, 0],
                rotation=[[1, 0, 0], [0, 1, 0], [0, 0, 1]],
            ),
            **changes,
        }
    )


def line_parameters(**changes):
    """测试用完整 TLS 配方。"""
    return FitLineParameters(
        **{
            **dict(
                feature_id="edge",
                selection=dict(feature_id="boundary", segment_ids=["side"]),
                evaluation=evaluation(),
                positive_direction=[1, 0, 0],
                min_orientation_cosine=0.1,
                quality_policy=dict(
                    policy_id="line-test",
                    policy_version=1,
                    rules=[
                        dict(item_id="support_count", unit="1", lower=2),
                        dict(item_id="span", unit="mm", lower=0.01),
                        dict(item_id="direction_gap", unit="1", lower=0.1),
                        dict(item_id="plane_max_residual", unit="mm", upper=0.001),
                        dict(item_id="rms", unit="mm", upper=0.01),
                        dict(item_id="max_residual", unit="mm", upper=0.05),
                    ],
                ),
            ),
            **changes,
        }
    )


def circle_parameters(**changes):
    """测试用完整求解设置，不从失败结果反推放宽阈值。"""
    return FitCircleParameters(
        **{
            **dict(
                feature_id="circle",
                selection=dict(feature_id="boundary", segment_ids=["arc"]),
                evaluation=evaluation(),
                radius_range=(0.1, 100),
                max_arc_step=0.5,
                solver=dict(
                    ftol=1e-12, xtol=1e-12, gtol=1e-12, max_nfev=500, x_scale=[1, 1, 1]
                ),
                quality_policy=dict(
                    policy_id="circle-test",
                    policy_version=1,
                    rules=[
                        dict(item_id="support_count", unit="1", lower=3),
                        dict(item_id="angular_coverage", unit="rad", lower=1),
                        dict(item_id="jacobian_ratio", unit="1", lower=0.01),
                        dict(item_id="max_gap", unit="rad", upper=5.3),
                        dict(item_id="plane_max_residual", unit="mm", upper=0.001),
                        dict(item_id="rms", unit="mm", upper=0.01),
                        dict(item_id="max_residual", unit="mm", upper=0.05),
                    ],
                ),
            ),
            **changes,
        }
    )


def topology(count, *, segment_id="arc", closed=False):
    """构造明确的逻辑段，不以序号作为 feature_id。"""
    return BoundaryTopology(
        point_count=count,
        segments=[
            dict(
                segment_id=segment_id,
                start=0,
                count=count,
                closed=closed,
                role="unknown" if closed else "open",
                orientation="ccw" if closed else "open",
            )
        ],
    )


def test_parameters_roundtrip_and_missing_quality_are_rejected():
    """方法/质量记录可完整往返，缺必检条件不自动补默认。"""
    for parameters in (line_parameters(), circle_parameters()):
        cls = type(parameters)
        assert cls.model_validate_json(parameters.model_dump_json()) == parameters
        value = parameters.model_dump(mode="json")
        for index in range(len(value["quality_policy"]["rules"])):
            changed = deepcopy(value)
            changed["quality_policy"]["rules"].pop(index)
            with pytest.raises(ValidationError):
                cls.model_validate(changed)
        value["selection"]["segment_ids"] *= 2
        with pytest.raises(ValidationError, match="重复"):
            cls.model_validate(value)


def test_solver_and_geometry_reject_implicit_or_degenerate_configuration():
    """不能靠库隐式终止条件、半径倒置或错误坐标继续计算。"""
    with pytest.raises(ValidationError):
        CircleSolverSettings()
    with pytest.raises(ValidationError):
        circle_parameters(radius_range=(1, 1))
    with pytest.raises(ValidationError):
        circle_parameters(max_arc_step=3.2)
    with pytest.raises(ValidationError):
        line_parameters(positive_direction=[2, 0, 0])
    with pytest.raises(ValidationError):
        evaluation(rotation=[[1, 0, 0], [0, 1, 0], [0, 0, -1]])


@pytest.mark.parametrize(
    "change",
    [
        dict(start=1),
        dict(count=1),
        dict(closed=True),
        dict(orientation="ccw"),
        dict(role="inner"),
    ],
)
def test_topology_rejects_unrepresented_gaps_and_false_closed_segments(change):
    """区间、角色、旋向与点数不能互相矛盾。"""
    value = topology(3).model_dump(mode="json")
    value["segments"][0].update(change)
    with pytest.raises(ValidationError):
        BoundaryTopology.model_validate(value)


def test_extract_method_branch_is_closed_and_target_space_is_explicit():
    """本次候选 ID 不能替代目标 ROI，其他方法字段不能混入投影分支。"""
    region = dict(
        roi_id="window",
        rois=[
            dict(
                roi_id="window",
                frame_id="fixture",
                length_unit="mm",
                kind="box",
                geometry=dict(
                    center=[0, 0, 0],
                    rotation=[[1, 0, 0], [0, 1, 0], [0, 0, 1]],
                    size=[4, 4, 4],
                ),
            )
        ],
    )
    value = dict(
        feature_id="boundary",
        evaluation=evaluation(),
        region=region,
        surface=dict(
            alpha_radius=1,
            max_edge_length=1,
            max_normal_step=1,
            min_projected_area=0.01,
        ),
        method=dict(kind="projection"),
        targets=[dict(segment_id="outer", region=region, closed=True, role="outer")],
        quality_policy=dict(
            policy_id="test",
            policy_version=1,
            rules=[
                dict(item_id="support_count", unit="1", lower=2),
                dict(item_id="length", unit="mm", lower=0.1),
            ],
        ),
    )
    assert ExtractBoundaryParameters(**value).method.kind == "projection"
    changed = deepcopy(value)
    changed["method"]["normal"] = [0, 0, 1]
    with pytest.raises(ValidationError):
        ExtractBoundaryParameters(**changed)
    changed = deepcopy(value)
    changed["targets"][0]["region"]["rois"][0]["length_unit"] = "m"
    with pytest.raises(ValidationError, match="评价空间"):
        ExtractBoundaryParameters(**changed)
