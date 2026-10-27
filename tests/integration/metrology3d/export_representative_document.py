"""输出可由现有页面导入的代表配方；不调用 API 或写入业务数据库。"""

import argparse
import json
from pathlib import Path

from tests.integration.metrology3d.representative_workflow import (
    representative_documents,
    representative_policy,
)


def main():
    """显式文件入口和页面显示配置仅供本轮隔离验收。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--policy-output", type=Path)
    args = parser.parse_args()
    template, app = representative_documents(file=True)
    app = app.model_copy(update={"display_name": "R5 A_top_L / S1"})
    positions = {
        "read": (0, 500),
        "filter": (350, 500),
        "D-crop": (700, 0),
        "D": (1050, 0),
        "B-crop": (700, 400),
        "B": (1050, 400),
        "T-crop": (700, 800),
        "T": (1050, 800),
        "frame": (1400, 0),
        "H": (1750, 400),
        "Z": (1750, 800),
        "A_top_L": (2100, 400),
        "S1": (2100, 1000),
        "extents": (2450, 400),
        "circle": (2450, 1000),
        "diameter": (2800, 1000),
        "preview": (3150, 500),
    }
    for node in template.nodes:
        x, y = positions[node.node_id]
        node.ui_state.update({"x": x, "y": y})
        if node.node_id == "preview":
            node.parameters["point_limit"] = 500000
    graph = template.model_dump(mode="json")
    # 密集总览不携带三份逐点平面分类；同一运行另用已有 Preview 检查拟面支持。
    for edge in graph["edges"]:
        if edge["target_node_id"] == "preview" and edge["source_node_id"] in {
            "D",
            "B",
            "T",
        }:
            edge["target_node_id"] = "plane-preview"
    graph["nodes"].append(
        dict(
            node_id="plane-preview",
            node_type_id="custom.metrology3d.cloud-preview",
            parameters=dict(point_limit=1000, color=dict(mode="solid")),
            ui_state=dict(x=1400, y=1300),
        )
    )
    graph["edges"].append(
        dict(
            edge_id="plane-inspection",
            source_node_id="filter",
            source_port="cloud",
            target_node_id="plane-preview",
            target_port="cloud",
        )
    )
    template = type(template).model_validate(graph)
    args.output.write_text(
        json.dumps(
            {
                "format_id": "amvision.workflow-app-document.v1",
                "application": app.model_dump(mode="json"),
                "template": template.model_dump(mode="json"),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    if args.policy_output:
        args.policy_output.write_text(
            representative_policy().model_dump_json(), encoding="utf-8"
        )


if __name__ == "__main__":
    main()
