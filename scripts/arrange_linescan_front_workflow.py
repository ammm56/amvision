"""按处理阶段整理线扫正面草稿；仅更新画布坐标、分组和说明。"""

import argparse
from copy import deepcopy
import json
from pathlib import Path

import httpx

from backend.service.application.auth.default_local_auth_seeder import (
    DEFAULT_LOCAL_AUTH_TOKEN,
)


APP_ID = "workflow-app-20261028070103"
OUT = Path("data/files/developer/线扫16K读码检测/3913/validation/front-layout-20261030")


def executable(payload):
    """排除纯显示字段后，保留全部执行配置供保存前后逐字段核对。"""
    result = deepcopy(payload)
    result["application"].get("metadata", {}).pop("workflow_graph_editor", None)
    result["template"].pop("groups", None)
    result["template"].pop("notes", None)
    for node in result["template"]["nodes"]:
        node.pop("ui_state", None)
    return result


def arrange(payload, sizes):
    """使用浏览器实测尺寸分层排列，给预览结果预留显示高度。"""
    result = deepcopy(payload)
    template = result["template"]
    nodes = {n["node_id"]: n for n in template["nodes"]}
    dimensions = {n["id"]: n for n in sizes}
    if set(nodes) != set(dimensions):
        raise ValueError("节点清单与浏览器测量不一致，请重新测量当前草稿")
    old_groups = {g["group_id"]: g for g in template["groups"]}
    groups, used = [], set()
    edges = template["edges"]

    def height(key):
        """预留图像、JSON 和 18 张图库的展开高度。"""
        kind = nodes[key]["node_type_id"]
        extra = 0
        if kind.endswith("gallery-preview"):
            extra = 750
        elif kind.endswith("value-preview"):
            extra = 200
        elif kind.endswith("image-preview"):
            extra = 200
        return dimensions[key]["height"] + extra

    def block(gid, title, members, x, y, color="#22b8cf"):
        """组内按依赖深度从左向右，同行分支按源节点位置排列。"""
        assert members and not used.intersection(members), gid
        used.update(members)
        local = set(members)
        incoming = {
            k: [
                e["source_node_id"]
                for e in edges
                if e["target_node_id"] == k and e["source_node_id"] in local
            ]
            for k in members
        }
        depths = {}
        while len(depths) < len(members):
            ready = [
                k
                for k in members
                if k not in depths and all(p in depths for p in incoming[k])
            ]
            if not ready:
                raise ValueError(f"{gid} 存在无法排列的环")
            for key in ready:
                depths[key] = max((depths[p] + 1 for p in incoming[key]), default=0)
        xpos, bottom = x + 40, y + 80
        for depth in range(max(depths.values()) + 1):
            column = [k for k in members if depths[k] == depth]
            column.sort(
                key=lambda k: (
                    sum(nodes[p]["ui_state"]["y"] for p in incoming[k])
                    / max(1, len(incoming[k]))
                )
            )
            ypos = y + 90
            for key in column:
                nodes[key]["ui_state"].update(x=xpos, y=ypos)
                ypos += height(key) + 90
            bottom = max(bottom, ypos)
            xpos += max(dimensions[k]["width"] for k in column) + 110
        group = deepcopy(old_groups.get(gid, old_groups["stage-1"]))
        group.update(
            group_id=gid,
            name=title,
            rect=dict(x=x, y=y, width=xpos - x - 70, height=bottom - y),
            member_node_ids=members,
            member_note_ids=[],
            color=color,
            locked=True,
        )
        groups.append(group)
        return group

    def right(g):
        """下一组与当前组保留统一间隔。"""
        return g["rect"]["x"] + g["rect"]["width"] + 100

    def bottom(g):
        """同阶段辅助区域放在主链下方。"""
        return g["rect"]["y"] + g["rect"]["height"] + 120

    top = 400
    g = block(
        "stage-input",
        "01 输入与解码",
        ["decode_input", "input_image", "decoded_source"],
        400,
        top,
    )
    g = block(
        "stage-1",
        "02 圆形定位与整盘配准",
        [
            "overview",
            "circles",
            "locate",
            "align",
            "draw_anchors",
            "anchors_preview",
            "overview_preview",
            "aligned_preview",
            "pose_preview",
        ],
        right(g),
        top,
    )
    g = block(
        "stage-2",
        "03 托盘范围 / 首槽 / 3×6 阵列",
        old_groups["stage-2"]["member_node_ids"],
        right(g),
        top,
        "#10b981",
    )
    g = block(
        "inspection-extract",
        "04A 当前图与参考图前景",
        old_groups["inspection-extract"]["member_node_ids"],
        right(g),
        top,
        "#10b981",
    )
    check_x = right(g)
    keys = [
        "reference_area",
        "reference_boundary",
        "missing",
        "excess",
        "shift",
        "angle",
        "boundary",
    ]
    labels = [
        "参考面积",
        "参考边界",
        "前景缺失",
        "前景多出",
        "质心偏移",
        "放置角度",
        "超出槽位",
    ]
    measures = [
        None,
        "reference_outside",
        "missing",
        "excess",
        "pose_difference",
        None,
        "current_outside",
    ]
    g = block(
        "inspection-checks",
        "04B 七项独立检查 · 从上到下读取",
        old_groups["inspection-checks"]["member_node_ids"],
        check_x,
        top,
        "#fab005",
    )
    cell = 410
    measure_height = max(height(k) for k in measures if k)
    check_height = max(height("check_" + k) for k in keys)
    field_height = max(height("check_field_" + k) for k in keys)
    for i, key in enumerate(keys):
        xx = check_x + 40 + i * cell
        if measures[i]:
            nodes[measures[i]]["ui_state"].update(x=xx, y=top + 210)
        nodes["check_" + key]["ui_state"].update(
            x=xx, y=top + 210 + measure_height + 80
        )
        nodes["check_field_" + key]["ui_state"].update(
            x=xx, y=top + 210 + measure_height + 80 + check_height + 80
        )
    g["rect"].update(
        width=7 * cell + 20,
        height=210 + measure_height + 80 + check_height + 80 + field_height + 60,
    )
    evidence_y = bottom(g)
    evidence = block(
        "inspection-evidence",
        "04C 每项数据与证据图（可整组禁用）",
        old_groups["inspection-evidence"]["member_node_ids"],
        check_x,
        evidence_y,
        "#2f80ed",
    )
    value_height = max(height("values_" + k) for k in keys)
    draw_height = max(height("evidence_" + k) for k in keys)
    gallery_height = max(height("gallery_" + k) for k in keys)
    for i, key in enumerate(keys):
        xx = check_x + 40 + i * cell
        nodes["values_" + key]["ui_state"].update(x=xx, y=evidence_y + 210)
        nodes["evidence_" + key]["ui_state"].update(
            x=xx, y=evidence_y + 210 + value_height + 80
        )
        nodes["gallery_" + key]["ui_state"].update(
            x=xx, y=evidence_y + 210 + value_height + 80 + draw_height + 80
        )
    evidence["rect"].update(
        width=g["rect"]["width"],
        height=210 + value_height + 80 + draw_height + 80 + gallery_height + 60,
    )
    notes = [
        deepcopy(n) for n in template["notes"] if not n["note_id"].startswith("layout-")
    ]
    for target in [g, evidence]:
        for i, label in enumerate(labels):
            nid = f"layout-{target['group_id']}-{i}"
            notes.append(
                dict(
                    note_id=nid,
                    title=label,
                    content="",
                    content_format="markdown",
                    rect=dict(
                        x=check_x + 40 + i * cell,
                        y=target["rect"]["y"] + 80,
                        width=330,
                        height=120,
                    ),
                    tone="info",
                    collapsed=True,
                    locked=True,
                    metadata={},
                )
            )
            target["member_note_ids"].append(nid)
    g = block(
        "inspection-summary",
        "04D 放置结果 / 正常槽位筛选",
        old_groups["inspection-summary"]["member_node_ids"],
        right(g),
        top,
        "#10b981",
    )
    g = block(
        "stage-4",
        "05 手选条码窗口 / 批量裁剪",
        old_groups["stage-4"]["member_node_ids"],
        right(g),
        top,
    )
    batch_x = right(g)
    g = block(
        "stage-5",
        "06 条码批量检测 / 空列表分支",
        old_groups["stage-5"]["member_node_ids"],
        batch_x,
        top,
    )
    g = block(
        "stage-6",
        "07 条码框外扩 / 裁剪 / 解析",
        old_groups["stage-6"]["member_node_ids"],
        right(g),
        top,
    )
    g = block(
        "stage-7",
        "08 按槽位 ID 汇总读码",
        old_groups["stage-7"]["member_node_ids"],
        right(g),
        top,
        "#10b981",
    )

    # 最终输出拆分为可读的子流程，放在读码区域下方，避免单个 86 节点大框。
    final_top = (
        max(
            bottom(group)
            for group in groups
            if group["group_id"] in {"stage-5", "stage-6", "stage-7"}
        )
        + 100
    )
    final_members = {k for k in nodes if k.startswith("final_")}
    box = [
        k
        for k in nodes
        if k in final_members
        and (
            k.startswith("final_box")
            or k.startswith("final_mapped_")
            or k
            in {
                "final_barcode_matrix",
                "final_barcode_transform",
                "final_resize_transform",
            }
        )
        and k
        not in {
            "final_mapped_groups_field",
            "final_mapped_matches",
            "final_mapped_boxes",
        }
    ]
    b = block(
        "final-coordinates",
        "09A 条码坐标 → 2500×2048 原图缩放坐标",
        ["final_has_detection", *box],
        batch_x,
        final_top,
        "#2f80ed",
    )
    context = [
        "final_barcode_groups",
        "final_placements_field",
        "final_groups_field",
        "final_mapped_groups_field",
        "final_context",
        "final_placements",
        "final_loop",
        "final_current",
        "final_item_id",
    ]
    c = block(
        "final-context", "09B 逐槽关联入口", context, batch_x, bottom(b), "#10b981"
    )
    placement = [
        k
        for k in nodes
        if k in final_members
        and (k.startswith("final_placement") or k.startswith("final_roi"))
        and k
        not in {"final_placements_field", "final_placements", "final_placement_field"}
    ]
    p = block(
        "final-placement",
        "09C 单件放置 OK/NG / 槽位 ROI",
        placement,
        right(c),
        c["rect"]["y"],
        "#10b981",
    )
    barcode = [
        "final_barcode_matches",
        "final_match_count",
        "final_unique_match",
        "final_barcode_record",
        "final_detections",
        "final_detection_count",
        "final_detection_ok",
        "final_decode_state",
        "final_decoded",
        "final_decoded_items",
        "final_valid_codes",
        "final_one_code",
        "final_barcode_values",
        "final_barcode_decision",
        "final_barcode",
        "final_barcode_result",
        "final_barcode_state",
        "final_barcode_texts",
        "final_mapped_matches",
        "final_mapped_boxes",
        "final_barcode_boxes",
    ]
    bc = block(
        "final-barcode",
        "09D 单件条码 OK/NG / bbox / 解析值",
        barcode,
        right(c),
        bottom(p),
        "#10b981",
    )
    item = [
        "final_item_decision",
        "final_item",
        "final_item_id_field",
        "final_placement_field",
        "final_barcode_field",
        "final_item_result",
        "final_end",
    ]
    it = block(
        "final-item",
        "09E 单件 JSON / 18 槽循环结束",
        item,
        max(right(p), right(bc)),
        c["rect"]["y"],
        "#10b981",
    )
    remaining = [k for k in nodes if k in final_members and k not in used]
    last = block(
        "final-result",
        "10 整盘总判定 / JSON 返回",
        remaining,
        right(it),
        c["rect"]["y"],
        "#10b981",
    )
    if used != set(nodes):
        raise ValueError(f"未分组节点：{set(nodes) - used}")
    guide = next(n for n in notes if n["note_id"] == "guide")
    guide.update(
        title="正面工作流 · 阅读顺序", rect=dict(x=400, y=-100, width=1600, height=380)
    )
    guide["content"] = (
        "主流程从左向右：01 输入 → 02 定位与配准 → 03 首槽与阵列 → 04 放置检查 → 05 条码窗口 → 06 批量检测 → 07 裁剪读码 → 08 按槽位汇总。\n\n04B 的七列与 04C 的七列一一对应：上方检查，下方数据、证据绘制和图库。04C 可整组禁用。\n\n读码区域下方：09A 转换条码坐标，09B 按槽位 ID 关联，09C/09D 生成放置与条码结果，09E 合并单件 JSON，10 输出整盘判定。全部返回坐标属于原图 resize 后的 2500×2048 图像。\n\nROI Grid Create 编辑首槽与 3×6 阵列；05 的 ROI Create 编辑条码窗口，当前初始尺寸 1000×1000。参考图用于二维前景检查，不能证明无翘起，现场缺陷准确率仍需实物验收。"
    )
    template.update(groups=groups, notes=notes)
    editor = (
        result["application"]
        .setdefault("metadata", {})
        .setdefault("workflow_graph_editor", {})
    )
    editor["boundary_positions"] = {
        "entry": {"x": 0, "y": top + 90},
        "result": {"x": right(last), "y": last["rect"]["y"] + 90},
    }
    assert executable(payload) == executable(result), "布局修改污染了执行配置"
    return result


def main():
    """正式 API 验证后保存草稿；不发布、不切换 Runtime。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    sizes = json.loads((OUT / "node-sizes.json").read_text("utf8"))
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
        template_url = f"/api/v1/workflows/projects/project-1/templates/{ref['template_id']}/versions/{ref['template_version']}"
        response = client.get(template_url)
        response.raise_for_status()
        original = dict(
            application=before["application"], template=response.json()["template"]
        )
        candidate = arrange(original, sizes)
        response = client.post(
            "/api/v1/workflows/applications/validate",
            json={"project_id": "project-1", **candidate},
        )
        response.raise_for_status()
        validation = response.json()
        if not validation["valid"]:
            raise ValueError(validation)
        (OUT / "candidate.json").write_text(
            json.dumps(candidate, ensure_ascii=False, indent=2), "utf8"
        )
        if args.apply:
            response = client.get(url)
            response.raise_for_status()
            if response.json()["draft_fingerprint"] != before["draft_fingerprint"]:
                raise ValueError("草稿已被修改，停止覆盖")
            response = client.put(url, json=candidate)
            response.raise_for_status()
            saved_app = client.get(url)
            saved_app.raise_for_status()
            saved_template = client.get(template_url)
            saved_template.raise_for_status()
            saved = dict(
                application=saved_app.json()["application"],
                template=saved_template.json()["template"],
            )
            assert executable(original) == executable(saved)
            (OUT / "saved.json").write_text(
                json.dumps(saved, ensure_ascii=False, indent=2), "utf8"
            )
        print(
            json.dumps(
                dict(
                    valid=True,
                    applied=args.apply,
                    nodes=len(candidate["template"]["nodes"]),
                    edges=len(candidate["template"]["edges"]),
                    groups=len(candidate["template"]["groups"]),
                    executable_unchanged=True,
                )
            )
        )


if __name__ == "__main__":
    main()
