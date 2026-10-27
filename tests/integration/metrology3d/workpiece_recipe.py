"""R5 完整工件的显式工程配置；仅用于固定装夹样本，不提供生产默认值。"""

from copy import deepcopy

from tests.integration.metrology3d import representative_recipe as representative
from tests.test_metrology3d_dimension_contracts import extent_parameters


# 拟面窗口位于左右片远离中央凸点的平坦带；查询为固定台面 U/V，非运行时质心。
# 每项依次为顶面 XYZ 范围、固定 U/V、台面最大延伸及完整边界搜索 XY。
STEEL = {
    "A_top_L": (
        [-35.5, -33.5, -21, -17.5, -15.2, -14],
        [-34.75, -19],
        10,
        [-37.4, -29, -23, -13.8],
    ),
    "A_top_R": (
        [-24, -22.5, -21, -17.5, -15.2, -13.8],
        [-23.5, -19],
        10,
        [-29.3, -21, -23, -13.8],
    ),
    "B_top_L": (
        [-5, -3.5, -38.5, -34.5, -14.6, -12.8],
        [-4.5, -36.5],
        20,
        [-6.8, 1.5, -40.4, -31.2],
    ),
    "B_top_R": (
        [6.5, 8, -38.5, -34.5, -14.6, -12.8],
        [7, -36.5],
        20,
        [1.3, 9.6, -40.4, -31.2],
    ),
    "A_bottom_L": (
        [-35, -33.5, -53, -51, -15.2, -13.4],
        [-34.5, -52],
        30,
        [-37.1, -28.6, -58.4, -48.9],
    ),
    "A_bottom_R": (
        [-24, -22.5, -54, -51, -15, -13],
        [-23.5, -52],
        30,
        [-29, -20.5, -58.4, -48.9],
    ),
    "B_bottom_L": (
        [-4.5, -3, -71.5, -68.5, -14.8, -12.8],
        [-4, -70],
        50,
        [-6.4, 2, -75.8, -66.1],
    ),
    "B_bottom_R": (
        [6.7, 8.2, -71.5, -68.5, -14.8, -12.8],
        [7.2, -70],
        50,
        [1.6, 9.9, -75.8, -66.1],
    ),
    "C_top_L": (
        [26, 27.5, -90.5, -87, -14, -11.8],
        [26.5, -89],
        60,
        [24.2, 32.6, -92.9, -83.5],
    ),
    "C_top_R": (
        [37.6, 39.1, -90.5, -87, -14, -11.8],
        [38.1, -89],
        60,
        [32, 40.7, -92.8, -83.5],
    ),
    "C_bottom_L": (
        [26.5, 28, -124.2, -121.2, -14, -11.8],
        [27, -123],
        25,
        [24.5, 33, -128.2, -118.4],
    ),
    "C_bottom_R": (
        [38, 39.4, -124.2, -121.2, -14, -11.8],
        [38.45, -123],
        25,
        [32.4, 41, -128.2, -118.4],
    ),
}
BODY = {
    "A_top": [[-34, -24, -28, -26, -16.5, -15.4]],
    # 原候选分别混入 X=[0,3]、[-30,-28] 的凹槽；显式使用两侧基体，不按残差删点。
    "B_top": [[-4, -0.5, -45, -42, -16, -14], [3.5, 7, -45, -42, -16, -14]],
    "A_bottom": [
        [-34, -30.5, -48, -45, -16.8, -15],
        [-27.5, -24, -48, -45, -16.8, -15],
    ],
    "B_bottom": [[-4, 7, -63, -61, -16, -14]],
    "C_top": [[28, 38, -100, -97, -15.7, -13.6]],
    "C_bottom": [[28, 38, -116, -112, -15.7, -13.6]],
}


def group_regions():
    """前置粗裁切包含本组全部最终 ROI；不是拟面支持，也不改变最终选点规则。"""
    regions = {}
    for group, body in BODY.items():
        boxes = list(body)
        for name, (top, _, _, xy) in STEEL.items():
            if name.rsplit("_", 1)[0] == group:
                boxes.extend(
                    [top, xy + ([-16.6, -14] if name == "A_top_L" else [-17.5, -11.5])]
                )
        envelope = [
            value
            for axis in range(3)
            for value in (
                min(box[2 * axis] for box in boxes),
                max(box[2 * axis + 1] for box in boxes),
            )
        ]
        regions[group] = representative.boxes(group + ".context", [envelope])
    return regions


def support_regions():
    """同组基体只拟合一次；原台面五窗及排除定义保持不变。"""
    regions = {"D": representative.supports()["D"]}
    regions.update(
        {
            name + ".B": representative.boxes(name + ".B", bounds)
            for name, bounds in BODY.items()
        }
    )
    regions.update(
        {
            name + ".T": representative.boxes(name + ".T", [config[0]])
            for name, config in STEEL.items()
        }
    )
    return regions


def plane(name):
    """同类平面的可辨识性和残差门禁与代表配方一致，不按结果反调。"""
    base = representative.plane(
        "D" if name == "D" else "T" if name.endswith(".T") else "B"
    )
    data = base.model_dump(mode="json")
    data["feature_id"] = name
    data["quality_policy"]["policy_id"] = "r5-" + name
    return type(base).model_validate(data)


def step(name, component):
    """H 使用本组基体，Z 使用同一次台面；被测顶面始终要求实测支持。"""
    group = name.rsplit("_", 1)[0]
    reference = group + ".B" if component == "H" else "D"
    base = representative.step(component, reference)
    data = base.model_dump(mode="json")
    data["item_id"] = name + "." + component
    data["mode"]["target_feature_id"] = name + ".T"
    data["mode"]["query"]["uv"] = STEEL[name][1]
    data["mode"]["reference_policy"]["max_extension_distance"] = (
        10 if component == "H" else STEEL[name][2]
    )
    return type(base).model_validate(data)


def contour(name):
    """每片动态中间高度和有限实测闭边界；S2 显式选择两侧开弧，不补缺口。"""
    base = representative.contour("A_top_L" if name in STEEL else "S1")
    data = deepcopy(base.model_dump(mode="json"))
    data["feature_id"] = name + "-boundary"
    if name in STEEL:
        group = name.rsplit("_", 1)[0]
        xy = STEEL[name][3]
        z = [-16.6, -14] if name == "A_top_L" else [-17.5, -11.5]
        region = representative.boxes(name, [xy + z]).model_dump(mode="json")
        data["region"] = region
        data["targets"] = [
            dict(segment_id=name, region=region, closed=True, role="outer")
        ]
        data["method"]["height"].update(
            item_id=name + ".H",
            reference_feature_id=group + ".B",
            target_feature_id=name + ".T",
        )
    elif name == "S2":
        data["region"] = representative.boxes(
            name, [[21.5, 43.5, -88, -77, -16, -12]]
        ).model_dump(mode="json")
        data["targets"] = [
            dict(
                segment_id=segment,
                closed=False,
                role="open",
                region=representative.boxes(segment, [bounds]).model_dump(mode="json"),
            )
            for segment, bounds in (
                ("S2-left", [22, 27, -87, -80.5, -16, -12]),
                ("S2-right", [37.8, 43, -87, -80.5, -16, -12]),
            )
        ]
    elif name != "S1":
        raise ValueError(name)
    return type(base).model_validate(data)


def circle(name):
    """S2 不降低角覆盖、辨识性或残差门禁，质量不足须保留无效。"""
    base = representative.circle()
    data = base.model_dump(mode="json")
    data["feature_id"] = name + "-circle"
    data["selection"] = dict(
        feature_id=name + "-boundary",
        segment_ids=[name] if name == "S1" else ["S2-left", "S2-right"],
    )
    return type(base).model_validate(data)


def hole(name):
    """孔径只消费已有圆特征，不重新拟合或用报告值替换。"""
    base = representative.hole()
    data = base.model_dump(mode="json")
    data["feature_id"] = name + "-circle"
    data["outputs"] = [dict(component="diameter", item_id=name + ".D")]
    return type(base).model_validate(data)


def extents(name):
    """投影 U 为宽、V 为长；保留该片边界失败及稳定结果 ID。"""
    return extent_parameters(
        evaluation=dict(kind="feature", frame_id="fixture", length_unit="mm"),
        source=dict(
            kind="boundary",
            selection=dict(feature_id=name + "-boundary", segment_ids=[name]),
        ),
        outputs=[
            dict(component="u", item_id=name + ".W"),
            dict(component="v", item_id=name + ".L"),
        ],
    )
