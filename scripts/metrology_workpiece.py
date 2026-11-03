"""导出普通 Workflow 编辑器可导入的完整工件配方，不依赖测试模块。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from backend.contracts.workflows.workflow_graph import (
    FlowApplication,
    WorkflowGraphTemplate,
)

EXAMPLES = Path(__file__).resolve().parents[1] / "docs/examples/workflows"


def build_documents(
    *, input_kind: str = "file", view: str = "full"
) -> tuple[WorkflowGraphTemplate, FlowApplication]:
    """复用同一冻结图；只切换文件/数组入口及显式显示支路。"""
    if input_kind not in {"file", "array"} or view not in {"full", "numeric"}:
        raise ValueError("input_kind 需要 file/array，view 需要 full/numeric")
    graph = json.loads(
        (EXAMPLES / "lithium_workpiece.template.json").read_text("utf-8")
    )
    app = json.loads(
        (EXAMPLES / "lithium_workpiece.application.json").read_text("utf-8")
    )
    suffix = f"{input_kind}-{view}"
    graph["template_id"] += "-" + suffix
    app["application_id"] = "lithium-workpiece-" + suffix
    app["display_name"] = "锂电工件测量 · " + (
        "文件" if input_kind == "file" else "同机数组"
    )
    app["template_ref"] = dict(
        template_id=graph["template_id"],
        template_version=graph["template_version"],
        source_uri="lithium_workpiece.template.json",
    )
    removed = set()
    if input_kind == "array":
        removed.add("read")
        source = graph["template_inputs"][0]
        source.update(
            payload_type_id="point-cloud-ref.v1",
            target_node_id="filter",
            target_port="cloud",
        )
        binding = next(b for b in app["bindings"] if b["direction"] == "input")
        binding["config"] = {"payload_type_id": "point-cloud-ref.v1"}
        binding["metadata"]["payload_type_id"] = "point-cloud-ref.v1"
        binding["metadata"]["display_name"] = "完整点云数组"
        source["display_name"] = "完整点云数组"
        app["description"] = (
            "同机完整点云数组输入；固定装夹；工程限值，不代表图纸公差。"
        )
    if view == "numeric":
        removed.add("preview")
        app["display_name"] += " · 数值"
    graph["nodes"] = [n for n in graph["nodes"] if n["node_id"] not in removed]
    graph["edges"] = [
        e
        for e in graph["edges"]
        if not {e["source_node_id"], e["target_node_id"]} & removed
    ]
    for group in graph["groups"]:
        group["member_node_ids"] = [
            n for n in group["member_node_ids"] if n not in removed
        ]
    app["metadata"]["app_mode"]["displays"] = [
        d
        for d in app["metadata"]["app_mode"]["displays"]
        if d["node_id"] not in removed
    ]
    return WorkflowGraphTemplate.model_validate(graph), FlowApplication.model_validate(
        app
    )


def app_document(*, input_kind: str = "file", view: str = "full") -> dict:
    """生成既有前端文档格式；没有本机路径、数据库 ID 或测试注册器。"""
    template, application = build_documents(input_kind=input_kind, view=view)
    return dict(
        format_id="amvision.workflow-app-document.v1",
        application=application.model_dump(mode="json"),
        template=template.model_dump(mode="json"),
    )


def main() -> None:
    """只写指定的新文档；覆盖必须显式选择，不创建或启动任何服务。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--input-kind", choices=("file", "array"), default="file")
    parser.add_argument("--view", choices=("full", "numeric"), default="full")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    document = app_document(input_kind=args.input_kind, view=args.view)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w" if args.overwrite else "x", encoding="utf-8") as stream:
        json.dump(document, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(args.output.resolve())


if __name__ == "__main__":
    main()
