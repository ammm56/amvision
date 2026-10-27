"""固定工件 50 项配方；共用原云/台面/同组基体，只连接现有节点。"""

import argparse
import json
from pathlib import Path

from backend.contracts.workflows.workflow_graph import WorkflowGraphTemplate
from tests.integration.metrology3d import (
    representative_recipe,
    workpiece_recipe as recipe,
)
from tests.integration.metrology3d.measurement_output import connect_measurement_output
from tests.metrology3d_transport_support import cloud_documents
from tests.point_cloud_support import options


def workpiece_documents(*, file=False, inspection="A_top_L"):
    """所有数值都计算；仅将指定对象的证据接到显示，未声称隐藏面板能减少捕获。"""
    if inspection not in {*recipe.STEEL, "S1", "S2"}:
        raise ValueError(inspection)
    template, app = cloud_documents(options().model_dump(mode="json") if file else None)
    graph = template.model_dump(mode="json")
    graph["display_name"] = "R5 full workpiece"

    def node(name, kind, settings=None, **parameters):
        if settings is not None:
            parameters["settings"] = settings.model_dump(mode="json")
        graph["nodes"].append(
            dict(
                node_id=name,
                node_type_id="custom.metrology3d." + kind,
                parameters=parameters,
            )
        )

    def link(a, port, b, target):
        graph["edges"].append(
            dict(
                edge_id=f"whole-{len(graph['edges'])}",
                source_node_id=a,
                source_port=port,
                target_node_id=b,
                target_port=target,
            )
        )

    for group, region in recipe.group_regions().items():
        rois = {r.roi_id: r.model_dump(mode="json") for r in region.rois}
        node(
            group + ".context",
            "crop-roi",
            source=dict(
                kind="parameters",
                roi=rois.pop(region.roi_id),
                bounds=list(rois.values()),
            ),
        )
        link("filter", "cloud", group + ".context", "cloud")
    for name, region in recipe.support_regions().items():
        rois = {r.roi_id: r.model_dump(mode="json") for r in region.rois}
        node(
            name + "-crop",
            "crop-roi",
            source=dict(
                kind="parameters",
                roi=rois.pop(region.roi_id),
                bounds=list(rois.values()),
            ),
        )
        node(name, "fit-plane", recipe.plane(name))
        group = (
            name.removesuffix(".B")
            if name.endswith(".B")
            else name.removesuffix(".T").rsplit("_", 1)[0]
        )
        link(
            "filter" if name == "D" else group + ".context",
            "cloud",
            name + "-crop",
            "cloud",
        )
        link(name + "-crop", "cloud", name, "cloud")
    node("frame", "build-frame", representative_recipe.frame())
    link("D", "features", "frame", "features")
    outputs = []
    for name in recipe.STEEL:
        base, top = name.rsplit("_", 1)[0] + ".B", name + ".T"
        for component, reference in (("H", base), ("Z", "D")):
            item = name + "." + component
            node(item, "measure-step", recipe.step(name, component))
            for source in (reference, top):
                link(source, "features", item, "features")
            link("frame", "pose", item, "pose")
            outputs.append(item)
            if name == inspection:
                link(item, "evidence", "preview", "evidence")
        node(name + ".boundary", "extract-boundary", recipe.contour(name))
        link(name.rsplit("_", 1)[0] + ".context", "cloud", name + ".boundary", "cloud")
        link("frame", "pose", name + ".boundary", "pose")
        for source in ("D", base, top):
            link(source, "features", name + ".boundary", "features")
        link(name + ".H", "evidence", name + ".boundary", "evidence")
        node(name + ".extents", "measure-extents", recipe.extents(name))
        link(name + ".boundary", "features", name + ".extents", "features")
        outputs.append(name + ".extents")
        if name == inspection:
            link(name + ".boundary", "features", "preview", "features")
            link(name + ".extents", "evidence", "preview", "evidence")
    for name in ("S1", "S2"):
        node(name + ".boundary", "extract-boundary", recipe.contour(name))
        link("filter", "cloud", name + ".boundary", "cloud")
        link("D", "features", name + ".boundary", "features")
        link("frame", "pose", name + ".boundary", "pose")
        node(name + ".circle", "fit-circle", recipe.circle(name))
        link(name + ".boundary", "features", name + ".circle", "features")
        node(name + ".diameter", "measure-hole", recipe.hole(name))
        link(name + ".circle", "features", name + ".diameter", "features")
        outputs.append(name + ".diameter")
        if name == inspection:
            for source in (name + ".boundary", name + ".circle"):
                link(source, "features", "preview", "features")
            link(name + ".diameter", "evidence", "preview", "evidence")
    connect_measurement_output(graph, outputs)
    # 单个有界总览；平面逐点分类不复制到整个工件结果中。
    for index, definition in enumerate(graph["nodes"]):
        definition["ui_state"] = dict(x=(index % 8) * 400, y=(index // 8) * 450)
        if definition["node_id"] == "preview":
            definition["parameters"]["point_limit"] = 500000
    return WorkflowGraphTemplate.model_validate(graph), app.model_copy(
        update={"display_name": "R5 full workpiece - " + inspection}
    )


def check_workpiece_body(body):
    """发布响应逐项对照独立几何已核查的冻结矩阵，不以运行成功代替量值正确。"""
    import pytest

    path = (
        Path(__file__).parents[3] / "docs/development/assets/r5-e/workpiece-matrix.json"
    )
    expected = json.loads(path.read_text("utf-8"))["items"]
    assert set(body) == {"code", "message", "data"}
    assert body["code"] == 0 and body["message"] == "measured"
    data = body["data"]
    assert set(data) == {"observation_id", "values", "items"} and data["observation_id"]
    actual = {item["item_id"]: item for item in data["items"]}
    assert len(actual) == len(data["items"]) == len(expected) == 50
    assert set(actual) == set(expected)
    for key, reference in expected.items():
        item = actual[key]
        assert item["valid"] == reference["valid"]
        assert item["reason"] == reference["reason"]
        assert item["unit"] == "mm"
        if reference["valid"]:
            assert item["value"] == pytest.approx(reference["value"], abs=1e-7)
        else:
            assert item["value"] is None
    assert data["values"] == {key: item["value"] for key, item in actual.items()}


def main():
    """导出正式页面可读取的配方文档，不写业务数据库。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--inspection", default="A_top_L", choices=[*recipe.STEEL, "S1", "S2"]
    )
    args = parser.parse_args()
    template, app = workpiece_documents(file=True, inspection=args.inspection)
    args.output.write_text(
        json.dumps(
            dict(
                format_id="amvision.workflow-app-document.v1",
                application=app.model_dump(mode="json"),
                template=template.model_dump(mode="json"),
            ),
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
