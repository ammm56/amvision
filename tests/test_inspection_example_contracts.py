"""当前示例与 API/Postman 副本不能继续引用已删除的结果字段。"""

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UPDATED_TEMPLATES = (
    "plc_register_modbus_tcp_async_result_record",
    "plc_modbus_wait_ready_ack_callback",
    "industrial_single_frame_glue_roi_delivery_bundle",
    "industrial_single_frame_glue_roi_modbus_callback",
    "industrial_single_frame_glue_roi_modbus_callback_strict",
)


def _objects(value):
    """结构化读取 JSON 以及 Postman raw JSON，不依赖文本替换。"""
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from _objects(child)
    elif isinstance(value, str) and value.lstrip().startswith("{"):
        try:
            parsed = json.loads(value)
        except ValueError:
            return
        yield from _objects(parsed)


def test_example_result_mappings_and_embedded_templates_are_current():
    """外部目标列名可以自定；内部结果来源必须使用当前契约。"""
    templates = {}
    for name in UPDATED_TEMPLATES:
        value = json.loads(
            (ROOT / "docs/examples/workflows" / f"{name}.template.json").read_text(
                "utf-8"
            )
        )
        templates[value["template_id"]] = value
    paths = list((ROOT / "docs/examples/workflows").glob("*.json"))
    paths.extend((ROOT / "docs/api").rglob("*.json"))
    for path in paths:
        for value in _objects(json.loads(path.read_text("utf-8-sig"))):
            if (
                value.get("source_kind") == "result"
                or value.get("source_scope") == "result"
            ):
                assert value.get("source_path") not in ("ok", "ok_ng"), (path, value)
            if (
                value.get("format_id") == "amvision.workflow-graph-template.v1"
                and value.get("template_id") in templates
            ):
                assert value == templates[value["template_id"]], path
