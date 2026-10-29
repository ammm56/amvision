"""显式优化正面工作流的裁剪链；保留可编辑搜索框和逐槽来源，不改发布版本。"""

import argparse
import copy
import json

import httpx

from backend.service.application.auth.default_local_auth_seeder import (
    DEFAULT_LOCAL_AUTH_TOKEN,
)
from scripts.configure_linescan_3913_workflow import APP_ID, DATA


def build(application, template, deployment_id=None):
    """参考工件只裁一次；循环直接采样局部搜索框，保持原像素与坐标链。"""
    application, template = copy.deepcopy(application), copy.deepcopy(template)
    nodes = {n["node_id"]: n for n in template["nodes"]}
    if "batch_detect" in nodes:
        if deployment_id:
            nodes["batch_detect"]["parameters"]["deployment_instance_id"] = (
                deployment_id
            )
        return dict(application=application, template=template)
    nodes.pop("barcode_roi_list", None)
    removed_targets = {
        "crop_part",
        "crop_search",
        "editor_slot_value",
        "editor_slot_roi",
        "barcode_context",
        "barcode_context_items",
        "barcode_passed_field",
        "barcode_loop",
    }
    edges = [
        e
        for e in template["edges"]
        if e["source_node_id"] != "barcode_roi_list"
        and e["target_node_id"] not in removed_targets | {"barcode_roi_list"}
    ]

    def node(name, kind, **parameters):
        """增加通用节点，不在处理器中固化槽位或条码配置。"""
        nodes[name] = dict(
            node_id=name,
            node_type_id=kind,
            parameters=parameters,
            enabled=True,
            metadata={},
            ui_state={},
        )

    def edge(source, port, target, target_port):
        """创建明确的端口连接。"""
        edges.append(
            dict(
                edge_id="pending",
                source_node_id=source,
                source_port=port,
                target_node_id=target,
                target_port=target_port,
            )
        )

    node("editor_slot_value", "core.logic.value-field-extract", path="items.0.source")
    node("editor_slot_roi", "core.vision.roi-create")
    edge("slot_array", "summary", "editor_slot_value", "value")
    edge("editor_slot_value", "value", "editor_slot_roi", "value")
    edge("editor_slot_roi", "roi", "crop_part", "roi")
    edge("decoded_source", "image", "crop_part", "image")
    edge("locate", "transform", "crop_part", "transform")
    node(
        "crop_search",
        "custom.opencv.mapped-roi-crop",
        **nodes["crop_part"]["parameters"],
    )
    edge("decoded_source", "image", "crop_search", "image")
    edge("locate", "transform", "crop_search", "transform")
    edge("part_roi", "roi", "crop_search", "roi")
    edge("barcode_roi", "roi", "crop_search", "window_roi")
    # 显式组装循环上下文，使框选和正常项两条分支都在 Start 前完成。
    # 不依赖节点位置或数组存储顺序决定执行先后。
    node("barcode_passed_field", "core.logic.object-field", key="passed_items")
    node("barcode_context", "core.logic.object-build")
    node("barcode_context_items", "core.logic.value-field-extract", path="passed_items")
    edge("passed_items", "value", "barcode_passed_field", "value")
    edge("barcode_passed_field", "field", "barcode_context", "entries")
    edge("roi_field", "field", "barcode_context", "entries")
    edge("barcode_context", "value", "barcode_context_items", "value")
    edge("barcode_context_items", "value", "barcode_loop", "items")
    if deployment_id:
        nodes["detect_code"]["parameters"]["deployment_instance_id"] = deployment_id

    # 参考图、可编辑窗口和逐槽采样依次排列，显示用途与检测用途可直接查看。
    group = next(g for g in template["groups"] if g["group_id"] == "stage-4")
    rows = [
        ["editor_slot_value", "editor_slot_roi", "crop_part", "part_image"],
        ["part_display_encode", "barcode_roi", "barcode_passed_field", "roi_field"],
        ["barcode_context", "barcode_context_items"],
        ["barcode_loop", "part_roi_value", "part_roi", "crop_search"],
        ["search_image", "search_preview", "search_image_value", "source_mapping"],
        ["source_id"],
    ]
    members = []
    for row_index, row in enumerate(rows):
        for col, name in enumerate(row):
            nodes[name]["ui_state"] = dict(
                x=group["rect"]["x"] + 40 + col * 420,
                y=80 + row_index * 1200,
                width=350,
            )
            members.append(name)
    group["member_node_ids"] = members
    group["rect"]["height"] = 7320
    for other in template["groups"]:
        if other is not group:
            other["member_node_ids"] = [
                name for name in other["member_node_ids"] if name not in members
            ]
    for i, e in enumerate(edges):
        e["edge_id"] = f"e{i + 1:03}"
    template.update(nodes=list(nodes.values()), edges=edges)
    assigned = [
        name for group in template["groups"] for name in group["member_node_ids"]
    ]
    assert len(assigned) == len(set(assigned)) and set(assigned) == set(nodes)
    return dict(application=application, template=template)


def main():
    """经正式校验保存草稿；可显式切换已验证的模型部署。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--deployment-id")
    parser.add_argument("--batch", action="store_true")
    args = parser.parse_args()
    out = DATA / "validation/front-performance"
    out.mkdir(parents=True, exist_ok=True)
    with httpx.Client(
        base_url="http://127.0.0.1:5600",
        timeout=90,
        headers={"Authorization": "Bearer " + DEFAULT_LOCAL_AUTH_TOKEN},
    ) as client:
        url = f"/api/v1/workflows/projects/project-1/applications/{APP_ID}"
        response = client.get(url)
        response.raise_for_status()
        app = response.json()["application"]
        ref = app["template_ref"]
        response = client.get(
            f"/api/v1/workflows/projects/project-1/templates/{ref['template_id']}/versions/{ref['template_version']}"
        )
        response.raise_for_status()
        payload = build(app, response.json()["template"], args.deployment_id)
        if args.batch and not any(
            node["node_id"] == "batch_detect" for node in payload["template"]["nodes"]
        ):
            from scripts.linescan_batch_variant import build as build_batch

            payload = build_batch(**payload)
        response = client.post(
            "/api/v1/workflows/applications/validate",
            json={"project_id": "project-1", **payload},
        )
        print("validate", response.status_code, response.text[:1500])
        response.raise_for_status()
        (out / "workflow-bundle.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), "utf-8"
        )
        if args.apply:
            response = client.put(url, json=payload)
            response.raise_for_status()
            print("saved", response.status_code)


if __name__ == "__main__":
    main()
