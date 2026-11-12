"""用现有通用节点编排逐工件 JSON 返回；不新增场景专用运行节点。"""

import argparse
from copy import deepcopy
import json

import httpx

from backend.service.application.auth.default_local_auth_seeder import (
    DEFAULT_LOCAL_AUTH_TOKEN,
)
from scripts.configure_linescan_3913_workflow import APP_ID, DATA

OUT = DATA / "validation/final-result-20261029"
PREFIX = "final_"


def build_result_nodes(
    *, expected_count=18, image_size=(2500, 2048), coordinate_scale=8
):
    """返回可单独验证的通用汇总子图，按 item_id 查询而非按列表位置拼接。"""
    nodes, edges = [], []

    def put(name, kind, **parameters):
        """注册一个明确命名的基本节点。"""
        name = PREFIX + name
        nodes.append(
            dict(
                node_id=name,
                node_type_id=kind,
                parameters=parameters,
                enabled=True,
                metadata={},
                ui_state={},
            )
        )
        return name

    def link(source, port, target, target_port):
        """使用明确节点和端口建立依赖。"""
        edges.append(
            dict(
                edge_id=f"final-edge-{len(edges):03}",
                source_node_id=source,
                source_port=port,
                target_node_id=target,
                target_port=target_port,
            )
        )

    def extract(name, source, path, *, default=None, optional=False):
        """字段缺失仅在明确指定的分支返回固定类型默认值。"""
        params = dict(path=path)
        if optional:
            params.update(missing_policy="default", default_value=default)
        target = put(name, "core.logic.value-field-extract", **params)
        link(source, "value", target, "value")
        return target

    def field(name, source, key, target, port="value"):
        """字段名与值通过 Object Field 显式绑定。"""
        node = put(name, "core.logic.object-field", key=key)
        link(source, port, node, "value")
        link(node, "field", target, "entries")

    def equal(name, source, value, port="value"):
        """输出 boolean.v1，供统一 OK/NG 判定使用。"""
        node = put(name, "core.logic.compare", operator="eq", right_value=value)
        link(source, port, node, "left")
        return node

    def decision(name, sources):
        """全部条件成立才返回 OK。"""
        node = put(name, "core.rule.ok-ng-decision", mode="all")
        for source, port in sources:
            link(source, port, node, "conditions")
        return node

    def projected_coordinates(name, roi, transform):
        """只投影坐标，不复制或变换图片；输出可用于绘制的 bbox 与 polygon。"""
        projected = put(
            name + "_project",
            "custom.opencv.planar-transform-bridge",
            direction="source-a-to-source-b",
        )
        link(roi, "roi", projected, "roi")
        link(transform, "transform", projected, "transform")
        value = put(name + "_value", "core.logic.payload-to-value")
        link(projected, "roi", value, "roi")
        return value

    def pick(name, source, paths):
        """使用已有字段选择节点保留明确键名，避免重复拆开再组装。"""
        target = put(name, "core.logic.object-pick", paths=paths)
        link(source, "value", target, "object")
        return target

    # Select Best 上游明确只选一个框；没有检测框的条目不做坐标投影。
    has_detection = put(
        "has_detection",
        "core.logic.list-filter",
        condition={"path": "detections.0", "operator": "exists"},
    )
    link("barcode_end", "results", has_detection, "items")
    box_loop = put("box_loop", "core.logic.for-each-start")
    link(has_detection, "value", box_loop, "items")
    barcode_record = put("box_barcode", "core.logic.value-field-extract", path="")
    link(box_loop, "item", barcode_record, "value")
    box = extract("box", barcode_record, "detections.0")
    matrix = extract("barcode_matrix", barcode_record, "source.source_from_crop")
    transform = put(
        "barcode_transform",
        "custom.opencv.transform-2d-create",
        transform_kind="homography",
        source_coordinate_space="barcode-search-image-pixels",
        target_coordinate_space="source-image-pixels",
    )
    link(matrix, "value", transform, "matrix_3x3")
    box_roi = put(
        "box_roi", "core.vision.roi-create", roi_kind="bbox", roi_id="barcode"
    )
    box_input = put("box_input", "core.logic.object-build", fields={"roi_kind": "bbox"})
    box_bbox = extract("box_bbox", box, "bbox_xyxy")
    field("box_bbox_field", box_bbox, "bbox_xyxy", box_input)
    link(box_input, "value", box_roi, "value")
    source_roi = put(
        "box_source",
        "custom.opencv.planar-transform-bridge",
        direction="source-a-to-source-b",
    )
    link(box_roi, "roi", source_roi, "roi")
    link(transform, "transform", source_roi, "transform")
    resize = put(
        "resize_transform",
        "custom.opencv.transform-2d-create",
        transform_kind="similarity",
        scale=1 / coordinate_scale,
        translation_x=(1 / coordinate_scale - 1) / 2,
        translation_y=(1 / coordinate_scale - 1) / 2,
        source_coordinate_space="source-image-pixels",
        target_coordinate_space="resized-source-image-pixels",
    )
    projected_box = projected_coordinates("box_current", source_roi, resize)
    geometry = pick("box_geometry", projected_box, ["bbox_xyxy", "polygon_xy"])
    attributes = pick("box_attributes", box, ["region_id", "class_name", "score"])
    box_result = put("box_result", "core.logic.object-merge-pair", conflict_policy="error")
    link(geometry, "value", box_result, "base")
    link(attributes, "value", box_result, "overlay")
    mapped = put("mapped_record", "core.logic.object-build")
    mapped_id = extract("mapped_id", barcode_record, "item_id")
    field("mapped_id_field", mapped_id, "item_id", mapped)
    field("mapped_detection_field", box_result, "detection", mapped)
    box_end = put("box_end", "core.logic.for-each-end")
    link(mapped, "value", box_end, "result")
    mapped_groups = put("mapped_groups", "core.logic.list-group-by", path="item_id")
    link(box_end, "results", mapped_groups, "items")

    # 两份输入均完成后才开始逐槽汇总；循环体不依赖其他循环的内部节点。
    groups = put("barcode_groups", "core.logic.list-group-by", path="item_id")
    link("barcode_end", "results", groups, "items")
    context = put("context", "core.logic.object-build")
    field("placements_field", "placement_items", "placements", context)
    field("groups_field", groups, "barcodes_by_id", context)
    field("mapped_groups_field", mapped_groups, "mapped_by_id", context)
    placements = extract("placements", context, "placements")
    loop = put("loop", "core.logic.for-each-start")
    link(placements, "value", loop, "items")
    current = put("current", "core.logic.value-field-extract", path="")
    link(loop, "item", current, "value")
    item_id = extract("item_id", current, "item_id")
    matches = put(
        "barcode_matches",
        "core.logic.value-field-extract",
        path="",
        missing_policy="default",
        default_value=[],
    )
    link(groups, "value", matches, "value")
    link(item_id, "value", matches, "path")
    match_count = put("match_count", "core.logic.list-length")
    link(matches, "value", match_count, "items")
    unique_match = equal("unique_match", match_count, 1)
    # 0 只在当前 item_id 分组内取首项；重复分组不能通过 unique_match。
    barcode = extract("barcode_record", matches, "0", optional=True, default={})
    placement_passed = extract("placement_passed", current, "result.passed")
    placement_ok = equal("placement_ok", placement_passed, True)
    placement_decision = decision("placement_decision", [(placement_ok, "result")])
    placement = put("placement", "core.logic.object-build")
    field("placement_result", placement_decision, "result", placement, "decision")
    roi = extract("roi", current, "source")
    roi_payload = put("roi_payload", "core.logic.value-to-roi")
    link(roi, "value", roi_payload, "value")
    projected_roi = projected_coordinates("roi_current", roi_payload, "locate")
    roi_geometry = pick("roi_geometry", projected_roi, ["bbox_xyxy", "polygon_xy"])
    field("placement_roi", roi_geometry, "roi", placement)
    reasons = extract("placement_reasons", current, "result.reasons")
    field("placement_reasons_field", reasons, "reasons", placement)
    detections = extract("detections", barcode, "detections", optional=True, default=[])
    detection_count = put("detection_count", "core.logic.list-length")
    link(detections, "value", detection_count, "items")
    detection_ok = equal("detection_ok", detection_count, 1)
    state = extract(
        "decode_state", barcode, "result.state", optional=True, default="not_executed"
    )
    decoded = equal("decoded", state, "decoded")
    decoded_items = extract(
        "decoded_items",
        barcode,
        "result.items.0.result.items",
        optional=True,
        default=[],
    )
    valid_codes = put(
        "valid_codes",
        "core.logic.list-filter",
        condition={
            "operator": "and",
            "conditions": [
                {"path": "valid", "operator": "eq", "right": True},
                {"path": "text", "operator": "ne", "right": ""},
            ],
        },
    )
    link(decoded_items, "value", valid_codes, "items")
    one_code = equal("one_code", valid_codes, 1, "count")
    values = put(
        "barcode_values", "core.logic.list-map", path="text", skip_missing=False
    )
    link(valid_codes, "value", values, "items")
    barcode_decision = decision(
        "barcode_decision",
        [
            (unique_match, "result"),
            (detection_ok, "result"),
            (decoded, "result"),
            (one_code, "result"),
        ],
    )
    barcode_result = put("barcode", "core.logic.object-build")
    field("barcode_result", barcode_decision, "result", barcode_result, "decision")
    field("barcode_state", state, "state", barcode_result)
    field("barcode_texts", values, "values", barcode_result)
    mapped_matches = put(
        "mapped_matches",
        "core.logic.value-field-extract",
        path="",
        missing_policy="default",
        default_value=[],
    )
    link(mapped_groups, "value", mapped_matches, "value")
    link(item_id, "value", mapped_matches, "path")
    mapped_boxes = put(
        "mapped_boxes", "core.logic.list-map", path="detection", skip_missing=False
    )
    link(mapped_matches, "value", mapped_boxes, "items")
    field("barcode_boxes", mapped_boxes, "detections", barcode_result)
    item_decision = decision(
        "item_decision",
        [
            (placement_decision, "ok"),
            (barcode_decision, "ok"),
        ],
    )
    item = put("item", "core.logic.object-build")
    field("item_id_field", item_id, "item_id", item)
    field("placement_field", placement, "placement", item)
    field("barcode_field", barcode_result, "barcode", item)
    field("item_result", item_decision, "result", item, "decision")
    end = put("end", "core.logic.for-each-end")
    link(item, "value", end, "result")
    items = put("items", "core.logic.value-field-extract", path="")
    link(end, "results", items, "value")
    ok_items = put(
        "ok_items",
        "core.logic.list-filter",
        condition={"path": "result", "operator": "eq", "right": "OK"},
    )
    link(items, "value", ok_items, "items")
    count = put("count", "core.logic.list-length")
    link(items, "value", count, "items")
    unique = put("unique_ids", "core.logic.list-unique", path="item_id")
    link(items, "value", unique, "items")
    count_ok = equal("count_ok", count, expected_count)
    unique_ok = equal("unique_ids_ok", unique, expected_count, "count")
    all_ok = equal("all_items_ok", ok_items, expected_count, "count")
    total = decision(
        "decision", [(count_ok, "result"), (unique_ok, "result"), (all_ok, "result")]
    )
    report = put(
        "report",
        "core.logic.object-build",
        fields={
            "format_id": "amvision.workpiece-inspection.v1",
            "face": "front",
            "expected_count": expected_count,
            "height_assessment": "not_measured",
            "coordinate_space": "resized-source-image-pixels",
            "image_size": list(image_size),
        },
    )
    field("result_field", total, "result", report, "decision")
    field("count_field", count, "count", report)
    field("items_field", items, "items", report)
    preview = put(
        "preview", "core.io.value-preview", title="最终返回 JSON", display_mode="json"
    )
    link(report, "value", preview, "value")
    return nodes, edges


def build(application, template):
    """增量更新当前草稿，原检测、读码和现有布局不变。"""
    application, template = deepcopy(application), deepcopy(template)
    nodes = {node["node_id"]: node for node in template["nodes"]}
    if "final_report" in nodes:
        # 仅替换本脚本拥有的汇总子图，保留现场对定位、检测和读码节点的编辑。
        owned = {node_id for node_id in nodes if node_id.startswith(PREFIX)}
        template["nodes"] = [
            node for node in template["nodes"] if node["node_id"] not in owned
        ]
        template["edges"] = [
            edge
            for edge in template["edges"]
            if edge["source_node_id"] not in owned
            and edge["target_node_id"] not in owned
        ]
        template["groups"] = [
            group for group in template["groups"] if group["group_id"] != "final-result"
        ]
    required = {"filter_codes", "code_item", "placement_items", "barcode_end", "report"}
    if not required.issubset(nodes):
        raise ValueError("当前草稿缺少预期的通用节点输出")
    extra = [
        dict(
            node_id="selected_regions_value",
            node_type_id="core.logic.payload-to-value",
            parameters={},
        ),
        dict(
            node_id="selected_detections",
            node_type_id="core.logic.value-field-extract",
            parameters={"path": "items"},
        ),
        dict(
            node_id="selected_detections_field",
            node_type_id="core.logic.object-field",
            parameters={"key": "detections"},
        ),
    ]
    links = [
        ("filter_codes", "regions", "selected_regions_value", "regions"),
        ("selected_regions_value", "value", "selected_detections", "value"),
        ("selected_detections", "value", "selected_detections_field", "value"),
        ("selected_detections_field", "field", "code_item", "entries"),
    ]
    stage = next(
        group for group in template["groups"] if group["group_id"] == "stage-7"
    )
    if "selected_regions_value" in nodes:
        extra, links = [], []
    x, y = stage["rect"]["x"], stage["rect"]["y"]
    for index, node in enumerate(extra):
        node.update(
            enabled=True,
            metadata={},
            ui_state={
                "x": x + 30 + index * 440,
                "y": y + stage["rect"]["height"] + 60,
                "width": 350,
            },
        )
    if extra:
        stage["rect"]["height"] += 470
    stage["member_node_ids"].extend(node["node_id"] for node in extra)
    template["nodes"].extend(extra)
    for index, (source, port, target, target_port) in enumerate(links):
        template["edges"].append(
            dict(
                edge_id=f"selected-result-{index}",
                source_node_id=source,
                source_port=port,
                target_node_id=target,
                target_port=target_port,
            )
        )
    added, edges = build_result_nodes(
        expected_count=nodes["report"]["parameters"]["fields"]["expected_count"],
        image_size=(
            nodes["overview"]["parameters"]["width"],
            nodes["overview"]["parameters"]["height"],
        ),
        coordinate_scale=nodes["crop_search"]["parameters"]["coordinate_scale"],
    )
    # 依赖阶段从左到右；每列内部纵向排列，保留现有整盘工作流位置。
    x += stage["rect"]["width"] + 160
    y = 400
    for index, node in enumerate(added):
        column, row = divmod(index, 10)
        node["ui_state"] = {
            "x": x + 40 + column * 440,
            "y": y + 80 + row * 530,
            "width": 350,
        }
    template["nodes"].extend(added)
    template["edges"].extend(edges)
    template["groups"].append(
        dict(
            group_id="final-result",
            name="08 逐工件 JSON / 总 OK-NG",
            enabled=True,
            rect={
                "x": x,
                "y": y,
                "width": ((len(added) + 9) // 10) * 440 + 80,
                "height": 5480,
            },
            member_node_ids=[node["node_id"] for node in added],
            member_note_ids=[],
            membership_policy="full-containment",
            color="#22b8cf",
            collapsed=False,
            locked=False,
            metadata={},
        )
    )
    output = next(
        item for item in template["template_outputs"] if item["output_id"] == "report"
    )
    output.update(
        source_node_id="final_report", source_port="value", display_name="检测结果"
    )
    for binding in application["bindings"]:
        if binding["binding_id"] == "report" and binding["direction"] == "output":
            binding.setdefault("metadata", {})["display_name"] = "检测结果"
    editor = application.setdefault("metadata", {}).setdefault(
        "workflow_graph_editor", {}
    )
    editor.setdefault("boundary_positions", {})["result"] = {
        "x": x + ((len(added) + 9) // 10) * 440 + 240,
        "y": y + 80,
    }
    return dict(application=application, template=template)


def main():
    """校验草稿；只有 --apply 才正式保存，不发布或切换 Runtime。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    with httpx.Client(
        base_url="http://127.0.0.1:5600",
        timeout=120,
        headers={"Authorization": "Bearer " + DEFAULT_LOCAL_AUTH_TOKEN},
    ) as client:
        url = f"/api/v1/workflows/projects/project-1/applications/{APP_ID}"
        response = client.get(url)
        response.raise_for_status()
        before = response.json()
        ref = before["application"]["template_ref"]
        response = client.get(
            f"/api/v1/workflows/projects/project-1/templates/{ref['template_id']}/versions/{ref['template_version']}"
        )
        response.raise_for_status()
        payload = build(before["application"], response.json()["template"])
        response = client.post(
            "/api/v1/workflows/applications/validate",
            json={"project_id": "project-1", **payload},
        )
        response.raise_for_status()
        if not response.json()["valid"]:
            raise ValueError(response.json())
        (OUT / "workflow.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), "utf-8"
        )
        if args.apply:
            current = client.get(url)
            current.raise_for_status()
            if current.json()["draft_fingerprint"] != before["draft_fingerprint"]:
                raise ValueError("草稿在验证期间发生变化")
            response = client.put(url, json=payload)
            response.raise_for_status()
        print(
            "validated", len(payload["template"]["nodes"]), "nodes; applied", args.apply
        )


if __name__ == "__main__":
    main()
