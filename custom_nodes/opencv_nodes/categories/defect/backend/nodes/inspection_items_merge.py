"""按显式检查名称和区域标识汇总判定。"""

from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.nodes.core_nodes.support.region import build_regions_payload
from backend.service.application.errors import InvalidRequestError
from .inspection_items import read_records, same_source

NODE_TYPE_ID = "custom.opencv.inspection-items-merge"


def handle_node(request):
    """检查集合由 Create Object 命名端口提供，禁止缺项或重复检查混入。"""
    payload = request.input_values.get("checks")
    body = payload.get("value") if isinstance(payload, dict) else None
    if not isinstance(body, dict) or not body or len(body) > 64:
        raise InvalidRequestError("汇总输入必须是非空的检查名称到检查记录的对象")
    groups = {}
    for name, value in body.items():
        group = read_records(
            value if isinstance(value, dict) and "value" in value else {"value": value},
            expected_format="amvision.inspection-check-items.v1",
        )
        for item in group.values():
            result = item["result"]
            if (
                result.get("check_id") != name
                or not isinstance(result.get("passed"), bool)
                or result.get("state") not in {"pass", "fail", "unavailable"}
            ):
                raise InvalidRequestError("检查名称、状态或 passed 不符合检查记录契约")
            if result["passed"] != (result["state"] == "pass"):
                raise InvalidRequestError("检查状态与 passed 不一致")
        groups[name] = group
    first = next(iter(groups.values()))
    if any(group.keys() != first.keys() for group in groups.values()):
        raise InvalidRequestError("各项检查的区域标识集合不完整")
    items, regions = [], []
    for key, base in first.items():
        for group in groups.values():
            same_source(base["source"], group[key]["source"])
        checks = {name: group[key]["result"] for name, group in groups.items()}
        failed = [
            name for name, result in checks.items() if result["passed"] is not True
        ]
        result = {
            "passed": not failed,
            "state": "pass"
            if not failed
            else "unavailable"
            if any(c["state"] == "unavailable" for c in checks.values())
            else "fail",
            "reasons": failed,
            "checks": checks,
        }
        source = base["source"]
        items.append({"item_id": key, "source": source, "result": result})
        regions.append(
            {
                "region_id": key,
                "class_id": 0 if not failed else 1,
                "class_name": result["state"],
                "score": 1.0,
                "bbox_xyxy": source["bbox_xyxy"],
                "polygon_xy": source["polygon_xy"],
                "area": source["area"],
            }
        )
    summary = {
        "format_id": "amvision.inspection-items.v1",
        "count": len(items),
        "passed": all(item["result"]["passed"] for item in items),
        "items": items,
        "check_ids": list(groups),
    }
    return {
        "summary": build_value_payload(summary),
        "regions": build_regions_payload(
            source_image=request.input_values.get("image"),
            selected_frame_index=None,
            items=regions,
        ),
    }
