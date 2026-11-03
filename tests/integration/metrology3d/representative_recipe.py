"""固定装夹完整样本的代表配方；仅测试使用，不注册生产默认或工件算法。"""

import numpy as np

from backend.contracts.workflows.boundary3d import FitCircleParameters
from backend.contracts.workflows.dimension3d_parameters import MeasureHoleParameters
from backend.contracts.workflows.geometry3d import (
    BuildFrameParameters,
    CropCloudParameters,
    FitPlaneParameters,
)
from backend.contracts.workflows.measurement3d_parameters import MeasureStepParameters
from tests.integration.metrology3d.test_boundary_extraction import extract_parameters


def boxes(name, bounds):
    """显式 XYZ 闭区间生成既有 box/union 参数；不进行点选择。"""
    rois = []
    for index, values in enumerate(bounds):
        low, high = np.asarray(values)[::2], np.asarray(values)[1::2]
        rois.append(
            dict(
                roi_id=f"{name}-{index}",
                kind="box",
                frame_id="fixture",
                length_unit="mm",
                geometry=dict(
                    center=(low + high) / 2, size=high - low, rotation=np.eye(3)
                ),
            )
        )
    rois.append(
        dict(
            roi_id=name,
            kind="union",
            frame_id="fixture",
            length_unit="mm",
            geometry=dict(roi_ids=[r["roi_id"] for r in rois]),
        )
    )
    return CropCloudParameters(roi_id=name, rois=rois)


def supports():
    """D3 保留孔列两侧台面；B 避开上沿凹处，T 取远离中央凸起的左侧平面。"""
    result = {
        "D": boxes(
            "D",
            [
                [-45, -37, -145, -125, -17, -16],
                [-12, 20, -145, -132, -16.5, -15],
                [22, 28, -30, -4, -16, -14.5],
                [39, 44, -30, -4, -16, -14.5],
                [-12, 24, -25, -4, -16.5, -15],
                [-44, -37, -12, -3, -17, -16],
            ],
        ),
        "B": boxes("B", [[-34, -24, -28, -26, -16.5, -15.4]]),
        "T": boxes("T", [[-35.5, -33.5, -21, -17.5, -15.2, -14]]),
    }
    datum = result["D"].model_dump(mode="json")
    for roi, name in zip(
        datum["rois"][:-1], ("D1", "D2", "D3-left", "D3-right", "D4", "D5")
    ):
        roi["roi_id"] = name
    datum["rois"].insert(
        -1,
        dict(
            roi_id="D3",
            kind="union",
            frame_id="fixture",
            length_unit="mm",
            geometry=dict(roi_ids=["D3-left", "D3-right"]),
        ),
    )
    datum["rois"][-1]["geometry"]["roi_ids"] = ["D1", "D2", "D3", "D4", "D5"]
    result["D"] = CropCloudParameters.model_validate(datum)
    return result


def plane(name):
    """全支持 SVD；限定已选平面的几何一致性，不宣称量具准确度。"""
    rms, maximum = (0.025, 0.12) if name == "D" else (0.02, 0.08)
    return FitPlaneParameters(
        feature_id=name,
        positive_normal=[0, 0, 1],
        min_orientation_cosine=0.99,
        algorithm=dict(kind="svd"),
        quality_policy=dict(
            policy_id=f"r5-{name}",
            policy_version=1,
            rules=[
                dict(item_id="inlier_count", unit="1", lower=100),
                dict(item_id="tangent_ratio", unit="1", lower=0.01),
                dict(item_id="normal_gap", unit="1", lower=0.01),
                dict(item_id="rms", unit="mm", upper=rms),
                dict(item_id="max_residual", unit="mm", upper=maximum),
            ],
        ),
    )


def frame():
    """原点投影及源 +X/+Z；不使用台面质心建立新坐标。"""
    return BuildFrameParameters(
        pose_id="datum",
        target_frame_id="part",
        primary_feature_id="D",
        positive_z=[0, 0, 1],
        origin=dict(kind="anchor-projection", anchor=[0, 0, 0]),
        x_axis=dict(kind="direction", direction=[1, 0, 0]),
        quality_policy=dict(
            policy_id="r5-frame",
            policy_version=1,
            rules=[
                dict(item_id=name, unit="1", lower=0.99)
                for name in ("axis_sine", "x_alignment", "z_alignment")
            ],
        ),
    )


def step(item_id, reference):
    """固定 U/V 位于所选钢片平面；有限延伸仅用于 D 或 B 基准。"""
    rules = []
    for side in ("reference", "target"):
        for name, unit, limits in (
            ("count", "1", dict(lower=10)),
            ("covered", "1", dict(lower=1)),
            ("direction_cosine", "1", dict(lower=0.99)),
            ("nearest_distance", "mm", dict(upper=0.05)),
            ("triangle_edge", "mm", dict(upper=0.1)),
            ("max_residual", "mm", dict(upper=0.08)),
        ):
            rules.append(dict(item_id=f"{side}_{name}", unit=unit, **limits))
    return MeasureStepParameters(
        item_id=item_id,
        frame_id="fixture",
        length_unit="mm",
        mode=dict(
            kind="directional-planes",
            reference_feature_id=reference,
            target_feature_id="T",
            query=dict(
                kind="pose-uv",
                pose_id="datum",
                target_frame_id="part",
                uv=[-34.75, -19],
            ),
            support_radius=0.15,
            reference_policy=dict(kind="plane-extension", max_extension_distance=10),
            quality_policy=dict(
                policy_id="r5-local-support", policy_version=1, rules=rules
            ),
        ),
    )


def contour(name):
    """搜索区包含完整过渡两侧；目标选择规则不自动选最长段或填缺口。"""
    steel = name == "A_top_L"
    region = (
        boxes(name, [[-37.4, -29, -23, -13.8, -16.6, -14]])
        if steel
        else boxes(name, [[-9, 12.5, -82, -72, -17.1, -13.5]])
    )
    target_region = (
        region
        if steel
        else boxes(
            "S1-arc",
            [
                [-8.4, -6, -78, -72.6, -17.1, -13.5],
                [-6.5, 10, -81.3, -76, -17.1, -13.5],
                [10, 12.2, -78, -72.6, -17.1, -13.5],
            ],
        )
    )
    return extract_parameters(
        feature_id=f"{name}-boundary",
        evaluation=dict(
            kind="pose",
            frame_id="fixture",
            length_unit="mm",
            pose_id="datum",
            target_frame_id="part",
        ),
        region=region,
        method=dict(
            kind="pose-contour",
            reference_feature_id="D",
            numeric_tolerance=1e-8,
            height=dict(
                kind="measurement-ratio",
                item_id="H",
                reference_feature_id="B",
                target_feature_id="T",
                ratio=0.5,
                order="target-above",
            )
            if steel
            else dict(kind="fixed", value=0.25),
        ),
        # 相邻扫描点跨钢片陡边可相差 1.69 mm；不能套用平面噪声限值。
        # 仍限制投影连接边为 0.1 mm，缺失大间隔不会因此被桥接。
        surface=dict(
            alpha_radius=0.06,
            max_edge_length=0.1,
            max_normal_step=2.0 if steel else 0.75,
            min_projected_area=1e-8,
        ),
        targets=[
            dict(
                segment_id=name,
                region=target_region,
                closed=steel,
                role="outer" if steel else "open",
            )
        ],
        quality_policy=dict(
            policy_id="r5-boundary",
            policy_version=1,
            rules=[
                dict(item_id="support_count", unit="1", lower=10),
                dict(item_id="length", unit="mm", lower=1),
            ],
        ),
    )


def circle():
    """显式选定下半圆弧；半径范围是特征识别约束，不是产品公差。"""
    return FitCircleParameters(
        feature_id="S1-circle",
        selection=dict(feature_id="S1-boundary", segment_ids=["S1"]),
        evaluation=dict(kind="feature", frame_id="fixture", length_unit="mm"),
        radius_range=[9, 11],
        max_arc_step=0.1,
        solver=dict(
            ftol=1e-12, xtol=1e-12, gtol=1e-12, max_nfev=500, x_scale=[1, 1, 1]
        ),
        quality_policy=dict(
            policy_id="r5-circle",
            policy_version=1,
            rules=[
                dict(item_id="support_count", unit="1", lower=100),
                dict(item_id="angular_coverage", unit="rad", lower=2.5),
                dict(item_id="jacobian_ratio", unit="1", lower=0.05),
                dict(item_id="max_gap", unit="rad", upper=3.8),
                dict(item_id="plane_max_residual", unit="mm", upper=1e-7),
                dict(item_id="rms", unit="mm", upper=0.03),
                dict(item_id="max_residual", unit="mm", upper=0.1),
            ],
        ),
    )


def hole():
    """直径节点只消费拟圆结果，不再次拟合。"""
    return MeasureHoleParameters(
        outputs=[dict(component="diameter", item_id="S1.D")],
        feature_id="S1-circle",
        target_kind="open-arc",
        evaluation=dict(kind="feature", frame_id="fixture", length_unit="mm"),
        display_direction=dict(kind="axis", axis="u"),
        quality_policy=dict(
            policy_id="r5-diameter",
            policy_version=1,
            rules=[dict(item_id="geometry_usable", unit="1", lower=1)],
        ),
    )
