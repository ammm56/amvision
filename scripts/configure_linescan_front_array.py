"""通过正式草稿 API 将正面验证流程改为可编辑托盘、首槽和二维阵列。"""

import argparse
import copy
import json

import httpx

from scripts.configure_linescan_3913_workflow import APP_ID, DATA
from backend.service.application.auth.default_local_auth_seeder import (
    DEFAULT_LOCAL_AUTH_TOKEN,
)

OUT = DATA / "validation/front-array"


def build(application, template):
    """仅替换配方输入和槽位来源，保留读码模型、参数及结果关联。"""
    application, template = copy.deepcopy(application), copy.deepcopy(template)
    nodes = {n["node_id"]: n for n in template["nodes"]}
    if "batch_detect" in nodes:
        # 已优化并可手工调参的配方不再重建，避免恢复旧的逐图推理链。
        return dict(application=application, template=template)
    ref = (
        nodes.get("recipe", {})
        .get("parameters", {})
        .get("fields", {})
        .get("reference_path", str(DATA / "validation/front-registered/reference.png"))
    )
    removed = {"recipe", "inspection_rois", "inspection_roi_list"}
    edges = [
        e
        for e in template["edges"]
        if e["source_node_id"] not in removed and e["target_node_id"] not in removed
    ]
    for name in removed:
        nodes.pop(name, None)

    def node(name, kind, **params):
        """统一用目录定义中的通用节点。"""
        nodes[name] = dict(
            node_id=name,
            node_type_id=kind,
            parameters=params,
            enabled=True,
            metadata={},
            ui_state={},
        )

    def edge(source, port, target, target_port):
        """单输入连线先替换已有连接，使脚本可重复执行。"""
        nonlocal edges
        edges = [
            e
            for e in edges
            if not (e["target_node_id"] == target and e["target_port"] == target_port)
        ]
        edges.append(
            dict(
                edge_id="pending",
                source_node_id=source,
                source_port=port,
                target_node_id=target,
                target_port=target_port,
            )
        )

    def preview(name, source, port, title):
        """每阶段的图片预览。"""
        node(
            name,
            "core.io.image-preview",
            title=title,
            response_transport_mode="inline-base64",
        )
        edge(source, port, name, "image")

    node("reference_path", "core.logic.string-value", value=ref)
    edge("reference_path", "value", "load_reference", "path")
    node(
        "tray_roi",
        "core.vision.roi-create",
        roi_id="tray",
        roi_kind="bbox",
        bbox_xyxy=[30, 60, 2370, 1760],
        display_name="托盘范围（参考坐标，可编辑）",
        debug_image_panel_enabled=True,
        debug_image_panel_transport_mode="inline-base64",
    )
    edge("align", "image", "tray_roi", "image")
    node("tray_roi_list", "core.vision.roi-list-create")
    edge("tray_roi", "roi", "tray_roi_list", "roi")
    node("tray_crop", "custom.opencv.crop-export")
    edge("tray_roi_list", "rois", "tray_crop", "rois")
    edge("align", "image", "tray_crop", "image")
    node("tray_image", "core.io.image-refs-item-get", index=0)
    edge("tray_crop", "crops", "tray_image", "images")
    # 配方只保存一个首槽；数组不再包含18份绝对坐标。
    seed = [
        [430, 155],
        [540, 155],
        [540, 410],
        [350, 410],
        [350, 510],
        [430, 510],
        [430, 665],
        [105, 665],
        [105, 390],
        [190, 390],
        [190, 220],
        [330, 220],
        [330, 310],
        [430, 310],
    ]
    node(
        "slot_seed",
        "core.vision.roi-create",
        roi_id="first-slot",
        roi_kind="polygon",
        polygon_xy=[[x - 30, y - 60] for x, y in seed],
        display_name="首槽检查范围（托盘局部坐标，可编辑）",
        debug_image_panel_enabled=True,
        debug_image_panel_transport_mode="inline-base64",
    )
    edge("tray_image", "image", "slot_seed", "image")
    node(
        "slot_array",
        "custom.opencv.roi-array",
        rows=3,
        columns=6,
        column_step_xy=[343, -3],
        row_step_xy=[4, 500],
        roi_id_prefix="slot",
        debug_image_panel_enabled=True,
        debug_image_panel_transport_mode="inline-base64",
    )
    edge("slot_seed", "roi", "slot_array", "roi")
    edge("tray_roi", "roi", "slot_array", "frame")
    edge("align", "image", "slot_array", "image")
    for name in ("compare_foreground", "slot_crops"):
        edge("slot_array", "rois", name, "rois")
    nodes["compare_foreground"]["parameters"].update(
        check_boundary=True, search_margin_pixels=8, max_outside_ratio=0.02
    )
    nodes["difference_gallery"]["parameters"]["title"] = (
        "逐槽差异：绿匹配 / 红缺失 / 橙多出 / 紫越界"
    )
    node("draw_slots", "custom.opencv.draw-rois", fill_alpha=0, draw_index=False)
    edge("align", "image", "draw_slots", "image")
    edge("slot_array", "rois", "draw_slots", "rois")
    preview("array_preview", "draw_slots", "image", "18槽阵列与编号")
    node(
        "tray_current",
        "custom.opencv.planar-transform-bridge",
        direction="source-a-to-source-b",
    )
    edge("locate", "transform", "tray_current", "transform")
    edge("tray_roi", "roi", "tray_current", "roi")
    node("draw_tray", "custom.opencv.draw-roi", fill_alpha=0)
    edge("overview", "image", "draw_tray", "image")
    edge("tray_current", "roi", "draw_tray", "roi")
    preview("tray_preview", "draw_tray", "image", "本次扫描的托盘范围")
    template.update(nodes=list(nodes.values()), edges=edges)
    for i, e in enumerate(edges):
        e["edge_id"] = f"e{i + 1:03}"
    stages = [
        (
            "01 原图 / 托盘定位",
            [
                ["decode_input", "input_image", "decoded_source", "overview"],
                ["circles", "locate", "align"],
                ["overview_preview", "draw_anchors", "anchors_preview", "pose_preview"],
                ["aligned_preview"],
            ],
        ),
        (
            "02 托盘 / 首槽 / 3×6阵列",
            [
                ["tray_roi", "tray_roi_list", "tray_crop", "tray_image"],
                ["slot_seed", "slot_array", "draw_slots", "array_preview"],
                ["tray_current", "draw_tray", "tray_preview"],
            ],
        ),
        (
            "03 放置检查 / 逐槽结果",
            [
                [
                    "reference_path",
                    "load_reference",
                    "compare_foreground",
                    "placement_items",
                ],
                ["slot_crops", "draw_inspection", "passed_items", "placement_preview"],
                ["slots_gallery", "inspection_preview", "difference_gallery"],
            ],
        ),
        (
            "04 正常工件 / 手选条码区域",
            [
                ["barcode_loop", "part_roi_value", "part_roi", "crop_part"],
                [
                    "part_image",
                    "part_display_encode",
                    "barcode_roi",
                    "barcode_roi_list",
                ],
                ["crop_search", "search_image", "search_preview", "search_image_value"],
                ["source_mapping", "source_id"],
            ],
        ),
        (
            "05 检测 / 外扩 / 读码",
            [
                ["detect_code", "code_regions", "filter_codes", "crop_code"],
                ["draw_detection", "code_grayscale", "decode_codes", "detection_value"],
                [
                    "detection_preview",
                    "code_crop_preview",
                    "code_values_preview",
                    "detection_values_preview",
                ],
            ],
        ),
        (
            "06 按槽位汇总",
            [
                [
                    "item_id_field",
                    "source_field",
                    "code_result_field",
                    "detection_field",
                ],
                ["roi_field", "code_item", "barcode_end", "barcodes_field"],
                ["pose_field", "inspection_field", "report", "report_preview"],
            ],
        ),
    ]
    groups = []
    assigned = set()
    for index, (title, rows) in enumerate(stages):
        x = 400 + index * 1760
        y = 80
        members = []
        for row in rows:
            for col, name in enumerate(row):
                if name not in nodes:
                    continue
                nodes[name]["ui_state"] = {
                    "x": x + 40 + col * 420,
                    "y": y,
                    "width": 350,
                }
                members.append(name)
            y += 1800 if "circles" in row else 1200
        assigned.update(members)
        groups.append(
            dict(
                group_id=f"stage-{index + 1}",
                name=title,
                enabled=True,
                rect=dict(x=x, y=0, width=1720, height=y + 40),
                member_node_ids=members,
                member_note_ids=[],
                membership_policy="full-containment",
                color=[
                    "#22b8cf",
                    "#fab005",
                    "#10b981",
                    "#7c5cfc",
                    "#22b8cf",
                    "#10b981",
                ][index],
                collapsed=False,
                locked=False,
                metadata={},
            )
        )
    template["groups"] = groups
    template["notes"] = [
        dict(
            note_id="guide",
            title="正面调试顺序",
            tone="info",
            rect=dict(x=400, y=-680, width=1500, height=560),
            content="01 定位使用参考圆心与本次检测圆心计算整盘位姿；参考点固定，本次位姿变化。02 托盘框在校正概览图上编辑；首槽在托盘裁图上编辑，ROI Array按行列向量输出18槽，框选和阵列参数均可修改。03 查看逐槽差异、偏移和角度。04 正常工件进入读码；条码框在工件图中编辑，初始1000×1000，不限制尺寸。05 检测框外扩后解码。06 所有结果按槽位标识汇总。\n\n定位图为原图1/8。二维结果不能证明没有翘起；阈值须经真实缺陷标定。只有正面，反面另建。",
        )
    ]
    template["description"] = (
        "3913正面：定位→可编辑托盘与首槽→3×6阵列→放置检查→正常工件读码。"
    )
    application["description"] = template["description"]
    application.setdefault("metadata", {}).setdefault("workflow_graph_editor", {})[
        "boundary_positions"
    ] = {"entry": {"x": 0, "y": 80}, "result": {"x": 11000, "y": 2480}}
    # 重建入口同样采用局部窗口直采样，不能把优化后的草稿写回逐件大图裁剪。
    from scripts.optimize_linescan_front_workflow import build as optimize_crops

    return optimize_crops(application, template)


def main():
    """验证后按需更新现有草稿，不发布或切换 Runtime。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    with httpx.Client(
        base_url="http://127.0.0.1:5600",
        headers={"Authorization": "Bearer " + DEFAULT_LOCAL_AUTH_TOKEN},
        timeout=90,
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
        payload = build(app, response.json()["template"])
        response = client.post(
            "/api/v1/workflows/applications/validate",
            json={"project_id": "project-1", **payload},
        )
        print("validate", response.status_code, response.text[:1500])
        response.raise_for_status()
        (OUT / "workflow-bundle.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), "utf-8"
        )
        if args.apply:
            response = client.put(url, json=payload)
            response.raise_for_status()
            print("saved", response.status_code)


if __name__ == "__main__":
    main()
