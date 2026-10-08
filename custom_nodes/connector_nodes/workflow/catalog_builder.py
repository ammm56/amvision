"""由单一 Pydantic 契约生成节点目录，避免表单与处理器参数漂移。"""

import json
from pathlib import Path

from backend.contracts.nodes.node_pack_manifest import (
    CUSTOM_NODE_CATALOG_FORMAT,
    CustomNodeCatalogDocument,
)
from backend.contracts.workflows.schema_helpers import inline_model_schema as _schema
from backend.contracts.workflows.metrology import ResourceReference
from backend.contracts.workflows.workflow_graph import (
    WorkflowPayloadContract,
    validate_node_definition_catalog,
)
from backend.nodes.core_catalog import get_core_workflow_payload_contracts
from custom_nodes.connector_nodes.shared.contracts import (
    MeasurementDefinition,
    PinLayout,
    PinObservations,
)
from custom_nodes.opencv_nodes.shared.workflow.payload_contracts import (
    load_shared_opencv_payload_contracts_payload,
    merge_payload_contracts_for_validation,
)


def _port(name, payload, required=True):
    """构造明确的公开端口；显示名保持简洁。"""
    return dict(
        name=name,
        display_name=name.replace("_", " ").title(),
        payload_type_id=payload,
        required=required,
    )


def build_custom_node_catalog_document() -> CustomNodeCatalogDocument:
    """固定行业端口；通用身份契约在独立公共模型中定义。"""
    payloads = [
        WorkflowPayloadContract(
            payload_type_id=key,
            display_name=name,
            transport_kind="inline-json",
            json_schema=model.model_json_schema(),
        )
        for key, name, model in (
            ("connector-pins.v1", "Connector Pins", PinObservations),
        )
    ]
    nodes = []
    for key, name, category, description, inputs, outputs, schema in (
        (
            "pin-array-locate",
            "Pin Array Locate",
            "connector.inspection.array",
            "按参考布局提取固定身份 PIN 和有限边缘，不判定最终 OK/NG。",
            [_port("image", "image-ref.v1"), _port("pose", "image-pose.v1", False)],
            [
                _port("pins", "connector-pins.v1"),
                _port("features", "geometric-features.v1"),
                _port("checks", "numeric-table.v1"),
                _port("summary", "value.v1"),
                _port("debug_preview", "response-body.v1", False),
            ],
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["layout"],
                "properties": {
                    "pose_mode": {
                        "type": "string",
                        "enum": ["input", "fixed"],
                        "default": "input",
                        "description": "Fixed 仅用于工件和图像坐标已固定的工位。",
                    },
                    "layout": _schema(PinLayout) | {"title": "PIN Layout"},
                    "debug_image_panel_enabled": {
                        "type": "boolean",
                        "title": "Debug Preview",
                        "default": False,
                        "description": "仅 Preview 生成观测几何和选中 PIN 的剖面；Runtime 不生成诊断图。",
                    },
                },
            },
        ),
        (
            "measure",
            "Connector Measure",
            "connector.measurement.dimension",
            "按固定身份测量指定特征；缺测和截面越界输出无效，公差交给 Check Limits。",
            [
                _port("pins", "connector-pins.v1"),
                _port("features", "geometric-features.v1"),
            ],
            [
                _port("measurements", "numeric-table.v1"),
                _port("summary", "value.v1"),
                _port("annotations", "value.v1"),
            ],
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["items"],
                "properties": {
                    "items": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 8192,
                        "items": _schema(MeasurementDefinition),
                        "x-ui-widget": "object-rows",
                    }
                },
            },
        ),
    ):
        nodes.append(
            dict(
                node_type_id="custom.connector." + key,
                version="0.1.8",
                display_name=name,
                category=category,
                description=description,
                implementation_kind="custom-node",
                runtime_kind="python-callable",
                node_pack_id="connector.nodes",
                node_pack_version="0.1.8",
                input_ports=inputs,
                output_ports=outputs,
                parameter_schema=schema,
                capability_tags=["vision.connector", "vision.measurement"],
            )
        )
    nodes[-1]["parameter_schema"]["properties"].update(
        {
            "unit": {
                "type": "string",
                "enum": ["pixel", "millimeter", "meter"],
                "default": "pixel",
            },
            "calibration_resource": _schema(ResourceReference)
            | {
                "title": "Calibration",
                "x-ui-widget": "measurement-resource",
                "x-resource-kind": "planar-calibration",
            },
        }
    )
    document = CustomNodeCatalogDocument(
        format_id=CUSTOM_NODE_CATALOG_FORMAT,
        payload_contracts=payloads,
        node_definitions=nodes,
    )
    opencv = tuple(
        WorkflowPayloadContract.model_validate(p)
        for p in load_shared_opencv_payload_contracts_payload()
    )
    validate_node_definition_catalog(
        node_definitions=document.node_definitions,
        payload_contracts=merge_payload_contracts_for_validation(
            core_payload_contracts=get_core_workflow_payload_contracts(),
            custom_payload_contracts=opencv + document.payload_contracts,
        ),
    )
    return document


def write_custom_node_catalog() -> Path:
    """生成随包分发的静态 Catalog。"""
    path = Path(__file__).with_name("catalog.json")
    path.write_text(
        json.dumps(
            build_custom_node_catalog_document().model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


if __name__ == "__main__":
    write_custom_node_catalog()
