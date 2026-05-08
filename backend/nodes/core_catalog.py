"""内建 core nodes 与 payload contract 目录。"""

from __future__ import annotations

from functools import lru_cache

from backend.contracts.workflows.workflow_graph import NodeDefinition, WorkflowPayloadContract
from backend.nodes.core_nodes import get_core_node_specs


@lru_cache(maxsize=1)
def get_core_workflow_payload_contracts() -> tuple[WorkflowPayloadContract, ...]:
    """返回 backend 内建的最小 payload contract 目录。

    返回：
    - tuple[WorkflowPayloadContract, ...]：内建 payload contract 列表。
    """

    return (
        WorkflowPayloadContract(
            payload_type_id="image-ref.v1",
            display_name="Image Reference",
            transport_kind="hybrid",
            json_schema={
                "type": "object",
                "properties": {
                    "transport_kind": {
                        "type": "string",
                        "enum": ["memory", "storage"],
                    },
                    "object_key": {"type": "string"},
                    "image_handle": {"type": "string"},
                    "width": {"type": "integer"},
                    "height": {"type": "integer"},
                    "media_type": {"type": "string"},
                },
                "required": ["transport_kind", "media_type"],
                "oneOf": [
                    {
                        "properties": {
                            "transport_kind": {"const": "storage"},
                        },
                        "required": ["object_key"],
                    },
                    {
                        "properties": {
                            "transport_kind": {"const": "memory"},
                        },
                        "required": ["image_handle"],
                    },
                ],
            },
            artifact_kinds=("image",),
        ),
        WorkflowPayloadContract(
            payload_type_id="image-base64.v1",
            display_name="Image Base64 Input",
            transport_kind="inline-json",
            json_schema={
                "type": "object",
                "properties": {
                    "image_base64": {
                        "type": "string",
                        "minLength": 1,
                    },
                    "media_type": {"type": "string"},
                    "width": {"type": "integer"},
                    "height": {"type": "integer"},
                },
                "required": ["image_base64"],
            },
        ),
        WorkflowPayloadContract(
            payload_type_id="image-refs.v1",
            display_name="Image References",
            transport_kind="inline-json",
            json_schema={
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "transport_kind": {
                                    "type": "string",
                                    "enum": ["memory", "storage"],
                                },
                                "object_key": {"type": "string"},
                                "image_handle": {"type": "string"},
                                "width": {"type": "integer"},
                                "height": {"type": "integer"},
                                "media_type": {"type": "string"},
                                "bbox_xyxy": {"type": "array"},
                                "crop_index": {"type": "integer"},
                            },
                            "required": ["transport_kind", "media_type"],
                            "oneOf": [
                                {
                                    "properties": {
                                        "transport_kind": {"const": "storage"},
                                    },
                                    "required": ["object_key"],
                                },
                                {
                                    "properties": {
                                        "transport_kind": {"const": "memory"},
                                    },
                                    "required": ["image_handle"],
                                },
                            ],
                        },
                    },
                    "count": {"type": "integer"},
                    "source_image": {
                        "type": "object",
                        "properties": {
                            "transport_kind": {
                                "type": "string",
                                "enum": ["memory", "storage"],
                            },
                            "object_key": {"type": "string"},
                            "image_handle": {"type": "string"},
                            "width": {"type": "integer"},
                            "height": {"type": "integer"},
                            "media_type": {"type": "string"},
                        },
                        "required": ["transport_kind", "media_type"],
                        "oneOf": [
                            {
                                "properties": {
                                    "transport_kind": {"const": "storage"},
                                },
                                "required": ["object_key"],
                            },
                            {
                                "properties": {
                                    "transport_kind": {"const": "memory"},
                                },
                                "required": ["image_handle"],
                            },
                        ],
                    },
                    "source_object_key": {"type": "string"},
                },
                "required": ["items"],
            },
            artifact_kinds=("image",),
        ),
        WorkflowPayloadContract(
            payload_type_id="detections.v1",
            display_name="Detection Result",
            transport_kind="inline-json",
            json_schema={
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "bbox_xyxy": {"type": "array"},
                                "score": {"type": "number"},
                                "class_name": {"type": "string"},
                            },
                            "required": ["bbox_xyxy", "score"],
                        },
                    }
                },
                "required": ["items"],
            },
        ),
        WorkflowPayloadContract(
            payload_type_id="response-body.v1",
            display_name="Response Body",
            transport_kind="inline-json",
            json_schema={"type": "object"},
        ),
        WorkflowPayloadContract(
            payload_type_id="http-response.v1",
            display_name="HTTP Response",
            transport_kind="inline-json",
            json_schema={
                "type": "object",
                "properties": {
                    "status_code": {"type": "integer"},
                    "body": {"type": "object"},
                },
                "required": ["status_code", "body"],
            },
        ),
    )


@lru_cache(maxsize=1)
def get_core_workflow_node_definitions() -> tuple[NodeDefinition, ...]:
    """返回 backend 内建的最小 core node 目录。

    返回：
    - tuple[NodeDefinition, ...]：从 core_nodes 目录扫描得到的 NodeDefinition 列表。
    """

    return tuple(core_node_spec.node_definition for core_node_spec in get_core_node_specs())
