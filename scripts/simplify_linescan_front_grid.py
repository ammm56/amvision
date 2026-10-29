"""通过正式草稿 API 将正面首槽和阵列合并为通用 ROI Grid Create。"""

import argparse
import copy
import json

import httpx

from backend.service.application.auth.default_local_auth_seeder import (
    DEFAULT_LOCAL_AUTH_TOKEN,
)
from backend.nodes.core_nodes.vision.roi.roi_grid_create import _roi_grid_create_handler
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)
from scripts.configure_linescan_3913_workflow import APP_ID, DATA

OUT = DATA / "validation/grid-interaction-20261029"


def build(application, template):
    """只简化几何来源与首槽提取，保留定位、比较、模型、读码参数和现有布局。"""
    application, template = copy.deepcopy(application), copy.deepcopy(template)
    nodes = {n["node_id"]: n for n in template["nodes"]}
    if nodes["slot_array"]["node_type_id"] == "core.vision.roi-grid-create":
        return dict(application=application, template=template)
    seed = nodes["slot_seed"]["parameters"]["polygon_xy"]
    frame = nodes["tray_roi"]["parameters"]["bbox_xyxy"]
    old = nodes["slot_array"]["parameters"]
    parameters = {
        "roi_kind": "polygon",
        "polygon_xy": [[x + frame[0], y + frame[1]] for x, y in seed],
        "rows": old["rows"],
        "columns": old["columns"],
        "step_x": old["column_step_xy"][0],
        "column_step_y": old["column_step_xy"][1],
        "row_step_x": old["row_step_xy"][0],
        "step_y": old["row_step_xy"][1],
        "roi_id_prefix": old["roi_id_prefix"],
        "bounds_policy": "reject",
        "debug_image_panel_enabled": True,
        "debug_image_panel_transport_mode": "inline-base64",
    }
    # 按当前配方逐点校验，避免用视觉上相似的矩形替换不规则检查范围。
    output = _roi_grid_create_handler(
        WorkflowNodeExecutionRequest(
            node_id="slot_array",
            node_definition=object(),
            parameters=parameters,
            input_values={},
            execution_metadata={},
        )
    )
    for i, item in enumerate(output["rois"]["items"]):
        r, c = divmod(i, old["columns"])
        expected = [
            [
                x + frame[0] + c * old["column_step_xy"][0] + r * old["row_step_xy"][0],
                y + frame[1] + c * old["column_step_xy"][1] + r * old["row_step_xy"][1],
            ]
            for x, y in seed
        ]
        assert item["polygon_xy"] == expected
    nodes["slot_array"].update(
        node_type_id="core.vision.roi-grid-create", parameters=parameters
    )
    nodes["editor_slot_value"].update(
        node_type_id="core.vision.roi-list-item-get", parameters={"index": 0}
    )
    removed = {
        "slot_seed",
        "tray_roi_list",
        "tray_crop",
        "tray_image",
        "editor_slot_roi",
    }
    edges = []
    for edge in template["edges"]:
        edge = copy.deepcopy(edge)
        if edge["edge_id"] == "e084":
            edge.update(source_node_id="editor_slot_value", source_port="roi")
        if edge["source_node_id"] in removed or edge["target_node_id"] in removed:
            continue
        if edge["target_node_id"] == "slot_array" and edge["target_port"] != "image":
            continue
        if edge["target_node_id"] == "editor_slot_value":
            edge.update(source_port="rois", target_port="rois")
        edges.append(edge)
    template["edges"] = edges
    template["nodes"] = [n for n in template["nodes"] if n["node_id"] not in removed]
    for group in template["groups"]:
        group["member_node_ids"] = [
            n for n in group["member_node_ids"] if n not in removed
        ]
    # 将阵列前移到原首槽列，结果/画图排列保持原阶段与方向。
    nodes["slot_array"]["ui_state"].update(x=2698, y=466)
    for name, x, y in [
        ("draw_slots", 3018, 466),
        ("array_preview", 3338, 466),
        ("slot_crops", 3658, 466),
        ("slots_gallery", 3978, 466),
    ]:
        nodes[name]["ui_state"].update(x=x, y=y)
    for note in template.get("notes", []):
        if note["note_id"] == "guide":
            note["content"] = (
                "01 定位：当前圆心与参考圆心计算整盘位姿，先校正到参考坐标。\n"
                "02 槽位：在 ROI Grid Create 图片面板中编辑首槽多边形、行列步距与数量，生成 3 行 6 列。托盘框用于检查整盘定位；槽位直接使用校正图坐标。\n"
                "03 放置检查：正常参考图与当前图逐槽比较前景差异、偏移、角度和越界。\n"
                "04 条码：ROI List Item Get 选择首槽供编辑条码框，初始 1000×1000，可修改。正常槽位进入读码链。\n"
                "05 检测条码、外扩裁剪、解码；06 按槽位标识关联并汇总。\n\n"
                "定位和检查图为原图 1/8，读码使用原始像素。二维检查不能证明无翘起；仅有一张正常参考图，现场缺陷准确率尚未验收。"
            )
    return dict(application=application, template=template)


def main():
    """验证几何、契约和草稿并发修改后保存；不发布或切换 Runtime。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    with httpx.Client(
        base_url="http://127.0.0.1:5600",
        headers={"Authorization": "Bearer " + DEFAULT_LOCAL_AUTH_TOKEN},
        timeout=120,
    ) as client:
        url = f"/api/v1/workflows/projects/project-1/applications/{APP_ID}"
        response = client.get(url)
        response.raise_for_status()
        before = response.json()
        app = before["application"]
        ref = app["template_ref"]
        response = client.get(
            f"/api/v1/workflows/projects/project-1/templates/{ref['template_id']}/versions/{ref['template_version']}"
        )
        response.raise_for_status()
        template = response.json()["template"]
        payload = build(app, template)
        result = client.post(
            "/api/v1/workflows/applications/validate",
            json={"project_id": "project-1", **payload},
        )
        result.raise_for_status()
        assert result.json()["valid"], result.text
        (OUT / "grid-workflow.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), "utf-8"
        )
        print("validated", len(payload["template"]["nodes"]), "nodes")
        if args.apply:
            current = client.get(url)
            current.raise_for_status()
            assert current.json()["draft_fingerprint"] == before["draft_fingerprint"], (
                "草稿在验证期间已变化"
            )
            result = client.put(url, json=payload)
            result.raise_for_status()
            (OUT / "after.json").write_text(
                json.dumps(result.json(), ensure_ascii=False, indent=2), "utf-8"
            )
            print("saved", result.status_code)


if __name__ == "__main__":
    main()
