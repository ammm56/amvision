"""将正面放置检测拆成通用测量节点；产品阈值只属于此开发工作流配方。"""

import argparse
import copy
import json

import httpx

from backend.service.application.auth.default_local_auth_seeder import (
    DEFAULT_LOCAL_AUTH_TOKEN,
)
from scripts.configure_linescan_3913_workflow import APP_ID, DATA
from scripts.simplify_linescan_front_grid import OUT as GRID_OUT

OUT = DATA / "validation/inspection-primitives-20261029"

# 名称、中文标题、测量节点、测量字段、闭区间、单位、绘图证据掩膜。
CHECKS = (
    (
        "reference_area",
        "参考前景有效",
        "reference_properties",
        "area",
        500,
        None,
        "px2",
        "reference_masks",
    ),
    (
        "reference_boundary",
        "参考允许域核对",
        "reference_outside",
        "ratio_to_a",
        0,
        0.02,
        "ratio",
        "reference_outside",
    ),
    ("missing", "前景缺失", "missing", "ratio_to_a", 0, 0.05, "ratio", "missing"),
    ("excess", "前景多出", "excess", "ratio_to_b", 0, 0.05, "ratio", "excess"),
    ("shift", "质心偏移", "pose_difference", "centroid_shift_pixels", 0, 8, "px", None),
    (
        "angle",
        "主轴角差",
        "pose_difference",
        "axis_angle_difference_degrees",
        0,
        3,
        "deg",
        None,
    ),
    (
        "boundary",
        "超出允许 ROI",
        "current_outside",
        "ratio_to_a",
        0,
        0.02,
        "ratio",
        "current_outside",
    ),
)


def layout_inspection_rows(template):
    """18张证据图展开约984像素高，各检查同行排列且不相互遮挡。"""
    nodes = {node["node_id"]: node for node in template["nodes"]}
    for row, (name, *_rest) in enumerate(CHECKS):
        for prefix in ("check_", "check_field_", "evidence_", "gallery_", "values_"):
            nodes[prefix + name]["ui_state"]["y"] = 480 + row * 1120
    for name, row in {
        "reference_outside": 1, "missing": 2, "excess": 3,
        "pose_difference": 4, "current_outside": 6,
    }.items():
        nodes[name]["ui_state"]["y"] = 480 + row * 1120
    for group in template["groups"]:
        if group["group_id"] in {"inspection-checks", "inspection-evidence"}:
            group["rect"]["height"] = 8000


def build(application, template):
    """保留定位、ROI 阵列、条码与公开契约，替换集中式放置检查。"""
    application, template = copy.deepcopy(application), copy.deepcopy(template)
    nodes = {n["node_id"]: n for n in template["nodes"]}
    if (
        nodes["compare_foreground"]["node_type_id"]
        == "custom.opencv.inspection-items-merge"
    ):
        layout_inspection_rows(template)
        return {"application": application, "template": template}
    if nodes["slot_array"]["node_type_id"] != "core.vision.roi-grid-create":
        raise ValueError("先完成可编辑 ROI Grid Create 配方")
    removed = {"difference_gallery"}
    template["nodes"] = [n for n in template["nodes"] if n["node_id"] not in removed]
    template["edges"] = [
        e
        for e in template["edges"]
        if e["source_node_id"] not in removed
        and e["target_node_id"] not in removed
        and e["target_node_id"] != "compare_foreground"
    ]
    # 让新增测量区拥有完整空间，下游原有组只平移，不改变任何参数或连线。
    for group in template["groups"]:
        if group["group_id"] in {"stage-4", "stage-5", "stage-6", "stage-7"}:
            group["rect"]["x"] += 4700
            for key in group["member_node_ids"]:
                nodes[key]["ui_state"]["x"] += 4700
    template["groups"] = [g for g in template["groups"] if g["group_id"] != "stage-3"]
    new_groups = {}

    def group(key, title, x, y, width, height, color):
        """分开计算和证据绘图，现场可以整体禁用证据组。"""
        g = {
            "group_id": key,
            "name": title,
            "enabled": True,
            "rect": {"x": x, "y": y, "width": width, "height": height},
            "member_node_ids": [],
            "member_note_ids": [],
            "membership_policy": "full-containment",
            "color": color,
            "collapsed": False,
            "locked": False,
            "metadata": {},
        }
        template["groups"].append(g)
        new_groups[key] = g

    def put(key, kind, params, x, y, group_id):
        """参数使用现有节点面板，节点之间只用公开端口。"""
        if key in nodes:
            n = nodes[key]
            n.update(node_type_id=kind, parameters=params, enabled=True)
            n["ui_state"].update(x=x, y=y)
        else:
            n = {
                "node_id": key,
                "node_type_id": kind,
                "parameters": params,
                "enabled": True,
                "ui_state": {"x": x, "y": y, "width": 256},
                "metadata": {},
            }
            template["nodes"].append(n)
            nodes[key] = n
        new_groups[group_id]["member_node_ids"].append(key)

    def edge(source, port, target, target_port):
        """每条连线拥有确定的名称，不依赖坐标或排序。"""
        template["edges"].append(
            {
                "edge_id": f"inspection-{source}-{port}-{target}-{target_port}",
                "source_node_id": source,
                "source_port": port,
                "target_node_id": target,
                "target_port": target_port,
                "metadata": {},
            }
        )

    group(
        "inspection-extract",
        "03A 前景提取 / 像素测量",
        4910,
        400,
        1960,
        1940,
        "#10b981",
    )
    group("inspection-checks", "03B 各项独立判定", 6920, 400, 1460, 3220, "#fab005")
    group(
        "inspection-evidence",
        "03C 每项数据 / 证据图（可整组禁用）",
        8430,
        400,
        990,
        3220,
        "#22b8cf",
    )
    group("inspection-summary", "03D 按槽位汇总", 9470, 400, 1910, 1940, "#10b981")
    for key, x, y in (("reference_path", 4960, 480), ("load_reference", 5270, 480)):
        put(
            key,
            nodes[key]["node_type_id"],
            nodes[key]["parameters"],
            x,
            y,
            "inspection-extract",
        )
    for prefix, source, y in (
        ("current", "align", 1050),
        ("reference", "load_reference", 1550),
    ):
        put(
            prefix + "_binary",
            "custom.opencv.binary-threshold",
            {"threshold": 80, "max_value": 255},
            4960,
            y,
            "inspection-extract",
        )
        put(
            prefix + "_dark",
            "custom.opencv.mask-logic",
            {"operation": "not"},
            5270,
            y,
            "inspection-extract",
        )
        put(
            prefix + "_masks",
            "custom.opencv.roi-mask-extract",
            {"search_margin_pixels": 8, "coordinate_space": "tray-reference-overview"},
            5580,
            y,
            "inspection-extract",
        )
        put(
            prefix + "_properties",
            "custom.opencv.mask-items-properties",
            {"min_axis_anisotropy": 0.1},
            6200,
            y,
            "inspection-extract",
        )
        edge(source, "image", prefix + "_binary", "image")
        edge(prefix + "_binary", "image", prefix + "_dark", "mask_a")
        edge(prefix + "_dark", "mask", prefix + "_masks", "mask")
        edge("slot_array", "rois", prefix + "_masks", "rois")
        edge(prefix + "_masks", "masks", prefix + "_properties", "masks")
    for key, a, b, bport, row in (
        ("missing", "reference_masks", "current_masks", "masks", 2),
        ("excess", "current_masks", "reference_masks", "masks", 3),
        ("current_outside", "current_masks", "current_masks", "allowed_masks", 6),
        ("reference_outside", "reference_masks", "reference_masks", "allowed_masks", 1),
    ):
        put(
            key,
            "custom.opencv.mask-items-difference",
            {"tolerance_pixels": 2},
            6970,
            480 + row * 430,
            "inspection-checks",
        )
        edge(a, "masks", key, "masks_a")
        edge(b, bport, key, "masks_b")
    put(
        "pose_difference",
        "custom.opencv.pose-items-difference",
        {},
        6970,
        480 + 4 * 430,
        "inspection-checks",
    )
    edge("current_properties", "metrics", "pose_difference", "current")
    edge("reference_properties", "metrics", "pose_difference", "reference")
    for row, (name, title, source, metric, minimum, maximum, unit, mask) in enumerate(
        CHECKS
    ):
        y = 480 + row * 430
        params = {"check_id": name, "metric": metric, "unit": unit}
        if minimum is not None:
            params["minimum"] = minimum
        if maximum is not None:
            params["maximum"] = maximum
        put(
            "check_" + name,
            "custom.opencv.measurement-items-check",
            params,
            7300,
            y,
            "inspection-checks",
        )
        put(
            "check_field_" + name,
            "core.logic.object-field",
            {"key": name},
            8000,
            y,
            "inspection-checks",
        )
        edge(source, "metrics", "check_" + name, "metrics")
        edge("check_" + name, "checks", "check_field_" + name, "value")
        edge("check_field_" + name, "field", "inspection_checks", "entries")
        put(
            "evidence_" + name,
            "custom.opencv.draw-inspection-items",
            {},
            8480,
            y,
            "inspection-evidence",
        )
        put(
            "gallery_" + name,
            "custom.opencv.gallery-preview",
            {
                "title": title + " / 逐槽证据",
                "response_transport_mode": "inline-base64",
            },
            8790,
            y,
            "inspection-evidence",
        )
        put(
            "values_" + name,
            "core.io.value-preview",
            {
                "title": title + " / 数值与阈值",
                "path": "items",
                "display_mode": "table",
                "columns": [
                    {"key": "slot", "label": "槽位", "path": "item_id"},
                    {"key": "value", "label": "测量值", "path": "result.value"},
                    {"key": "min", "label": "下限", "path": "result.minimum"},
                    {"key": "max", "label": "上限", "path": "result.maximum"},
                    {"key": "state", "label": "结果", "path": "result.state"},
                ],
            },
            9100,
            y,
            "inspection-evidence",
        )
        edge(
            "load_reference" if name.startswith("reference_") else "align",
            "image",
            "evidence_" + name,
            "image",
        )
        edge("check_" + name, "checks", "evidence_" + name, "checks")
        if mask:
            edge(mask, "masks", "evidence_" + name, "masks")
        edge("evidence_" + name, "images", "gallery_" + name, "images")
        edge("check_" + name, "checks", "values_" + name, "value")
    put(
        "inspection_checks",
        "core.logic.object-build",
        {},
        9520,
        480,
        "inspection-summary",
    )
    put(
        "compare_foreground",
        "custom.opencv.inspection-items-merge",
        {},
        9830,
        480,
        "inspection-summary",
    )
    edge("inspection_checks", "value", "compare_foreground", "checks")
    edge("align", "image", "compare_foreground", "image")
    for key, x, y in (
        ("draw_inspection", 10140, 480),
        ("inspection_preview", 10450, 480),
        ("placement_preview", 10760, 480),
        ("placement_items", 10140, 1300),
        ("passed_items", 10450, 1300),
    ):
        put(
            key,
            nodes[key]["node_type_id"],
            nodes[key]["parameters"],
            x,
            y,
            "inspection-summary",
        )
    nodes["draw_inspection"]["parameters"]["class_colors"] = {
        "pass": "#087A56",
        "fail": "#dc3232",
        "unavailable": "#ed9b2b",
    }
    nodes["placement_preview"]["parameters"]["title"] = "各槽位独立检查汇总"
    for note in template.get("notes", []):
        if note["note_id"] == "guide":
            note["content"] += (
                "\n\n放置检查已拆分：03A 显式二值化与前景测量；03B 缺失、多出、质心偏移、无向主轴角差、超出允许 ROI 独立检查；03C 各项数值和证据图，可整体禁用；03D 按槽位 ID 汇总。参考面积与参考越界检查用于识别无效配方。所有像素单位属于 2500×2048 配准图；缺少可测量主轴时为 unavailable，不判通过。允许 ROI 尚需按实际槽壁标定，当前不是物理高度检测。"
            )
    layout_inspection_rows(template)
    return {"application": application, "template": template}


def main():
    """先准备并验证配方；仅 --apply 才通过正式 API 更新草稿。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    if not args.apply:
        base = json.loads((GRID_OUT / "grid-workflow.json").read_text("utf-8"))
        payload = build(**base)
    else:
        with httpx.Client(
            base_url="http://127.0.0.1:5600",
            headers={"Authorization": "Bearer " + DEFAULT_LOCAL_AUTH_TOKEN},
            timeout=120,
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
            result = client.post(
                "/api/v1/workflows/applications/validate",
                json={"project_id": "project-1", **payload},
            )
            result.raise_for_status()
            assert result.json()["valid"], result.text
            current = client.get(url)
            current.raise_for_status()
            assert current.json()["draft_fingerprint"] == before["draft_fingerprint"], (
                "验证期间草稿已变化"
            )
            result = client.put(url, json=payload)
            result.raise_for_status()
            (OUT / "saved.json").write_text(
                json.dumps(result.json(), ensure_ascii=False, indent=2), "utf-8"
            )
    (OUT / "inspection-workflow.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), "utf-8"
    )
    print("prepared", len(payload["template"]["nodes"]), "nodes; applied", args.apply)


if __name__ == "__main__":
    main()
