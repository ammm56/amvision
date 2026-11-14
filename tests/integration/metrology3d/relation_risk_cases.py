"""B13 风险代表配方；解析期望不调用关系算法生成。"""

from math import pi, sqrt

from tests.test_metrology3d_relations import parameters
from tests.test_metrology3d_plane import plane_parameters
from tests.integration.metrology3d.test_boundary_extraction import region


CASES = (
    "zero",
    "point-line-finite",
    "point-line-model",
    "point-plane-signed",
    "point-plane-outside",
    "line-line",
    "line-line-unique",
    "line-angle",
    "plane-angle",
)


def definition(case):
    """返回参数及独立期望；输入来自 z=x 与 z=x-4 的两块解析面。"""
    if case == "zero":
        return parameters(), 0.0, None
    if case.startswith("point-line"):
        finite = case.endswith("finite")
        return (
            parameters(
                "point-line",
                reference=dict(kind="coordinate", position=(3, 10, 0.5)),
                support_mode="finite" if finite else "model",
            ),
            None if finite else 2.5,
            "outside_support" if finite else None,
        )
    if case.startswith("point-plane"):
        outside = case.endswith("outside")
        return (
            parameters(
                "point-plane",
                reference=dict(
                    kind="coordinate", position=(1, 20 if outside else 0, 0)
                ),
                target=dict(kind="plane", feature_id="plane-a"),
                support_mode="finite",
                coverage=dict(
                    support_radius=3,
                    min_support_count=3,
                    max_triangle_edge=3,
                    max_plane_residual=0.001,
                ),
            ),
            None if outside else -1 / sqrt(2),
            "outside_support" if outside else None,
        )
    if case == "line-angle":
        return parameters("line-angle", projection=True, angle_mode="signed"), pi, None
    if case == "plane-angle":
        return (
            parameters(
                "plane-angle",
                reference=dict(kind="plane", feature_id="plane-a"),
                target=dict(kind="plane", feature_id="plane-b"),
                angle_mode="oriented",
            ),
            pi,
            None,
        )
    p = parameters("line-line", support_mode="finite")
    if case == "line-line-unique":
        data = p.model_dump(mode="json")
        data["quality_policy"]["rules"].append(
            dict(item_id="contacts_unique", unit="1", lower=1)
        )
        return type(p).model_validate(data), None, "insufficient_quality"
    if case != "line-line":
        raise ValueError(case)
    return p, 4.0, None


def add_models(graph, case, link):
    """只通过正式裁剪/拟合节点提供模型；不用伪造特征替代发布准入。"""
    if case == "line-angle":
        next(n for n in graph["nodes"] if n["node_id"] == "b")["parameters"][
            "settings"
        ]["positive_direction"] = [0, -1, 0]
    if not (case.startswith("point-plane") or case == "plane-angle"):
        return
    for suffix, center in (("a", 1), ("b", 5)):
        roi_id, plane_id = f"plane-roi-{suffix}", f"plane-{suffix}"
        graph["nodes"].extend(
            [
                dict(
                    node_id=roi_id,
                    node_type_id="custom.metrology3d.crop-roi",
                    parameters=dict(
                        source=dict(
                            kind="parameters",
                            roi=region(center=(center, 0, 1), size=(2.2, 6, 2.2))[
                                "rois"
                            ][0],
                        )
                    ),
                ),
                dict(
                    node_id=plane_id,
                    node_type_id="custom.metrology3d.fit-plane",
                    parameters=dict(
                        settings=plane_parameters(
                            feature_id=plane_id,
                            positive_normal=(0, 0, -1 if suffix == "b" else 1),
                        ).model_dump(mode="json")
                    ),
                ),
            ]
        )
        link("filter", "cloud", roi_id, "cloud")
        link(roi_id, "cloud", plane_id, "cloud")
        link(plane_id, "features", "dimension", "features")
        link(plane_id, "features", "preview", "features")
