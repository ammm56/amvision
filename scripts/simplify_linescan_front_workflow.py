"""在已有批量检测配方上简化裁剪与结果汇总，保存前核对草稿指纹。"""

import argparse
from copy import deepcopy
import json

import httpx

from backend.service.application.auth.default_local_auth_seeder import (
    DEFAULT_LOCAL_AUTH_TOKEN,
)
from scripts.configure_linescan_3913_workflow import APP_ID, DATA
from scripts.configure_linescan_front_result import build as build_result


def build(application, template):
    """一次批量裁剪替代逐槽准备循环；保持手选窗口、空列表和逐槽 ID 关联。"""
    application, template = deepcopy(application), deepcopy(template)
    nodes = {n["node_id"]: n for n in template["nodes"]}
    removed = {
        "barcode_loop",
        "part_roi_value",
        "part_roi",
        "prepared_image",
        "barcode_passed_field",
        "barcode_context",
        "barcode_context_items",
    }
    edges = [
        e
        for e in template["edges"]
        if e["source_node_id"] not in removed
        and e["target_node_id"] not in removed
        and e["target_node_id"] not in {"prepared_value", "prepared_end"}
    ]
    for e in edges:
        if e["source_node_id"] == "prepared_end":
            e["source_port"] = "value"
    nodes["prepared_value"].update(
        node_type_id="core.logic.payload-to-value", parameters={}
    )
    nodes["prepared_end"].update(
        node_type_id="core.logic.value-field-extract", parameters={"path": "items"}
    )
    nodes["decoded_source"]["parameters"]["decode_method"] = "bmp-bgr24"
    nodes["passed_ids"] = dict(
        node_id="passed_ids",
        node_type_id="core.logic.list-map",
        parameters={"path": "item_id", "skip_missing": False},
        enabled=True,
        metadata={},
        ui_state={},
    )
    for source, port, target, target_port in [
        ("passed_items", "value", "passed_ids", "items"),
        ("passed_ids", "value", "crop_search", "selected_ids"),
        ("slot_array", "rois", "crop_search", "rois"),
        ("crop_search", "crops", "prepared_value", "images"),
        ("prepared_value", "value", "prepared_end", "value"),
    ]:
        # 幂等配置：已有同一目标端口先移除，禁止多输入歧义。
        edges = [
            e
            for e in edges
            if (e["target_node_id"], e["target_port"]) != (target, target_port)
        ]
        edges.append(
            dict(
                edge_id="opt-" + target + "-" + target_port,
                source_node_id=source,
                source_port=port,
                target_node_id=target,
                target_port=target_port,
            )
        )
    template["nodes"] = [n for key, n in nodes.items() if key not in removed]
    template["edges"] = edges
    for group in template["groups"]:
        group["member_node_ids"] = [
            n for n in group["member_node_ids"] if n not in removed
        ]
        if group["group_id"] == "stage-4":
            group["name"] = "04 手选条码窗口 / 正常槽位批量裁剪"
            group["member_node_ids"] = [
                "editor_slot_value",
                "crop_part",
                "part_image",
                "part_display_encode",
                "barcode_roi",
                "roi_field",
                "passed_ids",
                "crop_search",
                "prepared_value",
                "prepared_end",
            ]
            for index, name in enumerate(group["member_node_ids"]):
                column, row = divmod(index, 3)
                nodes[name]["ui_state"] = {
                    "x": group["rect"]["x"] + 40 + column * 450,
                    "y": group["rect"]["y"] + 80 + row * 550,
                    "width": 350,
                }
            group["rect"].update(width=1900, height=1750)
    return build_result(application, template)


def main():
    """只更新草稿，不发布、不切换现场 Runtime。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    out = DATA / "validation/front-optimization-20261030"
    out.mkdir(parents=True, exist_ok=True)
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
        original = {
            "application": before["application"],
            "template": response.json()["template"],
        }
        payload = build(**original)
        (out / "candidate.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), "utf-8"
        )
        response = client.post(
            "/api/v1/workflows/applications/validate",
            json={"project_id": "project-1", **payload},
        )
        if response.is_error:
            raise RuntimeError(response.text)
        response.raise_for_status()
        validation = response.json()
        (out / "candidate.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), "utf-8"
        )
        if not validation["valid"]:
            raise ValueError(validation)
        if args.apply:
            current = client.get(url)
            current.raise_for_status()
            if current.json()["draft_fingerprint"] != before["draft_fingerprint"]:
                raise ValueError("草稿在验证期间被修改")
            (out / "before.json").write_text(
                json.dumps(original, ensure_ascii=False, indent=2), "utf-8"
            )
            response = client.put(url, json=payload)
            response.raise_for_status()
        print(
            "validated", len(payload["template"]["nodes"]), "nodes; applied", args.apply
        )


if __name__ == "__main__":
    main()
