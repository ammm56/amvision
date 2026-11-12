"""配置 3913 正面独立验证工作流；产品配方只在开发数据中，不进入通用节点。"""

import argparse
import json
from pathlib import Path

import httpx

from backend.service.application.auth.default_local_auth_seeder import (
    DEFAULT_LOCAL_AUTH_TOKEN,
)

APP_ID = "workflow-app-20261028070103"
ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/files/developer/线扫16K读码检测/3913"


def build(application, template):
    """使用六行圆心定位，逐槽检查；正面读码，不含反面分支。"""
    recipe = json.loads(
        (DATA / "validation/front-registered/recipe.json").read_text("utf-8")
    )
    nodes, edges = [], []

    def node(name, kind, x, y, **parameters):
        """添加标准节点，位置仅用于显示。"""
        nodes.append(
            {
                "node_id": name,
                "node_type_id": kind,
                "parameters": parameters,
                "enabled": True,
                "ui_state": {"x": x, "y": y, "width": 280},
                "metadata": {},
            }
        )

    def edge(source, port, target, target_port):
        """按明确端口建立连线。"""
        edges.append(
            {
                "edge_id": f"e{len(edges) + 1:03}",
                "source_node_id": source,
                "source_port": port,
                "target_node_id": target,
                "target_port": target_port,
            }
        )

    node("decode_input", "core.io.image-base64-decode", 350, 450)
    node("input_image", "core.logic.image-ref-coalesce", 700, 150, allow_empty=False)
    edge("decode_input", "image", "input_image", "fallback")
    node(
        "overview",
        "custom.opencv.resize",
        1050,
        150,
        width=2500,
        height=2048,
        interpolation="area",
    )
    edge("input_image", "image", "overview", "image")
    node("circles", "custom.opencv.hough-circles", 1400, 150, **recipe["hough"])
    edge("overview", "image", "circles", "image")
    node(
        "locate",
        "custom.opencv.circle-pattern-locate",
        1750,
        150,
        **recipe["localization"],
    )
    edge("circles", "circles", "locate", "circles")
    node(
        "align",
        "custom.opencv.planar-transform-bridge",
        2100,
        150,
        direction="source-b-to-source-a",
        output_width=2500,
        output_height=2048,
        fit_output_bounds=False,
        interpolation="linear",
        border_mode="constant",
        border_value=255,
    )
    edge("overview", "image", "align", "image")
    edge("locate", "transform", "align", "transform")
    node("draw_anchors", "custom.opencv.draw-circles", 1750, -400)
    edge("overview", "image", "draw_anchors", "image")
    edge("circles", "circles", "draw_anchors", "circles")
    node(
        "anchors_preview",
        "core.io.image-preview",
        2100,
        -400,
        title="托盘圆定位",
        response_transport_mode="inline-base64",
    )
    edge("draw_anchors", "image", "anchors_preview", "image")
    node(
        "recipe",
        "core.logic.object-build",
        1050,
        950,
        fields={
            "reference_path": recipe["reference_path"],
            "inspection_rois": recipe["inspection_rois"],
            "barcode_rois": recipe["barcode_rois"],
        },
    )
    for name, y in [
        ("reference_path", 550),
        ("inspection_rois", 950),
        ("barcode_rois", 1700),
    ]:
        node(name, "core.logic.value-field-extract", 1400, y, path=name)
        edge("recipe", "value", name, "value")
    node("load_reference", "core.io.image-load-local", 1750, 550)
    edge("reference_path", "value", "load_reference", "path")
    node("inspection_roi_list", "core.vision.roi-list-create", 1750, 950)
    edge("inspection_rois", "value", "inspection_roi_list", "items")
    edge("load_reference", "image", "inspection_roi_list", "image")
    node(
        "compare_foreground",
        "custom.opencv.roi-foreground-compare",
        2450,
        150,
        threshold=80,
        foreground="dark",
        tolerance_pixels=2,
        min_reference_area=500,
        max_missing_ratio=0.05,
        max_excess_ratio=0.05,
    )
    edge("align", "image", "compare_foreground", "image")
    edge("load_reference", "image", "compare_foreground", "reference_image")
    edge("inspection_roi_list", "rois", "compare_foreground", "rois")
    node(
        "draw_inspection",
        "custom.opencv.draw-regions",
        2800,
        150,
        color_by="class-name",
        class_colors={
            "within_tolerance": "#087A56",
            "outside_tolerance": "#E04444",
            "invalid_reference": "#D98B00",
        },
        draw_score=False,
        draw_masks=False,
        draw_polygons=True,
        draw_boxes=False,
        draw_class_name=False,
        line_thickness=3,
        font_scale=0.6,
    )
    edge("align", "image", "draw_inspection", "image")
    edge("compare_foreground", "regions", "draw_inspection", "regions")
    node(
        "inspection_preview",
        "core.io.image-preview",
        3150,
        150,
        title="正面18槽放置检查",
        response_transport_mode="inline-base64",
    )
    edge("draw_inspection", "image", "inspection_preview", "image")
    node("placement_items", "core.logic.value-field-extract", 2800, 700, path="items")
    edge("compare_foreground", "summary", "placement_items", "value")
    node(
        "passed_items",
        "core.logic.list-filter",
        3150,
        700,
        condition={"path": "result.passed", "operator": "eq", "right": True},
    )
    edge("placement_items", "value", "passed_items", "items")
    node(
        "passed_ids",
        "core.logic.list-map",
        3500,
        700,
        path="item_id",
        skip_missing=False,
    )
    edge("passed_items", "value", "passed_ids", "items")
    node(
        "crop_search",
        "custom.opencv.mapped-roi-crop",
        3850,
        1700,
        coordinate_scale=8,
        interpolation="linear",
        maximum_total_pixels=18000000,
    )
    edge("input_image", "image", "crop_search", "image")
    edge("locate", "transform", "crop_search", "transform")
    edge("barcode_rois", "value", "crop_search", "roi_items")
    edge("passed_ids", "value", "crop_search", "selected_ids")
    node("search_items", "core.io.image-refs-to-value-list", 4200, 1700)
    edge("crop_search", "crops", "search_items", "images")
    node("barcode_loop", "core.logic.for-each-start", 4550, 1700)
    edge("search_items", "items", "barcode_loop", "items")
    node("search_image", "core.logic.value-to-image-ref", 4900, 1700)
    edge("barcode_loop", "item", "search_image", "value")
    node(
        "detect_code",
        "core.model.detection",
        5250,
        1700,
        score_threshold=0.3,
        deployment_instance_id="deployment-instance-bf7694d0436f4544b7682d0e42d4656a",
        return_preview_image_base64=False,
    )
    edge("search_image", "image", "detect_code", "image")
    node("code_regions", "core.vision.detections-to-regions", 5250, 2100)
    edge("detect_code", "detections", "code_regions", "detections")
    node(
        "filter_codes",
        "core.vision.regions-select-best",
        5600,
        2100,
        strategy="highest-score",
        class_names=["dmcode", "qrcode"],
    )
    edge("code_regions", "regions", "filter_codes", "regions")
    node("code_grayscale", "custom.opencv.channel-select", 5250, 1300, channel_index=2)
    edge("search_image", "image", "code_grayscale", "image")
    node("crop_code", "custom.opencv.crop-export", 5600, 1700, box_padding=40)
    edge("code_grayscale", "image", "crop_code", "image")
    edge("filter_codes", "regions", "crop_code", "regions")
    node(
        "decode_codes",
        "custom.barcode.crop-decode",
        5950,
        1700,
        format="data-matrix",
        binarizer="local-average",
        decode_scale=2,
        try_rotate=True,
        try_invert=True,
        try_downscale=True,
    )
    edge("crop_code", "crops", "decode_codes", "crops")
    for name, path, y in [
        ("source_id", "roi_id", 2450),
        ("source_mapping", "mapped_source", 2800),
    ]:
        node(name, "core.logic.value-field-extract", 4900, y, path=path)
        edge("barcode_loop", "item", name, "value")
    node("code_item", "core.logic.object-build", 6650, 1700)
    for name, source, port, key, y in [
        ("item_id_field", "source_id", "value", "item_id", 2450),
        ("source_field", "source_mapping", "value", "source", 2800),
        ("code_result_field", "decode_codes", "summary", "result", 1700),
        ("detection_field", "filter_codes", "summary", "localization", 2100),
    ]:
        node(name, "core.logic.object-field", 6300, y, key=key)
        edge(source, port, name, "value")
        edge(name, "field", "code_item", "entries")
    node("barcode_end", "core.logic.for-each-end", 7000, 1700)
    edge("code_item", "value", "barcode_end", "result")
    node(
        "report",
        "core.logic.object-build",
        8050,
        700,
        fields={
            "format_id": "amvision.linescan-validation.v1",
            "face": "front",
            "expected_count": 18,
            "height_assessment": "not_measured",
            "validation_stage": "reference-and-controlled-perturbations",
            "recipe_source_image_size": [20000, 16384],
            "inspection_image_size": [2500, 2048],
        },
    )
    for name, source, port, key, y in [
        ("pose_field", "locate", "summary", "tray_localization", 150),
        ("inspection_field", "compare_foreground", "summary", "placement_2d", 700),
        ("selection_field", "crop_search", "summary", "barcode_selection", 1100),
        ("barcodes_field", "barcode_end", "results", "barcodes", 1700),
    ]:
        node(name, "core.logic.object-field", 7700, y, key=key)
        edge(source, port, name, "value")
        edge(name, "field", "report", "entries")
    node(
        "report_preview",
        "core.io.value-preview",
        8400,
        700,
        title="正面放置与白码结果",
        display_mode="json",
    )
    edge("report", "value", "report_preview", "value")
    template.update(
        nodes=nodes,
        edges=edges,
        groups=[],
        description="3913 正面：六行托盘圆定位 → 18槽二维检查 → 正常槽1000×1000搜索区 → 检测 → 条码解析。",
    )
    template["template_inputs"] = []
    application["bindings"] = []
    for name, typ, target, port in [
        ("request_image_ref", "image-ref.v1", "input_image", "primary"),
        ("request_image_base64", "image-base64.v1", "decode_input", "payload"),
    ]:
        template["template_inputs"].append(
            {
                "input_id": name,
                "display_name": name,
                "payload_type_id": typ,
                "target_node_id": target,
                "target_port": port,
                "required": False,
            }
        )
        application["bindings"].append(
            {
                "binding_id": name,
                "direction": "input",
                "template_port_id": name,
                "binding_kind": "api-request",
                "required": False,
                "config": {"payload_type_id": typ},
                "metadata": {"payload_type_id": typ, "display_name": name},
            }
        )
    template["template_outputs"] = [
        {
            "output_id": "report",
            "display_name": "Report",
            "payload_type_id": "value.v1",
            "source_node_id": "report",
            "source_port": "value",
        }
    ]
    application["bindings"].append(
        {
            "binding_id": "report",
            "direction": "output",
            "template_port_id": "report",
            "binding_kind": "api-response",
            "required": False,
            "config": {},
            "metadata": {"payload_type_id": "value.v1"},
        }
    )
    template["notes"] = [
        {
            "note_id": "guide",
            "title": "3913 正面定位与读码",
            "content": "仅正面工作流，反面另建。输入20000×16384原始BMP，定位概览图为2500×2048。Hough圆只提供候选；Circle Pattern Locate按明确参考点匹配整个图案，允许平移和±10°旋转，定位失败立即报错。\n\n托盘对齐后比较18个槽位，不单独对齐工件。边缘容差2个概览像素（约16个原图像素），差异比例5%是验证参数，尚未用真实缺陷标定；不能测量翘起高度。\n\n放置通过的槽位才读码，其余在barcode_selection中保留skipped。Mapped ROI Crop的倍率8明确换算定位坐标，直接从原图取得1000×1000区域。红色通道索引2、检测框外扩40px、显式2倍cubic插值、local-average二值化后Data Matrix解析。每条记录以item_id关联槽位。解码位置属于1000×1000搜索图，乘source.source_from_crop才能回到原图，不能只加外接框偏移。",
            "rect": {"x": 350, "y": -1000, "width": 1200, "height": 550},
            "tone": "warning",
        }
    ]
    application["description"] = template["description"]
    application.setdefault("metadata", {}).setdefault("workflow_graph_editor", {})[
        "boundary_positions"
    ] = {"entry": {"x": 0, "y": 150}, "result": {"x": 8750, "y": 700}}
    return add_editable_roi_and_debug(application, template)


def add_editable_roi_and_debug(application, template):
    """按现有 ROI 编辑器、绘制和预览节点组织现场调试流程。"""
    removed = {
        "barcode_rois",
        "crop_search",
        "search_items",
        "search_image",
        "passed_ids",
        "source_mapping",
        "selection_field",
    }
    nodes = [n for n in template["nodes"] if n["node_id"] not in removed]
    edges = [
        e
        for e in template["edges"]
        if e["source_node_id"] not in removed and e["target_node_id"] not in removed
    ]
    lookup = {n["node_id"]: n for n in nodes}
    lookup["recipe"]["parameters"]["fields"].pop("barcode_rois", None)
    lookup["source_id"]["parameters"]["path"] = "item_id"
    lookup["compare_foreground"]["parameters"].update(
        check_pose=True,
        max_centroid_shift_pixels=8,
        max_axis_angle_degrees=3,
        emit_comparison_images=True,
    )

    def node(name, kind, **params):
        """新增通用节点，稍后统一布局。"""
        item = {
            "node_id": name,
            "node_type_id": kind,
            "parameters": params,
            "enabled": True,
            "ui_state": {"x": 0, "y": 0, "width": 320},
            "metadata": {},
        }
        nodes.append(item)
        lookup[name] = item

    def edge(source, port, target, target_port):
        """端口显式连线，禁止按页面位置关联结果。"""
        edges.append(
            {
                "edge_id": "pending",
                "source_node_id": source,
                "source_port": port,
                "target_node_id": target,
                "target_port": target_port,
            }
        )

    def preview(name, source, port, title, gallery=False, value=False):
        """添加独立显示节点；调试配置仍由原节点控制。"""
        kind = (
            "custom.opencv.gallery-preview"
            if gallery
            else ("core.io.value-preview" if value else "core.io.image-preview")
        )
        params = {"title": title}
        if not value:
            params["response_transport_mode"] = "inline-base64"
        node(name, kind, **params)
        edge(
            source, port, name, "images" if gallery else ("value" if value else "image")
        )

    node("decoded_source", "custom.opencv.image-decode")
    for connection in edges:
        if (
            connection["source_node_id"] == "input_image"
            and connection["target_node_id"] == "overview"
        ):
            connection["source_node_id"] = "decoded_source"
    edge("input_image", "image", "decoded_source", "image")
    preview("overview_preview", "overview", "image", "输入概览")
    preview("aligned_preview", "align", "image", "托盘对齐结果")
    preview("pose_preview", "locate", "summary", "托盘定位误差", value=True)
    node("slot_crops", "custom.opencv.crop-export", polygon_background_fill="white")
    edge("align", "image", "slot_crops", "image")
    edge("inspection_roi_list", "rois", "slot_crops", "rois")
    preview("slots_gallery", "slot_crops", "crops", "18个工件 ROI", gallery=True)
    preview(
        "difference_gallery",
        "compare_foreground",
        "comparison_images",
        "逐槽差异：绿匹配 / 红缺失 / 橙溢出",
        gallery=True,
    )
    preview(
        "placement_preview",
        "compare_foreground",
        "summary",
        "放置判定 / 偏移 / 角度",
        value=True,
    )
    # 每次只裁一个完整工件，避免一次常驻 18 张原分辨率工件图。
    edge("passed_items", "value", "barcode_loop", "items")
    node("part_roi_value", "core.logic.value-field-extract", path="source")
    edge("barcode_loop", "item", "part_roi_value", "value")
    node("part_roi", "core.vision.roi-create")
    edge("part_roi_value", "value", "part_roi", "value")
    node(
        "crop_part",
        "custom.opencv.mapped-roi-crop",
        coordinate_scale=8,
        roi_coordinate_scale=8,
        interpolation="linear",
        maximum_total_pixels=20000000,
    )
    edge("decoded_source", "image", "crop_part", "image")
    edge("locate", "transform", "crop_part", "transform")
    edge("part_roi", "roi", "crop_part", "roi")
    node("part_image", "core.io.image-refs-item-get", index=0)
    edge("crop_part", "crops", "part_image", "images")
    node(
        "barcode_roi",
        "core.vision.roi-create",
        roi_kind="bbox",
        roi_id="barcode-search",
        display_name="条码搜索区域（可拖动修改）",
        bbox_xyxy=[1720, 1000, 2720, 2000],
        debug_image_panel_enabled=True,
        debug_image_panel_transport_mode="inline-base64",
    )
    # 取参显示显式编码一次，显示通道可直接复用 JPEG，不积压原始大矩阵编码。
    # Crop Export 和模型仍从 part_image 的 raw 像素读取，不把显示压缩用于推理。
    node("part_display_encode", "core.io.image-encode", format="jpeg", jpeg_quality=90)
    edge("part_image", "image", "part_display_encode", "image")
    edge("part_display_encode", "image", "barcode_roi", "image")
    node("crop_search", "custom.opencv.crop-export", box_padding=0)
    edge("part_image", "image", "crop_search", "image")
    node("barcode_roi_list", "core.vision.roi-list-create")
    edge("barcode_roi", "roi", "barcode_roi_list", "roi")
    edge("barcode_roi_list", "rois", "crop_search", "rois")
    node("search_image", "core.io.image-refs-item-get", index=0)
    edge("crop_search", "crops", "search_image", "images")
    edge("search_image", "image", "detect_code", "image")
    edge("search_image", "image", "code_grayscale", "image")
    node("search_image_value", "core.logic.payload-to-value")
    edge("search_image", "image", "search_image_value", "image")
    node("source_mapping", "core.logic.value-field-extract", path="mapped_source")
    edge("search_image_value", "value", "source_mapping", "value")
    edge("source_mapping", "value", "source_field", "value")
    # Create ROI 已显示同一张完整工件图，不重复提交约14MP的 Image Preview。
    preview("search_preview", "search_image", "image", "手选条码搜索图")
    node(
        "draw_detection",
        "custom.opencv.draw-detections",
        line_thickness=3,
        font_scale=0.7,
    )
    edge("search_image", "image", "draw_detection", "image")
    edge("detect_code", "detections", "draw_detection", "detections")
    preview("detection_preview", "draw_detection", "image", "模型检测框与分数")
    node("detection_value", "core.logic.payload-to-value")
    edge("detect_code", "detections", "detection_value", "detections")
    preview(
        "detection_values_preview",
        "detection_value",
        "value",
        "模型原始结果",
        value=True,
    )
    preview("code_crop_preview", "crop_code", "crops", "外扩后的解码图", gallery=True)
    preview(
        "code_values_preview", "decode_codes", "summary", "当前槽位解码结果", value=True
    )
    # 原始定位矩形及局部取框均在结果中可追溯。
    node("roi_field", "core.logic.object-field", key="search_roi")
    edge("barcode_roi", "summary", "roi_field", "value")
    edge("roi_field", "field", "code_item", "entries")
    template.update(nodes=nodes, edges=edges)
    for index, e in enumerate(edges):
        e["edge_id"] = f"e{index + 1:03}"
    layout_front_workflow(application, template)
    template["description"] = (
        "3913 正面：托盘定位、18槽放置检查、正常工件手选条码 ROI、检测与读码；分阶段调试预览。"
    )
    application["description"] = template["description"]
    template["notes"] = [
        {
            "note_id": "guide",
            "title": "正面现场调试",
            "tone": "info",
            "rect": {"x": 350, "y": -750, "width": 1250, "height": 600},
            "content": "按编号分组从左向右执行。18槽用托盘坐标统一比较，不对工件单独配准，避免把放歪纠正后误判。差异图：绿色匹配、红色缺失、橙色多出；查看判定明细中的偏移和主轴角差。阈值是当前验证参数，现场需实际异常样本标定，二维图片不测量翘起高度。\n\n第4组 Create ROI 是条码搜索区域：预览后打开调试图，用矩形工具拖动/缩放并应用参数，也可直接修改矩形坐标。初始1000×1000，所有正常工件复用同一局部框，不限制为固定尺寸。此图是托盘对齐后的工件外接矩形，坐标相对工件，不能填整图坐标。\n\n循环中预览显示当前/最后一次工件；18槽全览及全部判定见第3组，全部读码及槽位标识见第6组。异常槽不会进入读码循环。只处理正面。",
        }
    ]
    return {"application": application, "template": template}


def layout_front_workflow(application, template):
    """参照现有工作流的分组组织，主链上排、预览下排，不依赖节点位置执行。"""
    stages = [
        (
            "01 输入",
            350,
            0,
            [
                ["decode_input", "input_image", "decoded_source"],
                ["overview", "overview_preview"],
            ],
        ),
        (
            "02 托盘定位",
            1700,
            0,
            [
                ["circles", "locate", "align"],
                ["draw_anchors", "pose_preview", "aligned_preview"],
                ["anchors_preview"],
            ],
        ),
        (
            "03 18槽放置检查",
            3050,
            0,
            [
                ["recipe", "reference_path", "load_reference"],
                ["inspection_rois", "inspection_roi_list", "compare_foreground"],
                ["slot_crops", "draw_inspection", "placement_items"],
                ["slots_gallery", "inspection_preview", "passed_items"],
                ["difference_gallery", "placement_preview"],
            ],
        ),
        (
            "04 正常工件 / 手选条码区域",
            4400,
            0,
            [
                ["barcode_loop", "part_roi_value", "part_roi"],
                ["crop_part", "part_image", "part_display_encode"],
                ["barcode_roi", "barcode_roi_list", "crop_search"],
                ["search_image", "search_preview", "search_image_value"],
                ["source_mapping", "source_id"],
            ],
        ),
        (
            "05 目标检测 / 裁剪 / 解码",
            5750,
            0,
            [
                ["detect_code", "code_regions", "filter_codes"],
                ["draw_detection", "code_grayscale", "crop_code"],
                ["detection_preview", "code_crop_preview", "decode_codes"],
                ["detection_value", "detection_values_preview", "code_values_preview"],
            ],
        ),
        (
            "06 结果汇总",
            7100,
            0,
            [
                ["item_id_field", "source_field", "code_result_field"],
                ["detection_field", "roi_field", "code_item"],
                ["barcode_end", "barcodes_field", "pose_field"],
                ["inspection_field", "report", "report_preview"],
            ],
        ),
    ]
    by_id = {n["node_id"]: n for n in template["nodes"]}
    groups = []
    assigned = set()
    for i, (title, x, y, rows) in enumerate(stages):
        members = []
        row_y = y + 80
        for row, names in enumerate(rows):
            for col, name in enumerate(names):
                by_id[name]["ui_state"] = {
                    "x": x + 40 + col * 410,
                    "y": row_y,
                    "width": 340,
                }
                members.append(name)
            # Hough 的完整参数面板实测高 1674，不能与下一排节点重叠。
            # 18张 Gallery 实际预览高984px，保留完整显示后的节点间隔。
            row_y += (
                1790
                if "circles" in names
                else 1100
                if any(
                    by_id[name]["node_type_id"] == "custom.opencv.gallery-preview"
                    for name in names
                )
                else 920
            )
        assigned.update(members)
        groups.append(
            {
                "group_id": f"stage-{i + 1}",
                "name": title,
                "enabled": True,
                "rect": {
                    "x": x,
                    "y": y,
                    "width": 1280,
                    "height": row_y - y + 20,
                },
                "member_node_ids": members,
                "member_note_ids": [],
                "membership_policy": "full-containment",
                "color": [
                    "#22b8cf",
                    "#fab005",
                    "#10b981",
                    "#7c5cfc",
                    "#22b8cf",
                    "#10b981",
                ][i],
                "collapsed": False,
                "locked": False,
                "metadata": {},
            }
        )
    assert assigned == set(by_id), f"未布局节点: {set(by_id) - assigned}"
    template["groups"] = groups
    application["metadata"]["workflow_graph_editor"]["boundary_positions"] = {
        "entry": {"x": 0, "y": 80},
        "result": {"x": 8500, "y": 2840},
    }


def main():
    """默认只校验并导出，--apply 通过正式 API 更新指定草稿。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    with httpx.Client(
        base_url="http://127.0.0.1:5600",
        headers={"Authorization": "Bearer " + DEFAULT_LOCAL_AUTH_TOKEN},
        timeout=60,
    ) as client:
        url = f"/api/v1/workflows/projects/project-1/applications/{APP_ID}"
        response = client.get(url)
        response.raise_for_status()
        application = response.json()["application"]
        ref = application["template_ref"]
        response = client.get(
            f"/api/v1/workflows/projects/project-1/templates/{ref['template_id']}/versions/{ref['template_version']}"
        )
        response.raise_for_status()
        payload = build(application, response.json()["template"])
        # 同一配置入口最终使用可编辑首槽阵列，避免再次写回18组固定坐标。
        from scripts.configure_linescan_front_array import build as build_array

        payload = build_array(payload["application"], payload["template"])
        response = client.post(
            "/api/v1/workflows/applications/validate",
            json={"project_id": "project-1", **payload},
        )
        print("validate", response.status_code, response.text[:3000])
        response.raise_for_status()
        (DATA / "validation/front-registered/workflow-bundle.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), "utf-8"
        )
        if args.apply:
            response = client.put(url, json=payload)
            response.raise_for_status()
            print("saved", response.status_code)


if __name__ == "__main__":
    main()
