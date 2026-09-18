"""显式转换旧图片 overlay 配置；仅处理文档，不作为运行时兼容路径。"""

from copy import deepcopy
from uuid import uuid4


def migrate_presentation_connections(bundle: dict) -> dict:
    """返回独立候选；保留布局及参数，冲突时拒绝覆盖，重复运行保持不变。"""
    result = deepcopy(bundle)
    application, template = result["application"], result["template"]
    nodes = {node["node_id"]: node for node in template["nodes"]}
    edges = template.setdefault("edges", [])
    displays = application.get("metadata", {}).get("app_mode", {}).get("displays", [])
    for display in displays:
        if "overlay" not in display:
            continue
        overlay = display["overlay"]
        if overlay is None:
            del display["overlay"]
            continue
        target, source = nodes.get(display["node_id"]), nodes.get(overlay.get("node_id"))
        if (not target or target["node_type_id"] != "core.io.image-preview"
                or not source or source["node_type_id"] != "core.io.value-display"
                or overlay.get("output_port") != "body" or overlay.get("position", "top-left") != "top-left"):
            raise ValueError(f"旧 overlay 引用无效：{display['node_id']}")
        bindings = [edge for edge in edges if edge["target_node_id"] == target["node_id"] and edge["target_port"] == "presentation"]
        public_inputs = [item for item in template.get("template_inputs", []) if item["target_node_id"] == target["node_id"] and item["target_port"] == "presentation"]
        if public_inputs or len(bindings) > 1 or any(
            edge["source_node_id"] != source["node_id"] or edge["source_port"] != "body" for edge in bindings
        ):
            raise ValueError(f"Presentation 已有不同来源：{target['node_id']}")
        if not bindings:
            edges.append(dict(edge_id=f"presentation-{uuid4().hex}", source_node_id=source["node_id"],
                              source_port="body", target_node_id=target["node_id"], target_port="presentation", metadata={}))
        del display["overlay"]
    return result


def main() -> None:
    """从导出 bundle 生成新文件；不覆盖原始文档或修改现场服务。"""
    import argparse
    import json
    from pathlib import Path

    parser = argparse.ArgumentParser(description="将旧 App Mode overlay 转为 Presentation 连线")
    parser.add_argument("--input", required=True, type=Path, help="包含 application/template 的 JSON")
    parser.add_argument("--output", required=True, type=Path, help="新的候选文档路径，不覆盖已有文件")
    args = parser.parse_args()
    candidate = migrate_presentation_connections(json.loads(args.input.read_text(encoding="utf-8")))
    encoded = json.dumps(candidate, ensure_ascii=False, indent=2, allow_nan=False)
    with args.output.open("x", encoding="utf-8") as stream:
        stream.write(encoded)


if __name__ == "__main__":
    main()
