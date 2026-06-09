"""workflow 示例文档的合同校验测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.contracts.workflows.workflow_graph import (
    FlowApplication,
    WorkflowGraphTemplate,
    validate_flow_application_bindings,
    validate_workflow_graph_template,
)
from backend.nodes.local_node_pack_loader import LocalNodePackLoader
from backend.nodes.node_catalog_registry import NodeCatalogRegistry


def test_yolox_deployment_detection_lifecycle_example_documents_are_valid() -> None:
    """验证 deployment lifecycle 示例模板与应用可以通过当前合同校验。"""

    example_dir = (
        Path(__file__).resolve().parents[1] / "docs" / "examples" / "workflows"
    )
    template_path = example_dir / "yolox_deployment_detection_lifecycle.template.json"
    application_path = (
        example_dir / "yolox_deployment_detection_lifecycle.application.json"
    )
    template = WorkflowGraphTemplate.model_validate(
        json.loads(template_path.read_text(encoding="utf-8"))
    )
    application = FlowApplication.model_validate(
        json.loads(application_path.read_text(encoding="utf-8"))
    )

    registry = NodeCatalogRegistry()
    validate_workflow_graph_template(
        template=template,
        node_definitions=registry.get_workflow_node_definitions(),
    )
    validate_flow_application_bindings(template=template, application=application)

    assert [node.node_id for node in template.nodes] == [
        "decode_request_image",
        "start",
        "warmup",
        "detect",
        "health",
        "stop",
    ]
    assert template.nodes[3].parameters["auto_start_process"] is False
    assert template.metadata["example_kind"] == "deployment-control-detection-lifecycle"
    assert template.metadata["uses_existing_deployment_instance"] is True
    assert template.metadata["node_groups"]["input"] == ["decode_request_image"]
    assert template.metadata["node_groups"]["deployment_control"] == [
        "start",
        "warmup",
        "health",
        "stop",
    ]
    assert [edge.edge_id for edge in template.edges] == [
        "edge-decode-detect-image",
        "edge-start-warmup-dependency",
        "edge-warmup-detect-dependency",
        "edge-detect-health-dependency",
        "edge-health-stop-dependency",
    ]
    assert template.metadata["execution_order_note"] == (
        "当前最小执行器按图边做稳定拓扑排序；"
        "该示例通过显式 dependency 边表达 start -> warmup -> detection -> health -> stop。"
    )
    assert application.template_ref.source_uri == (
        "docs/examples/workflows/yolox_deployment_detection_lifecycle.template.json"
    )
    assert (
        application.metadata["example_kind"] == "deployment-control-detection-lifecycle"
    )
    assert application.bindings[0].config["payload_type_id"] == "image-base64.v1"
    assert [binding.binding_id for binding in application.bindings] == [
        "request_image",
        "start_body",
        "warmup_body",
        "detections",
        "health_body",
        "stop_body",
    ]


def test_yolox_deployment_sync_infer_health_example_documents_are_valid() -> None:
    """验证 deployment sync infer health 示例模板与应用可以通过当前合同校验。"""

    example_dir = (
        Path(__file__).resolve().parents[1] / "docs" / "examples" / "workflows"
    )
    template_path = example_dir / "yolox_deployment_sync_infer_health.template.json"
    application_path = (
        example_dir / "yolox_deployment_sync_infer_health.application.json"
    )
    template = WorkflowGraphTemplate.model_validate(
        json.loads(template_path.read_text(encoding="utf-8"))
    )
    application = FlowApplication.model_validate(
        json.loads(application_path.read_text(encoding="utf-8"))
    )

    registry = NodeCatalogRegistry()
    validate_workflow_graph_template(
        template=template,
        node_definitions=registry.get_workflow_node_definitions(),
    )
    validate_flow_application_bindings(template=template, application=application)

    assert [node.node_id for node in template.nodes] == [
        "decode_request_image",
        "deployment_request_input",
        "start",
        "warmup",
        "detect",
        "health",
    ]
    assert template.nodes[4].parameters["auto_start_process"] is False
    assert template.metadata["example_kind"] == "deployment-sync-infer-health"
    assert template.metadata["deployment_instance_id_binding"] == "deployment_request"
    assert template.metadata["uses_existing_deployment_instance"] is True
    assert template.metadata["node_groups"]["input"] == [
        "decode_request_image",
        "deployment_request_input",
    ]
    assert template.metadata["node_groups"]["deployment_control"] == [
        "start",
        "warmup",
        "health",
    ]
    assert application.template_ref.source_uri == (
        "docs/examples/workflows/yolox_deployment_sync_infer_health.template.json"
    )
    assert application.metadata["example_kind"] == "deployment-sync-infer-health"
    assert [binding.binding_id for binding in application.bindings] == [
        "request_image",
        "deployment_request",
        "start_body",
        "warmup_body",
        "detections",
        "health_body",
    ]


def test_barcode_result_display_example_documents_are_valid() -> None:
    """验证 barcode 结果展示示例模板与应用可以通过当前合同校验。"""

    example_dir = (
        Path(__file__).resolve().parents[1] / "docs" / "examples" / "workflows"
    )
    template_path = example_dir / "barcode_result_display.template.json"
    application_path = example_dir / "barcode_result_display.application.json"
    template = WorkflowGraphTemplate.model_validate(
        json.loads(template_path.read_text(encoding="utf-8"))
    )
    application = FlowApplication.model_validate(
        json.loads(application_path.read_text(encoding="utf-8"))
    )

    custom_nodes_root = Path(__file__).resolve().parents[1] / "custom_nodes"
    node_pack_loader = LocalNodePackLoader(custom_nodes_root)
    node_pack_loader.refresh()
    registry = NodeCatalogRegistry(node_pack_loader=node_pack_loader)
    validate_workflow_graph_template(
        template=template,
        node_definitions=registry.get_workflow_node_definitions(),
    )
    validate_flow_application_bindings(template=template, application=application)

    assert [node.node_id for node in template.nodes[:5]] == [
        "decode_request_image",
        "decode",
        "draw_results",
        "image_preview",
        "summary",
    ]
    assert template.metadata["example_kind"] == "barcode-result-display"
    assert template.metadata["node_groups"]["decode_and_render"] == [
        "decode",
        "draw_results",
        "image_preview",
        "extract_image",
        "build_image_preview_value",
    ]
    assert (
        application.template_ref.source_uri
        == "docs/examples/workflows/barcode_result_display.template.json"
    )
    assert application.runtime_mode == "python-json-workflow"
    assert application.bindings[0].metadata["payload_type_id"] == "image-base64.v1"
    assert [binding.binding_id for binding in application.bindings] == [
        "request_image",
        "http_response",
    ]


def test_sam3_video_memory_attention_review_example_documents_are_valid() -> None:
    """验证 SAM3 memory-attention 视频样例模板与应用可以通过当前合同校验。"""

    example_dir = (
        Path(__file__).resolve().parents[1] / "docs" / "examples" / "workflows"
    )
    template_path = example_dir / "sam3_video_memory_attention_review.template.json"
    application_path = (
        example_dir / "sam3_video_memory_attention_review.application.json"
    )
    template = WorkflowGraphTemplate.model_validate(
        json.loads(template_path.read_text(encoding="utf-8"))
    )
    application = FlowApplication.model_validate(
        json.loads(application_path.read_text(encoding="utf-8"))
    )

    custom_nodes_root = Path(__file__).resolve().parents[1] / "custom_nodes"
    node_pack_loader = LocalNodePackLoader(custom_nodes_root)
    node_pack_loader.refresh()
    registry = NodeCatalogRegistry(node_pack_loader=node_pack_loader)
    validate_workflow_graph_template(
        template=template,
        node_definitions=registry.get_workflow_node_definitions(),
    )
    validate_flow_application_bindings(template=template, application=application)

    assert [node.node_id for node in template.nodes] == [
        "video_load_local",
        "decode_frames",
        "segment_video",
        "filter_tracks",
        "render_overlay",
        "save_video",
        "video_body",
    ]
    assert template.nodes[2].parameters["tracking_mode"] == "memory-attention-tracker"
    assert template.nodes[2].parameters["history_limit"] == 6
    assert template.nodes[2].parameters["prototype_momentum"] == 0.72
    assert template.nodes[2].parameters["attention_temperature"] == 0.12
    assert template.nodes[2].parameters["prototype_blend_weight"] == 0.35
    assert template.nodes[2].parameters["max_memory_tokens_per_entry"] == 256
    assert template.metadata["example_kind"] == "sam3-video-memory-attention-review"
    assert template.metadata["tracking_mode"] == "memory-attention-tracker"
    assert template.metadata["node_groups"]["tracking"] == [
        "segment_video",
        "filter_tracks",
    ]
    assert application.template_ref.source_uri == (
        "docs/examples/workflows/sam3_video_memory_attention_review.template.json"
    )
    assert application.runtime_mode == "python-json-workflow"
    assert [binding.binding_id for binding in application.bindings] == [
        "request_video_path",
        "request_prompts",
        "preview_body",
        "tracks",
        "summary",
    ]


@pytest.mark.parametrize(
    (
        "example_name",
        "expected_example_kind",
        "expected_wait_node_id",
        "expected_mask_operator",
        "expected_mask_decimal",
    ),
    [
        (
            "plc_modbus_wait_status_word_ready_mask",
            "plc-modbus-wait-status-word-ready-mask",
            "wait_status_word_ready",
            "bitmask_all_set",
            5,
        ),
        (
            "plc_modbus_wait_status_word_alarm_mask",
            "plc-modbus-wait-status-word-alarm-mask",
            "wait_status_word_alarm",
            "bitmask_any_set",
            48,
        ),
    ],
)
def test_plc_modbus_wait_status_word_example_documents_are_valid(
    example_name: str,
    expected_example_kind: str,
    expected_wait_node_id: str,
    expected_mask_operator: str,
    expected_mask_decimal: int,
) -> None:
    """验证 PLC Modbus 状态字 wait-condition 样例模板与应用可以通过当前合同校验。"""

    example_dir = (
        Path(__file__).resolve().parents[1] / "docs" / "examples" / "workflows"
    )
    template_path = example_dir / f"{example_name}.template.json"
    application_path = example_dir / f"{example_name}.application.json"
    template = WorkflowGraphTemplate.model_validate(
        json.loads(template_path.read_text(encoding="utf-8"))
    )
    application = FlowApplication.model_validate(
        json.loads(application_path.read_text(encoding="utf-8"))
    )

    custom_nodes_root = Path(__file__).resolve().parents[1] / "custom_nodes"
    node_pack_loader = LocalNodePackLoader(custom_nodes_root)
    node_pack_loader.refresh()
    registry = NodeCatalogRegistry(node_pack_loader=node_pack_loader)
    validate_workflow_graph_template(
        template=template,
        node_definitions=registry.get_workflow_node_definitions(),
    )
    validate_flow_application_bindings(template=template, application=application)

    assert [node.node_id for node in template.nodes] == [
        "request_wait_config_input",
        expected_wait_node_id,
        "archive_object",
        "save_archive_json",
    ]
    assert template.nodes[1].parameters["data_type"] == "uint16"
    assert template.nodes[1].parameters["operator"] == expected_mask_operator
    assert template.nodes[1].parameters["expected_value"] == expected_mask_decimal
    assert template.nodes[1].parameters["wait_timeout_seconds"] is None
    assert template.metadata["example_kind"] == expected_example_kind
    assert template.metadata["focus"] == "plc-modbus-wait-status-word-mask"
    assert template.metadata["mask_operator"] == expected_mask_operator
    assert template.metadata["default_mask_decimal"] == expected_mask_decimal
    assert [template_input.input_id for template_input in template.template_inputs] == [
        "request_wait_config"
    ]
    assert template.template_inputs[0].payload_type_id == "value.v1"
    assert application.template_ref.source_uri == (
        f"docs/examples/workflows/{example_name}.template.json"
    )
    assert application.runtime_mode == "python-json-workflow"
    assert [binding.binding_id for binding in application.bindings] == [
        "request_wait_config",
        "wait_result",
        "archive",
        "json_summary",
    ]


def test_plc_modbus_wait_ready_ack_callback_example_documents_are_valid() -> None:
    """验证 PLC Modbus ready -> ack -> callback 样例模板与应用可以通过当前合同校验。"""

    example_dir = (
        Path(__file__).resolve().parents[1] / "docs" / "examples" / "workflows"
    )
    template_path = example_dir / "plc_modbus_wait_ready_ack_callback.template.json"
    application_path = example_dir / "plc_modbus_wait_ready_ack_callback.application.json"
    template = WorkflowGraphTemplate.model_validate(
        json.loads(template_path.read_text(encoding="utf-8"))
    )
    application = FlowApplication.model_validate(
        json.loads(application_path.read_text(encoding="utf-8"))
    )

    custom_nodes_root = Path(__file__).resolve().parents[1] / "custom_nodes"
    node_pack_loader = LocalNodePackLoader(custom_nodes_root)
    node_pack_loader.refresh()
    registry = NodeCatalogRegistry(node_pack_loader=node_pack_loader)
    validate_workflow_graph_template(
        template=template,
        node_definitions=registry.get_workflow_node_definitions(),
    )
    validate_flow_application_bindings(template=template, application=application)

    assert [node.node_id for node in template.nodes] == [
        "request_wait_config_input",
        "request_ack_write_config_input",
        "wait_status_word_ready",
        "build_ack_write_request",
        "write_ack_signal",
        "extract_wait_matched",
        "compare_wait_matched",
        "decide_result",
        "build_result_metrics",
        "build_result_metadata",
        "inspection_result",
        "callback_result",
    ]
    assert template.nodes[2].parameters["data_type"] == "uint16"
    assert template.nodes[2].parameters["operator"] == "bitmask_all_set"
    assert template.nodes[2].parameters["expected_value"] == 5
    assert template.nodes[2].parameters["wait_timeout_seconds"] == 60.0
    assert template.nodes[4].parameters["data_type"] == "bool"
    assert template.nodes[4].parameters["value"] is True
    assert template.nodes[6].parameters["right_value"] is True
    assert template.nodes[11].parameters["url"] == "http://127.0.0.1:18080/plc/modbus/handshake-result"
    assert template.metadata["example_kind"] == "plc-modbus-wait-ready-ack-callback"
    assert template.metadata["focus"] == "plc-modbus-handshake-callback"
    assert [template_input.input_id for template_input in template.template_inputs] == [
        "request_wait_config",
        "request_ack_write_config",
    ]
    assert [template_output.output_id for template_output in template.template_outputs] == [
        "wait_result",
        "ack_write_result",
        "inspection_result",
        "decision_summary",
        "callback_response",
    ]
    assert application.template_ref.source_uri == (
        "docs/examples/workflows/plc_modbus_wait_ready_ack_callback.template.json"
    )
    assert application.runtime_mode == "python-json-workflow"
    assert [binding.binding_id for binding in application.bindings] == [
        "request_wait_config",
        "request_ack_write_config",
        "wait_result",
        "ack_write_result",
        "inspection_result",
        "decision_summary",
        "callback_response",
    ]


def test_plc_register_modbus_tcp_async_result_record_example_documents_are_valid() -> None:
    """验证 plc-register TriggerSource 回传样例模板与应用可以通过当前合同校验。"""

    example_dir = (
        Path(__file__).resolve().parents[1] / "docs" / "examples" / "workflows"
    )
    template_path = example_dir / "plc_register_modbus_tcp_async_result_record.template.json"
    application_path = example_dir / "plc_register_modbus_tcp_async_result_record.application.json"
    template = WorkflowGraphTemplate.model_validate(
        json.loads(template_path.read_text(encoding="utf-8"))
    )
    application = FlowApplication.model_validate(
        json.loads(application_path.read_text(encoding="utf-8"))
    )

    registry = NodeCatalogRegistry()
    validate_workflow_graph_template(
        template=template,
        node_definitions=registry.get_workflow_node_definitions(),
    )
    validate_flow_application_bindings(template=template, application=application)

    assert [node.node_id for node in template.nodes] == [
        "wrap_trigger_payload",
        "wrap_trigger_event",
        "extract_event_matched",
        "compare_event_matched",
        "extract_observed_value",
        "extract_previous_observed_value",
        "extract_sequence_id",
        "decide_result",
        "build_result_metrics",
        "build_result_metadata",
        "inspection_alarm",
        "inspection_result",
        "callback_result",
    ]
    assert template.nodes[0].node_type_id == "core.logic.payload-to-value"
    assert template.nodes[1].node_type_id == "core.logic.payload-to-value"
    assert template.nodes[3].parameters["right_value"] is True
    assert template.nodes[10].parameters["alarm_code"] == "PLC-REGISTER-NG"
    assert template.nodes[12].parameters["url"] == "http://127.0.0.1:18080/plc/register/result"
    assert template.metadata["example_kind"] == "plc-register-modbus-tcp-async-result-record"
    assert template.metadata["focus"] == "plc-register-trigger-result-callback"
    assert template.metadata["trigger_source_kind"] == "plc-register"
    assert [template_input.input_id for template_input in template.template_inputs] == [
        "request_trigger_payload",
        "request_trigger_event",
    ]
    assert [template_input.payload_type_id for template_input in template.template_inputs] == [
        "response-body.v1",
        "response-body.v1",
    ]
    assert [template_output.output_id for template_output in template.template_outputs] == [
        "inspection_result",
        "inspection_alarm",
        "decision_summary",
        "callback_response",
    ]
    assert application.template_ref.source_uri == (
        "docs/examples/workflows/plc_register_modbus_tcp_async_result_record.template.json"
    )
    assert application.runtime_mode == "python-json-workflow"
    assert [binding.binding_id for binding in application.bindings] == [
        "request_trigger_payload",
        "request_trigger_event",
        "inspection_result",
        "inspection_alarm",
        "decision_summary",
        "callback_response",
    ]
    assert application.bindings[0].metadata["source_path"] == "payload"
    assert application.bindings[1].metadata["source_path"] == "event"


@pytest.mark.parametrize(
    (
        "example_name",
        "expected_example_kind",
        "expected_node_ids",
        "expected_input_ids",
        "expected_binding_ids",
    ),
    [
        (
            "industrial_single_frame_sealant_quality_gate",
            "industrial-single-frame-sealant-quality-gate",
            [
                "request_image_path_input",
                "load_image",
                "filter_regions",
                "area_ratio",
                "continuity_score",
                "gap_check",
                "presence_check",
                "area_ratio_check",
                "metadata_object",
                "metrics_object",
                "process_decision",
                "alarm_condition",
                "save_result_json",
                "append_result_csv",
            ],
            [
                "request_image_path",
                "request_regions",
            ],
            [
                "request_image_path",
                "request_regions",
                "inspection_result",
                "inspection_alarm",
                "decision_summary",
                "json_summary",
                "csv_summary",
            ],
        ),
        (
            "industrial_single_frame_glue_roi_callback",
            "industrial-single-frame-glue-roi-callback",
            [
                "request_image_path_input",
                "load_image",
                "filter_regions",
                "create_roi",
                "coverage_check",
                "offset_check",
                "intersection_metrics",
                "metadata_object",
                "metrics_object",
                "process_decision",
                "alarm_condition",
                "save_result_json",
                "append_result_csv",
                "callback_result",
            ],
            [
                "request_image_path",
                "request_regions",
                "request_roi",
            ],
            [
                "request_image_path",
                "request_regions",
                "request_roi",
                "inspection_result",
                "inspection_alarm",
                "decision_summary",
                "json_summary",
                "csv_summary",
                "callback_response",
            ],
        ),
        (
            "industrial_single_frame_glue_polygon_roi_changeover",
            "industrial-single-frame-glue-polygon-roi-changeover",
            [
                "request_image_path_input",
                "load_image",
                "filter_regions",
                "create_roi",
                "coverage_check",
                "inside_check",
                "intersection_metrics",
                "metadata_object",
                "metrics_object",
                "process_decision",
                "alarm_condition",
                "save_result_json",
                "append_result_csv",
                "callback_result",
            ],
            [
                "request_image_path",
                "request_regions",
                "request_roi",
            ],
            [
                "request_image_path",
                "request_regions",
                "request_roi",
                "inspection_result",
                "inspection_alarm",
                "decision_summary",
                "json_summary",
                "csv_summary",
                "callback_response",
            ],
        ),
    ],
)
def test_industrial_single_frame_example_documents_are_valid(
    example_name: str,
    expected_example_kind: str,
    expected_node_ids: list[str],
    expected_input_ids: list[str],
    expected_binding_ids: list[str],
) -> None:
    """验证工业单帧规则样例模板与应用可以通过当前合同校验。"""

    example_dir = (
        Path(__file__).resolve().parents[1] / "docs" / "examples" / "workflows"
    )
    template_path = example_dir / f"{example_name}.template.json"
    application_path = example_dir / f"{example_name}.application.json"
    template = WorkflowGraphTemplate.model_validate(
        json.loads(template_path.read_text(encoding="utf-8"))
    )
    application = FlowApplication.model_validate(
        json.loads(application_path.read_text(encoding="utf-8"))
    )

    registry = NodeCatalogRegistry()
    validate_workflow_graph_template(
        template=template,
        node_definitions=registry.get_workflow_node_definitions(),
    )
    validate_flow_application_bindings(template=template, application=application)

    assert [node.node_id for node in template.nodes] == expected_node_ids
    assert template.metadata["example_kind"] == expected_example_kind
    assert template.metadata["focus"] == "single-frame-industrial-rule-chain"
    assert [
        template_input.input_id for template_input in template.template_inputs
    ] == expected_input_ids
    assert template.template_inputs[0].payload_type_id == "value.v1"
    assert template.template_inputs[1].payload_type_id == "regions.v1"
    if example_name in {
        "industrial_single_frame_glue_roi_callback",
        "industrial_single_frame_glue_polygon_roi_changeover",
    }:
        assert template.template_inputs[2].payload_type_id == "value.v1"
        assert template.template_inputs[2].required is False
        assert template.metadata["dynamic_roi_input_binding"] == "request_roi"
    assert (
        application.template_ref.source_uri
        == f"docs/examples/workflows/{example_name}.template.json"
    )
    assert application.runtime_mode == "python-json-workflow"
    assert [
        binding.binding_id for binding in application.bindings
    ] == expected_binding_ids
    if example_name in {
        "industrial_single_frame_glue_roi_callback",
        "industrial_single_frame_glue_polygon_roi_changeover",
    }:
        assert application.bindings[2].required is False
        assert application.bindings[2].metadata["payload_type_id"] == "value.v1"


def test_industrial_single_frame_yolox_position_gate_documents_are_valid() -> None:
    """验证 YOLOX 检测到工业规则链样例模板与应用可以通过当前合同校验。"""

    example_dir = (
        Path(__file__).resolve().parents[1] / "docs" / "examples" / "workflows"
    )
    template_path = (
        example_dir / "industrial_single_frame_yolox_position_gate.template.json"
    )
    application_path = (
        example_dir / "industrial_single_frame_yolox_position_gate.application.json"
    )
    template = WorkflowGraphTemplate.model_validate(
        json.loads(template_path.read_text(encoding="utf-8"))
    )
    application = FlowApplication.model_validate(
        json.loads(application_path.read_text(encoding="utf-8"))
    )

    registry = NodeCatalogRegistry()
    validate_workflow_graph_template(
        template=template,
        node_definitions=registry.get_workflow_node_definitions(),
    )
    validate_flow_application_bindings(template=template, application=application)

    assert [node.node_id for node in template.nodes] == [
        "request_image_path_input",
        "deployment_request_input",
        "load_image",
        "detect",
        "detections_to_regions",
        "filter_regions",
        "select_best_region",
        "create_roi",
        "inside_check",
        "offset_check",
        "presence_check",
        "metadata_object",
        "metrics_object",
        "process_decision",
        "alarm_condition",
        "save_result_json",
        "append_result_csv",
    ]
    assert (
        template.metadata["example_kind"]
        == "industrial-single-frame-yolox-position-gate"
    )
    assert template.metadata["focus"] == "single-frame-industrial-detection-rule-chain"
    assert template.metadata["uses_existing_deployment_instance"] is True
    assert template.metadata["dynamic_roi_input_binding"] == "request_roi"
    assert [template_input.input_id for template_input in template.template_inputs] == [
        "request_image_path",
        "deployment_request",
        "request_roi",
    ]
    assert template.template_inputs[0].payload_type_id == "value.v1"
    assert template.template_inputs[1].payload_type_id == "value.v1"
    assert template.template_inputs[2].payload_type_id == "value.v1"
    assert template.template_inputs[2].required is False
    assert application.template_ref.source_uri == (
        "docs/examples/workflows/industrial_single_frame_yolox_position_gate.template.json"
    )
    assert application.runtime_mode == "python-json-workflow"
    assert [binding.binding_id for binding in application.bindings] == [
        "request_image_path",
        "deployment_request",
        "request_roi",
        "model_detections",
        "model_regions",
        "inspection_result",
        "inspection_alarm",
        "decision_summary",
        "json_summary",
        "csv_summary",
    ]
    assert application.bindings[2].required is False
    assert application.bindings[3].config["payload_type_id"] == "detections.v1"
    assert application.bindings[4].config["payload_type_id"] == "regions.v1"


@pytest.mark.parametrize(
    (
        "example_name",
        "expected_example_kind",
        "expected_focus",
        "expected_node_ids",
    ),
    [
        (
            "industrial_single_frame_line_pair_measure_gate",
            "industrial-single-frame-line-pair-measure-gate",
            "single-frame-industrial-geometry-line-chain",
            [
                "request_image_path_input",
                "load_image",
                "otsu",
                "contour",
                "fit_lines",
                "lines_to_value",
                "extract_line_1_midpoint",
                "extract_line_2_midpoint",
                "measure_midpoint_distance",
                "measure_parallelism",
                "measure_slot_width",
                "slot_width_check",
                "parallelism_check",
                "metadata_object",
                "metrics_object",
                "process_decision",
                "alarm_condition",
                "save_result_json",
                "append_result_csv",
            ],
        ),
        (
            "industrial_single_frame_circle_concentricity_gate",
            "industrial-single-frame-circle-concentricity-gate",
            "single-frame-industrial-geometry-circle-chain",
            [
                "request_image_path_input",
                "load_image",
                "otsu",
                "contour",
                "filter_contours",
                "fit_circles",
                "measure_diameter",
                "measure_concentricity",
                "contours_to_regions",
                "circularity_check",
                "diameter_check",
                "concentricity_check",
                "metadata_object",
                "metrics_object",
                "process_decision",
                "alarm_condition",
                "save_result_json",
                "append_result_csv",
            ],
        ),
    ],
)
def test_industrial_single_frame_geometry_gate_documents_are_valid(
    example_name: str,
    expected_example_kind: str,
    expected_focus: str,
    expected_node_ids: list[str],
) -> None:
    """验证工业单帧几何量测样例模板与应用可以通过当前合同校验。"""

    example_dir = (
        Path(__file__).resolve().parents[1] / "docs" / "examples" / "workflows"
    )
    template_path = example_dir / f"{example_name}.template.json"
    application_path = example_dir / f"{example_name}.application.json"
    template = WorkflowGraphTemplate.model_validate(
        json.loads(template_path.read_text(encoding="utf-8"))
    )
    application = FlowApplication.model_validate(
        json.loads(application_path.read_text(encoding="utf-8"))
    )

    custom_nodes_root = Path(__file__).resolve().parents[1] / "custom_nodes"
    node_pack_loader = LocalNodePackLoader(custom_nodes_root)
    node_pack_loader.refresh()
    registry = NodeCatalogRegistry(node_pack_loader=node_pack_loader)
    validate_workflow_graph_template(
        template=template,
        node_definitions=registry.get_workflow_node_definitions(),
    )
    validate_flow_application_bindings(template=template, application=application)

    assert [node.node_id for node in template.nodes] == expected_node_ids
    assert template.metadata["example_kind"] == expected_example_kind
    assert template.metadata["focus"] == expected_focus
    assert [template_input.input_id for template_input in template.template_inputs] == [
        "request_image_path"
    ]
    assert template.template_inputs[0].payload_type_id == "value.v1"
    assert [template_output.output_id for template_output in template.template_outputs] == [
        "inspection_result",
        "inspection_alarm",
        "decision_summary",
        "json_summary",
        "csv_summary",
    ]
    assert (
        application.template_ref.source_uri
        == f"docs/examples/workflows/{example_name}.template.json"
    )
    assert application.runtime_mode == "python-json-workflow"
    assert [binding.binding_id for binding in application.bindings] == [
        "request_image_path",
        "inspection_result",
        "inspection_alarm",
        "decision_summary",
        "json_summary",
        "csv_summary",
    ]


def test_industrial_single_frame_segments_continuity_gate_documents_are_valid() -> None:
    """验证 segments 到工业规则链样例模板与应用可以通过当前合同校验。"""

    example_dir = (
        Path(__file__).resolve().parents[1] / "docs" / "examples" / "workflows"
    )
    template_path = (
        example_dir / "industrial_single_frame_segments_continuity_gate.template.json"
    )
    application_path = (
        example_dir
        / "industrial_single_frame_segments_continuity_gate.application.json"
    )
    template = WorkflowGraphTemplate.model_validate(
        json.loads(template_path.read_text(encoding="utf-8"))
    )
    application = FlowApplication.model_validate(
        json.loads(application_path.read_text(encoding="utf-8"))
    )

    registry = NodeCatalogRegistry()
    validate_workflow_graph_template(
        template=template,
        node_definitions=registry.get_workflow_node_definitions(),
    )
    validate_flow_application_bindings(template=template, application=application)

    assert [node.node_id for node in template.nodes] == [
        "request_image_path_input",
        "load_image",
        "segments_to_regions",
        "filter_regions",
        "area_ratio",
        "continuity_score",
        "gap_check",
        "presence_check",
        "area_ratio_check",
        "metadata_object",
        "metrics_object",
        "process_decision",
        "alarm_condition",
        "save_result_json",
        "append_result_csv",
    ]
    assert (
        template.metadata["example_kind"]
        == "industrial-single-frame-segments-continuity-gate"
    )
    assert (
        template.metadata["focus"] == "single-frame-industrial-segmentation-rule-chain"
    )
    assert [template_input.input_id for template_input in template.template_inputs] == [
        "request_image_path",
        "request_segments",
    ]
    assert template.template_inputs[0].payload_type_id == "value.v1"
    assert template.template_inputs[1].payload_type_id == "segments.v1"
    assert application.template_ref.source_uri == (
        "docs/examples/workflows/industrial_single_frame_segments_continuity_gate.template.json"
    )
    assert application.runtime_mode == "python-json-workflow"
    assert [binding.binding_id for binding in application.bindings] == [
        "request_image_path",
        "request_segments",
        "normalized_regions",
        "inspection_result",
        "inspection_alarm",
        "decision_summary",
        "json_summary",
        "csv_summary",
    ]
    assert application.bindings[1].config["payload_type_id"] == "segments.v1"
    assert application.bindings[2].config["payload_type_id"] == "regions.v1"


@pytest.mark.parametrize(
    (
        "example_name",
        "expected_example_kind",
        "expected_focus",
        "expected_node_ids",
        "expected_input_ids",
        "expected_binding_ids",
    ),
    [
        (
            "industrial_single_frame_regions_overlay_review",
            "industrial-single-frame-regions-overlay-review",
            "single-frame-industrial-regions-overlay-review",
            [
                "request_image_path_input",
                "load_image",
                "filter_regions",
                "create_roi",
                "draw_roi",
                "overlay_regions",
                "presence_check",
                "inside_check",
                "metadata_object",
                "metrics_object",
                "process_decision",
            ],
            ["request_image_path", "request_regions", "request_roi"],
            [
                "request_image_path",
                "request_regions",
                "request_roi",
                "filtered_regions",
                "effective_roi",
                "review_overlay_image",
                "inspection_result",
                "decision_summary",
            ],
        ),
        (
            "industrial_single_frame_segments_overlay_review",
            "industrial-single-frame-segments-overlay-review",
            "single-frame-industrial-segments-overlay-review",
            [
                "request_image_path_input",
                "load_image",
                "segments_to_regions",
                "filter_regions",
                "create_roi",
                "draw_roi",
                "overlay_regions",
                "presence_check",
                "coverage_check",
                "metadata_object",
                "metrics_object",
                "process_decision",
            ],
            ["request_image_path", "request_segments", "request_roi"],
            [
                "request_image_path",
                "request_segments",
                "request_roi",
                "normalized_regions",
                "effective_roi",
                "review_overlay_image",
                "inspection_result",
                "decision_summary",
            ],
        ),
    ],
)
def test_industrial_single_frame_overlay_review_documents_are_valid(
    example_name: str,
    expected_example_kind: str,
    expected_focus: str,
    expected_node_ids: list[str],
    expected_input_ids: list[str],
    expected_binding_ids: list[str],
) -> None:
    """验证工业单帧 overlay 复核样例模板与应用可以通过当前合同校验。"""

    example_dir = (
        Path(__file__).resolve().parents[1] / "docs" / "examples" / "workflows"
    )
    template_path = example_dir / f"{example_name}.template.json"
    application_path = example_dir / f"{example_name}.application.json"
    template = WorkflowGraphTemplate.model_validate(
        json.loads(template_path.read_text(encoding="utf-8"))
    )
    application = FlowApplication.model_validate(
        json.loads(application_path.read_text(encoding="utf-8"))
    )

    custom_nodes_root = Path(__file__).resolve().parents[1] / "custom_nodes"
    node_pack_loader = LocalNodePackLoader(custom_nodes_root)
    node_pack_loader.refresh()
    registry = NodeCatalogRegistry(node_pack_loader=node_pack_loader)
    validate_workflow_graph_template(
        template=template,
        node_definitions=registry.get_workflow_node_definitions(),
    )
    validate_flow_application_bindings(template=template, application=application)

    assert [node.node_id for node in template.nodes] == expected_node_ids
    assert template.metadata["example_kind"] == expected_example_kind
    assert template.metadata["focus"] == expected_focus
    assert template.metadata["dynamic_roi_input_binding"] == "request_roi"
    assert [
        template_input.input_id for template_input in template.template_inputs
    ] == expected_input_ids
    assert template.template_inputs[0].payload_type_id == "value.v1"
    assert template.template_inputs[2].payload_type_id == "value.v1"
    assert template.template_inputs[2].required is False
    assert (
        application.template_ref.source_uri
        == f"docs/examples/workflows/{example_name}.template.json"
    )
    assert application.runtime_mode == "python-json-workflow"
    assert [binding.binding_id for binding in application.bindings] == expected_binding_ids
    assert application.bindings[2].required is False
    assert application.bindings[2].metadata["payload_type_id"] == "value.v1"
    assert application.bindings[5].config["payload_type_id"] == "image-ref.v1"


@pytest.mark.parametrize(
    (
        "example_name",
        "expected_example_kind",
        "expected_focus",
        "expected_node_ids",
        "expected_binding_ids",
        "expected_has_detections_output",
    ),
    [
        (
            "industrial_single_frame_yoloe_text_overlay_review",
            "industrial-single-frame-yoloe-text-overlay-review",
            "single-frame-industrial-yoloe-overlay-review",
            [
                "request_image_path_input",
                "load_image",
                "detect",
                "filter_regions",
                "create_roi",
                "draw_roi",
                "overlay_regions",
                "presence_check",
                "inside_check",
                "metadata_object",
                "metrics_object",
                "process_decision",
            ],
            [
                "request_image_path",
                "request_prompts",
                "request_roi",
                "model_detections",
                "model_regions",
                "filtered_regions",
                "effective_roi",
                "review_overlay_image",
                "inspection_result",
                "decision_summary",
            ],
            True,
        ),
        (
            "industrial_single_frame_sam3_semantic_overlay_review",
            "industrial-single-frame-sam3-semantic-overlay-review",
            "single-frame-industrial-sam3-overlay-review",
            [
                "request_image_path_input",
                "load_image",
                "segment",
                "filter_regions",
                "create_roi",
                "draw_roi",
                "overlay_regions",
                "presence_check",
                "coverage_check",
                "metadata_object",
                "metrics_object",
                "process_decision",
            ],
            [
                "request_image_path",
                "request_prompts",
                "request_roi",
                "model_regions",
                "filtered_regions",
                "effective_roi",
                "review_overlay_image",
                "inspection_result",
                "decision_summary",
            ],
            False,
        ),
    ],
)
def test_industrial_single_frame_native_model_overlay_review_documents_are_valid(
    example_name: str,
    expected_example_kind: str,
    expected_focus: str,
    expected_node_ids: list[str],
    expected_binding_ids: list[str],
    expected_has_detections_output: bool,
) -> None:
    """验证 YOLOE / SAM3 单帧直连 overlay 复核样例模板与应用可以通过当前合同校验。"""

    example_dir = (
        Path(__file__).resolve().parents[1] / "docs" / "examples" / "workflows"
    )
    template_path = example_dir / f"{example_name}.template.json"
    application_path = example_dir / f"{example_name}.application.json"
    template = WorkflowGraphTemplate.model_validate(
        json.loads(template_path.read_text(encoding="utf-8"))
    )
    application = FlowApplication.model_validate(
        json.loads(application_path.read_text(encoding="utf-8"))
    )

    custom_nodes_root = Path(__file__).resolve().parents[1] / "custom_nodes"
    node_pack_loader = LocalNodePackLoader(custom_nodes_root)
    node_pack_loader.refresh()
    registry = NodeCatalogRegistry(node_pack_loader=node_pack_loader)
    validate_workflow_graph_template(
        template=template,
        node_definitions=registry.get_workflow_node_definitions(),
    )
    validate_flow_application_bindings(template=template, application=application)

    assert [node.node_id for node in template.nodes] == expected_node_ids
    assert template.metadata["example_kind"] == expected_example_kind
    assert template.metadata["focus"] == expected_focus
    assert template.metadata["dynamic_roi_input_binding"] == "request_roi"
    assert [template_input.input_id for template_input in template.template_inputs] == [
        "request_image_path",
        "request_prompts",
        "request_roi",
    ]
    assert template.template_inputs[0].payload_type_id == "value.v1"
    assert template.template_inputs[1].payload_type_id == "text-prompts.v1"
    assert template.template_inputs[2].payload_type_id == "value.v1"
    assert template.template_inputs[2].required is False
    assert (
        application.template_ref.source_uri
        == f"docs/examples/workflows/{example_name}.template.json"
    )
    assert application.runtime_mode == "python-json-workflow"
    assert [binding.binding_id for binding in application.bindings] == expected_binding_ids
    assert application.bindings[1].metadata["payload_type_id"] == "text-prompts.v1"
    assert application.bindings[2].required is False
    if expected_has_detections_output:
        assert application.bindings[3].config["payload_type_id"] == "detections.v1"
        assert application.bindings[7].config["payload_type_id"] == "image-ref.v1"
    else:
        assert application.bindings[3].config["payload_type_id"] == "regions.v1"
        assert application.bindings[6].config["payload_type_id"] == "image-ref.v1"


@pytest.mark.parametrize(
    (
        "example_name",
        "expected_example_kind",
        "expected_focus",
        "expected_node_ids",
        "expected_input_ids",
        "expected_input_payload_types",
        "expected_binding_ids",
        "expected_optional_binding_index",
        "expected_overlay_binding_index",
        "expected_detections_binding_index",
    ),
    [
        (
            "industrial_single_frame_yoloe_visual_overlay_review",
            "industrial-single-frame-yoloe-visual-overlay-review",
            "single-frame-industrial-yoloe-visual-overlay-review",
            [
                "request_image_path_input",
                "request_prompt_image_path_input",
                "load_image",
                "load_prompt_image",
                "detect",
                "filter_regions",
                "create_roi",
                "draw_roi",
                "overlay_regions",
                "presence_check",
                "inside_check",
                "metadata_object",
                "metrics_object",
                "process_decision",
            ],
            [
                "request_image_path",
                "request_prompt_image_path",
                "request_prompts",
                "request_roi",
            ],
            ["value.v1", "value.v1", "prompt-regions.v1", "value.v1"],
            [
                "request_image_path",
                "request_prompt_image_path",
                "request_prompts",
                "request_roi",
                "model_detections",
                "model_regions",
                "filtered_regions",
                "effective_roi",
                "review_overlay_image",
                "inspection_result",
                "decision_summary",
            ],
            3,
            8,
            4,
        ),
        (
            "industrial_single_frame_sam3_interactive_overlay_review",
            "industrial-single-frame-sam3-interactive-overlay-review",
            "single-frame-industrial-sam3-interactive-overlay-review",
            [
                "request_image_path_input",
                "load_image",
                "segment",
                "filter_regions",
                "create_roi",
                "draw_roi",
                "overlay_regions",
                "presence_check",
                "coverage_check",
                "metadata_object",
                "metrics_object",
                "process_decision",
            ],
            [
                "request_image_path",
                "request_prompts",
                "request_roi",
            ],
            ["value.v1", "prompt-regions.v1", "value.v1"],
            [
                "request_image_path",
                "request_prompts",
                "request_roi",
                "model_regions",
                "filtered_regions",
                "effective_roi",
                "review_overlay_image",
                "inspection_result",
                "decision_summary",
            ],
            2,
            6,
            None,
        ),
    ],
)
def test_industrial_single_frame_prompt_region_native_model_overlay_review_documents_are_valid(
    example_name: str,
    expected_example_kind: str,
    expected_focus: str,
    expected_node_ids: list[str],
    expected_input_ids: list[str],
    expected_input_payload_types: list[str],
    expected_binding_ids: list[str],
    expected_optional_binding_index: int,
    expected_overlay_binding_index: int,
    expected_detections_binding_index: int | None,
) -> None:
    """验证 prompt-regions 直连的 YOLOE / SAM3 overlay 复核样例模板与应用可以通过当前合同校验。"""

    example_dir = (
        Path(__file__).resolve().parents[1] / "docs" / "examples" / "workflows"
    )
    template_path = example_dir / f"{example_name}.template.json"
    application_path = example_dir / f"{example_name}.application.json"
    template = WorkflowGraphTemplate.model_validate(
        json.loads(template_path.read_text(encoding="utf-8"))
    )
    application = FlowApplication.model_validate(
        json.loads(application_path.read_text(encoding="utf-8"))
    )

    custom_nodes_root = Path(__file__).resolve().parents[1] / "custom_nodes"
    node_pack_loader = LocalNodePackLoader(custom_nodes_root)
    node_pack_loader.refresh()
    registry = NodeCatalogRegistry(node_pack_loader=node_pack_loader)
    validate_workflow_graph_template(
        template=template,
        node_definitions=registry.get_workflow_node_definitions(),
    )
    validate_flow_application_bindings(template=template, application=application)

    assert [node.node_id for node in template.nodes] == expected_node_ids
    assert template.metadata["example_kind"] == expected_example_kind
    assert template.metadata["focus"] == expected_focus
    assert template.metadata["dynamic_roi_input_binding"] == "request_roi"
    assert [template_input.input_id for template_input in template.template_inputs] == expected_input_ids
    assert [
        template_input.payload_type_id for template_input in template.template_inputs
    ] == expected_input_payload_types
    assert template.template_inputs[-1].required is False
    assert (
        application.template_ref.source_uri
        == f"docs/examples/workflows/{example_name}.template.json"
    )
    assert application.runtime_mode == "python-json-workflow"
    assert [binding.binding_id for binding in application.bindings] == expected_binding_ids
    assert application.bindings[expected_optional_binding_index].required is False
    assert application.bindings[expected_optional_binding_index].metadata["payload_type_id"] == "value.v1"
    assert application.bindings[expected_overlay_binding_index].config["payload_type_id"] == "image-ref.v1"
    if expected_detections_binding_index is not None:
        assert (
            application.bindings[expected_detections_binding_index].config["payload_type_id"]
            == "detections.v1"
        )


def test_industrial_local_directory_batch_input_documents_are_valid() -> None:
    """验证工业本地目录批量输入样例模板与应用可以通过当前合同校验。"""

    example_dir = (
        Path(__file__).resolve().parents[1] / "docs" / "examples" / "workflows"
    )
    template_path = example_dir / "industrial_local_directory_batch_input.template.json"
    application_path = (
        example_dir / "industrial_local_directory_batch_input.application.json"
    )
    template = WorkflowGraphTemplate.model_validate(
        json.loads(template_path.read_text(encoding="utf-8"))
    )
    application = FlowApplication.model_validate(
        json.loads(application_path.read_text(encoding="utf-8"))
    )

    registry = NodeCatalogRegistry()
    validate_workflow_graph_template(
        template=template,
        node_definitions=registry.get_workflow_node_definitions(),
    )
    validate_flow_application_bindings(template=template, application=application)

    assert [node.node_id for node in template.nodes] == [
        "request_directory_path_input",
        "scan_directory",
        "batch_window",
        "load_images",
        "summary_object",
    ]
    assert template.metadata["example_kind"] == "industrial-local-directory-batch-input"
    assert template.metadata["focus"] == "local-batch-industrial-input-prep"
    assert (
        template.metadata["dynamic_batch_start_binding"] == "request_batch_start_index"
    )
    assert template.metadata["dynamic_batch_size_binding"] == "request_batch_size"
    assert template.metadata["dynamic_batch_cursor_binding"] == "request_batch_cursor"
    assert [template_input.input_id for template_input in template.template_inputs] == [
        "request_directory_path",
        "request_batch_start_index",
        "request_batch_size",
        "request_batch_cursor",
    ]
    assert template.template_inputs[0].payload_type_id == "value.v1"
    assert template.template_inputs[1].payload_type_id == "value.v1"
    assert template.template_inputs[1].required is False
    assert template.template_inputs[2].payload_type_id == "value.v1"
    assert template.template_inputs[2].required is False
    assert template.template_inputs[3].payload_type_id == "value.v1"
    assert template.template_inputs[3].required is False
    assert application.template_ref.source_uri == (
        "docs/examples/workflows/industrial_local_directory_batch_input.template.json"
    )
    assert application.runtime_mode == "python-json-workflow"
    assert [binding.binding_id for binding in application.bindings] == [
        "request_directory_path",
        "request_batch_start_index",
        "request_batch_size",
        "request_batch_cursor",
        "batch_files",
        "batch_images",
        "scan_summary",
        "batch_cursor",
        "batch_summary",
    ]
    assert application.bindings[1].required is False
    assert application.bindings[2].required is False
    assert application.bindings[3].required is False
    assert application.bindings[5].config["payload_type_id"] == "image-refs.v1"


def test_industrial_local_directory_polling_cursor_guard_documents_are_valid() -> None:
    """验证工业目录轮询 cursor 守护样例模板与应用可以通过当前合同校验。"""

    example_dir = (
        Path(__file__).resolve().parents[1] / "docs" / "examples" / "workflows"
    )
    template_path = (
        example_dir / "industrial_local_directory_polling_cursor_guard.template.json"
    )
    application_path = (
        example_dir
        / "industrial_local_directory_polling_cursor_guard.application.json"
    )
    template = WorkflowGraphTemplate.model_validate(
        json.loads(template_path.read_text(encoding="utf-8"))
    )
    application = FlowApplication.model_validate(
        json.loads(application_path.read_text(encoding="utf-8"))
    )

    registry = NodeCatalogRegistry()
    validate_workflow_graph_template(
        template=template,
        node_definitions=registry.get_workflow_node_definitions(),
    )
    validate_flow_application_bindings(template=template, application=application)

    assert [node.node_id for node in template.nodes] == [
        "request_directory_path_input",
        "load_cursor_state",
        "scan_directory",
        "poll_window",
        "batch_archive_object",
        "save_cursor_state",
        "save_batch_archive",
    ]
    assert template.nodes[2].parameters["sort_by"] == "modified_time"
    assert template.nodes[2].parameters["descending"] is False
    assert template.metadata["example_kind"] == (
        "industrial-local-directory-polling-cursor-guard"
    )
    assert template.metadata["focus"] == "local-directory-polling-guard"
    assert template.metadata["uses_persisted_local_cursor"] is True
    assert template.metadata["dynamic_batch_size_binding"] == "request_batch_size"
    assert [template_input.input_id for template_input in template.template_inputs] == [
        "request_directory_path",
        "request_batch_size",
    ]
    assert template.template_inputs[0].payload_type_id == "value.v1"
    assert template.template_inputs[1].payload_type_id == "value.v1"
    assert template.template_inputs[1].required is False
    assert application.template_ref.source_uri == (
        "docs/examples/workflows/industrial_local_directory_polling_cursor_guard.template.json"
    )
    assert application.runtime_mode == "python-json-workflow"
    assert [binding.binding_id for binding in application.bindings] == [
        "request_directory_path",
        "request_batch_size",
        "has_work",
        "batch_files",
        "scan_summary",
        "poll_summary",
        "batch_cursor",
        "cursor_state",
        "cursor_load_summary",
        "cursor_save_summary",
        "batch_archive",
        "archive_summary",
    ]
    assert application.bindings[1].required is False
    assert application.bindings[2].config["payload_type_id"] == "boolean.v1"


def test_industrial_local_directory_batch_yolox_position_gate_documents_are_valid() -> (
    None
):
    """验证工业目录批处理检测闭环样例模板与应用可以通过当前合同校验。"""

    example_dir = (
        Path(__file__).resolve().parents[1] / "docs" / "examples" / "workflows"
    )
    template_path = (
        example_dir / "industrial_local_directory_batch_yolox_position_gate.template.json"
    )
    application_path = (
        example_dir
        / "industrial_local_directory_batch_yolox_position_gate.application.json"
    )
    template = WorkflowGraphTemplate.model_validate(
        json.loads(template_path.read_text(encoding="utf-8"))
    )
    application = FlowApplication.model_validate(
        json.loads(application_path.read_text(encoding="utf-8"))
    )

    registry = NodeCatalogRegistry()
    validate_workflow_graph_template(
        template=template,
        node_definitions=registry.get_workflow_node_definitions(),
    )
    validate_flow_application_bindings(template=template, application=application)

    assert [node.node_id for node in template.nodes] == [
        "request_directory_path_input",
        "deployment_request_input",
        "scan_directory",
        "batch_window",
        "create_roi",
        "iterate_batch",
        "get_current_file_record",
        "get_current_file_index",
        "extract_current_file_path",
        "load_image",
        "detect",
        "detections_to_regions",
        "filter_regions",
        "select_best_region",
        "inside_check",
        "offset_check",
        "presence_check",
        "metadata_object",
        "metrics_object",
        "process_decision",
        "append_result_csv",
        "batch_summary_object",
        "save_batch_json",
    ]
    assert (
        template.metadata["example_kind"]
        == "industrial-local-directory-batch-yolox-position-gate"
    )
    assert template.metadata["focus"] == "local-batch-industrial-detection-rule-chain"
    assert template.metadata["uses_existing_deployment_instance"] is True
    assert (
        template.metadata["dynamic_batch_start_binding"] == "request_batch_start_index"
    )
    assert template.metadata["dynamic_batch_size_binding"] == "request_batch_size"
    assert template.metadata["dynamic_batch_cursor_binding"] == "request_batch_cursor"
    assert template.metadata["dynamic_roi_input_binding"] == "request_roi"
    assert [template_input.input_id for template_input in template.template_inputs] == [
        "request_directory_path",
        "request_batch_start_index",
        "request_batch_size",
        "request_batch_cursor",
        "deployment_request",
        "request_roi",
    ]
    assert template.template_inputs[0].payload_type_id == "value.v1"
    assert template.template_inputs[1].payload_type_id == "value.v1"
    assert template.template_inputs[1].required is False
    assert template.template_inputs[2].payload_type_id == "value.v1"
    assert template.template_inputs[2].required is False
    assert template.template_inputs[3].payload_type_id == "value.v1"
    assert template.template_inputs[3].required is False
    assert template.template_inputs[4].payload_type_id == "value.v1"
    assert template.template_inputs[5].payload_type_id == "value.v1"
    assert template.template_inputs[5].required is False
    assert application.template_ref.source_uri == (
        "docs/examples/workflows/industrial_local_directory_batch_yolox_position_gate.template.json"
    )
    assert application.runtime_mode == "python-json-workflow"
    assert [binding.binding_id for binding in application.bindings] == [
        "request_directory_path",
        "request_batch_start_index",
        "request_batch_size",
        "request_batch_cursor",
        "deployment_request",
        "request_roi",
        "batch_files",
        "inspection_results",
        "inspection_result_count",
        "terminated_early",
        "termination_reason",
        "scan_summary",
        "window_summary",
        "batch_cursor",
        "batch_summary",
        "json_summary",
    ]
    assert application.bindings[1].required is False
    assert application.bindings[2].required is False
    assert application.bindings[3].required is False
    assert application.bindings[5].required is False
    assert application.bindings[9].config["payload_type_id"] == "boolean.v1"


def test_industrial_local_directory_watch_yolox_position_gate_documents_are_valid() -> (
    None
):
    """验证工业目录监听触发检测闭环样例模板与应用可以通过当前合同校验。"""

    example_dir = (
        Path(__file__).resolve().parents[1] / "docs" / "examples" / "workflows"
    )
    template_path = (
        example_dir / "industrial_local_directory_watch_yolox_position_gate.template.json"
    )
    application_path = (
        example_dir
        / "industrial_local_directory_watch_yolox_position_gate.application.json"
    )
    template = WorkflowGraphTemplate.model_validate(
        json.loads(template_path.read_text(encoding="utf-8"))
    )
    application = FlowApplication.model_validate(
        json.loads(application_path.read_text(encoding="utf-8"))
    )

    registry = NodeCatalogRegistry()
    validate_workflow_graph_template(
        template=template,
        node_definitions=registry.get_workflow_node_definitions(),
    )
    validate_flow_application_bindings(template=template, application=application)

    assert [node.node_id for node in template.nodes] == [
        "wrap_trigger_payload",
        "wrap_trigger_event",
        "deployment_request_input",
        "extract_batch_files",
        "extract_batch_id",
        "extract_scan_summary",
        "extract_directory_path",
        "create_roi",
        "iterate_batch",
        "get_current_file_record",
        "get_current_file_index",
        "extract_current_file_path",
        "load_image",
        "detect",
        "detections_to_regions",
        "filter_regions",
        "select_best_region",
        "inside_check",
        "offset_check",
        "presence_check",
        "item_metadata_object",
        "item_metrics_object",
        "process_decision",
        "append_result_csv",
        "batch_metadata_object",
        "batch_record",
        "batch_result_summary",
        "save_batch_json",
        "callback_result",
    ]
    assert (
        template.metadata["example_kind"]
        == "industrial-local-directory-watch-yolox-position-gate"
    )
    assert (
        template.metadata["focus"]
        == "directory-watch-trigger-industrial-detection-rule-chain"
    )
    assert template.metadata["trigger_source_kind"] == "directory-watch"
    assert template.metadata["uses_existing_deployment_instance"] is True
    assert template.metadata["dynamic_roi_input_binding"] == "request_roi"
    assert template.metadata["callback_url_edit_required"] is True
    assert [template_input.input_id for template_input in template.template_inputs] == [
        "request_trigger_payload",
        "request_trigger_event",
        "deployment_request",
        "request_roi",
    ]
    assert [template_input.payload_type_id for template_input in template.template_inputs] == [
        "response-body.v1",
        "response-body.v1",
        "value.v1",
        "value.v1",
    ]
    assert template.template_inputs[3].required is False
    assert [template_output.output_id for template_output in template.template_outputs] == [
        "batch_files",
        "inspection_results",
        "inspection_result_count",
        "terminated_early",
        "termination_reason",
        "batch_record",
        "batch_result_summary",
        "json_summary",
        "callback_response",
    ]
    assert application.template_ref.source_uri == (
        "docs/examples/workflows/industrial_local_directory_watch_yolox_position_gate.template.json"
    )
    assert application.runtime_mode == "python-json-workflow"
    assert [binding.binding_id for binding in application.bindings] == [
        "request_trigger_payload",
        "request_trigger_event",
        "deployment_request",
        "request_roi",
        "batch_files",
        "inspection_results",
        "inspection_result_count",
        "terminated_early",
        "termination_reason",
        "batch_record",
        "batch_result_summary",
        "json_summary",
        "callback_response",
    ]
    assert application.bindings[0].metadata["source_path"] == "payload"
    assert application.bindings[1].metadata["source_path"] == "event"
    assert application.bindings[3].required is False
    assert application.bindings[7].config["payload_type_id"] == "boolean.v1"


def test_industrial_local_directory_batch_segments_continuity_gate_documents_are_valid() -> (
    None
):
    """验证工业目录批处理分割闭环样例模板与应用可以通过当前合同校验。"""

    example_dir = (
        Path(__file__).resolve().parents[1] / "docs" / "examples" / "workflows"
    )
    template_path = (
        example_dir
        / "industrial_local_directory_batch_segments_continuity_gate.template.json"
    )
    application_path = (
        example_dir
        / "industrial_local_directory_batch_segments_continuity_gate.application.json"
    )
    template = WorkflowGraphTemplate.model_validate(
        json.loads(template_path.read_text(encoding="utf-8"))
    )
    application = FlowApplication.model_validate(
        json.loads(application_path.read_text(encoding="utf-8"))
    )

    registry = NodeCatalogRegistry()
    validate_workflow_graph_template(
        template=template,
        node_definitions=registry.get_workflow_node_definitions(),
    )
    validate_flow_application_bindings(template=template, application=application)

    assert [node.node_id for node in template.nodes] == [
        "request_directory_path_input",
        "scan_directory",
        "batch_window",
        "iterate_batch",
        "get_current_file_record",
        "get_current_file_index",
        "extract_current_file_path",
        "load_image",
        "get_current_segments_value",
        "value_to_segments",
        "segments_to_regions",
        "filter_regions",
        "area_ratio",
        "continuity_score",
        "gap_check",
        "presence_check",
        "area_ratio_check",
        "metadata_object",
        "metrics_object",
        "process_decision",
        "append_result_csv",
        "batch_summary_object",
        "save_batch_json",
    ]
    assert (
        template.metadata["example_kind"]
        == "industrial-local-directory-batch-segments-continuity-gate"
    )
    assert template.metadata["focus"] == "local-batch-industrial-segmentation-rule-chain"
    assert (
        template.metadata["dynamic_batch_start_binding"] == "request_batch_start_index"
    )
    assert template.metadata["dynamic_batch_size_binding"] == "request_batch_size"
    assert template.metadata["dynamic_batch_cursor_binding"] == "request_batch_cursor"
    assert template.metadata["batch_segments_items_binding"] == "request_segments_items"
    assert [template_input.input_id for template_input in template.template_inputs] == [
        "request_directory_path",
        "request_batch_start_index",
        "request_batch_size",
        "request_batch_cursor",
        "request_segments_items",
    ]
    assert [template_input.payload_type_id for template_input in template.template_inputs] == [
        "value.v1",
        "value.v1",
        "value.v1",
        "value.v1",
        "value.v1",
    ]
    assert template.template_inputs[1].required is False
    assert template.template_inputs[2].required is False
    assert template.template_inputs[3].required is False
    assert application.template_ref.source_uri == (
        "docs/examples/workflows/industrial_local_directory_batch_segments_continuity_gate.template.json"
    )
    assert application.runtime_mode == "python-json-workflow"
    assert [binding.binding_id for binding in application.bindings] == [
        "request_directory_path",
        "request_batch_start_index",
        "request_batch_size",
        "request_batch_cursor",
        "request_segments_items",
        "batch_files",
        "inspection_results",
        "inspection_result_count",
        "terminated_early",
        "termination_reason",
        "scan_summary",
        "window_summary",
        "batch_cursor",
        "batch_summary",
        "json_summary",
    ]
    assert application.bindings[1].required is False
    assert application.bindings[2].required is False
    assert application.bindings[3].required is False
    assert application.bindings[8].config["payload_type_id"] == "boolean.v1"


def test_industrial_local_directory_batch_regions_continuity_gate_documents_are_valid() -> (
    None
):
    """验证工业目录批处理 regions 闭环样例模板与应用可以通过当前合同校验。"""

    example_dir = (
        Path(__file__).resolve().parents[1] / "docs" / "examples" / "workflows"
    )
    template_path = (
        example_dir
        / "industrial_local_directory_batch_regions_continuity_gate.template.json"
    )
    application_path = (
        example_dir
        / "industrial_local_directory_batch_regions_continuity_gate.application.json"
    )
    template = WorkflowGraphTemplate.model_validate(
        json.loads(template_path.read_text(encoding="utf-8"))
    )
    application = FlowApplication.model_validate(
        json.loads(application_path.read_text(encoding="utf-8"))
    )

    registry = NodeCatalogRegistry()
    validate_workflow_graph_template(
        template=template,
        node_definitions=registry.get_workflow_node_definitions(),
    )
    validate_flow_application_bindings(template=template, application=application)

    assert [node.node_id for node in template.nodes] == [
        "request_directory_path_input",
        "scan_directory",
        "batch_window",
        "iterate_batch",
        "get_current_file_record",
        "get_current_file_index",
        "extract_current_file_path",
        "load_image",
        "get_current_regions_value",
        "value_to_regions",
        "filter_regions",
        "area_ratio",
        "continuity_score",
        "gap_check",
        "presence_check",
        "area_ratio_check",
        "metadata_object",
        "metrics_object",
        "process_decision",
        "append_result_csv",
        "batch_summary_object",
        "save_batch_json",
    ]
    assert (
        template.metadata["example_kind"]
        == "industrial-local-directory-batch-regions-continuity-gate"
    )
    assert template.metadata["focus"] == "local-batch-industrial-regions-rule-chain"
    assert (
        template.metadata["dynamic_batch_start_binding"] == "request_batch_start_index"
    )
    assert template.metadata["dynamic_batch_size_binding"] == "request_batch_size"
    assert template.metadata["dynamic_batch_cursor_binding"] == "request_batch_cursor"
    assert template.metadata["batch_regions_items_binding"] == "request_regions_items"
    assert [template_input.input_id for template_input in template.template_inputs] == [
        "request_directory_path",
        "request_batch_start_index",
        "request_batch_size",
        "request_batch_cursor",
        "request_regions_items",
    ]
    assert [template_input.payload_type_id for template_input in template.template_inputs] == [
        "value.v1",
        "value.v1",
        "value.v1",
        "value.v1",
        "value.v1",
    ]
    assert template.template_inputs[1].required is False
    assert template.template_inputs[2].required is False
    assert template.template_inputs[3].required is False
    assert application.template_ref.source_uri == (
        "docs/examples/workflows/industrial_local_directory_batch_regions_continuity_gate.template.json"
    )
    assert application.runtime_mode == "python-json-workflow"
    assert [binding.binding_id for binding in application.bindings] == [
        "request_directory_path",
        "request_batch_start_index",
        "request_batch_size",
        "request_batch_cursor",
        "request_regions_items",
        "batch_files",
        "inspection_results",
        "inspection_result_count",
        "terminated_early",
        "termination_reason",
        "scan_summary",
        "window_summary",
        "batch_cursor",
        "batch_summary",
        "json_summary",
    ]
    assert application.bindings[1].required is False
    assert application.bindings[2].required is False
    assert application.bindings[3].required is False
    assert application.bindings[8].config["payload_type_id"] == "boolean.v1"


def test_opencv_process_save_image_example_documents_are_valid() -> None:
    """验证 OpenCV 处理并保存图片示例模板与应用可以通过当前合同校验。"""

    example_dir = (
        Path(__file__).resolve().parents[1] / "docs" / "examples" / "workflows"
    )
    template_path = example_dir / "opencv_process_save_image.template.json"
    application_path = example_dir / "opencv_process_save_image.application.json"
    template = WorkflowGraphTemplate.model_validate(
        json.loads(template_path.read_text(encoding="utf-8"))
    )
    application = FlowApplication.model_validate(
        json.loads(application_path.read_text(encoding="utf-8"))
    )

    custom_nodes_root = Path(__file__).resolve().parents[1] / "custom_nodes"
    node_pack_loader = LocalNodePackLoader(custom_nodes_root)
    node_pack_loader.refresh()
    registry = NodeCatalogRegistry(node_pack_loader=node_pack_loader)
    validate_workflow_graph_template(
        template=template,
        node_definitions=registry.get_workflow_node_definitions(),
    )
    validate_flow_application_bindings(template=template, application=application)

    assert [node.node_id for node in template.nodes] == [
        "decode_request_image",
        "blur_image",
        "threshold_image",
        "edge_image",
        "save_image",
        "preview_image",
        "response",
    ]
    assert template.metadata["example_kind"] == "opencv-process-save-image"
    assert template.metadata["node_groups"]["opencv_process"] == [
        "blur_image",
        "threshold_image",
        "edge_image",
    ]
    assert (
        application.template_ref.source_uri
        == "docs/examples/workflows/opencv_process_save_image.template.json"
    )
    assert application.runtime_mode == "python-json-workflow"
    assert [binding.binding_id for binding in application.bindings] == [
        "request_image",
        "http_response",
    ]


def test_yolox_deployment_infer_opencv_health_example_documents_are_valid() -> None:
    """验证 deployment infer + opencv + health 示例模板与应用可以通过当前合同校验。"""

    example_dir = (
        Path(__file__).resolve().parents[1] / "docs" / "examples" / "workflows"
    )
    template_path = example_dir / "yolox_deployment_infer_opencv_health.template.json"
    application_path = (
        example_dir / "yolox_deployment_infer_opencv_health.application.json"
    )
    template = WorkflowGraphTemplate.model_validate(
        json.loads(template_path.read_text(encoding="utf-8"))
    )
    application = FlowApplication.model_validate(
        json.loads(application_path.read_text(encoding="utf-8"))
    )

    custom_nodes_root = Path(__file__).resolve().parents[1] / "custom_nodes"
    node_pack_loader = LocalNodePackLoader(custom_nodes_root)
    node_pack_loader.refresh()
    registry = NodeCatalogRegistry(node_pack_loader=node_pack_loader)
    validate_workflow_graph_template(
        template=template,
        node_definitions=registry.get_workflow_node_definitions(),
    )
    validate_flow_application_bindings(template=template, application=application)

    assert [node.node_id for node in template.nodes[:5]] == [
        "decode_request_image",
        "deployment_request_input",
        "health",
        "extract_deployment_instance_id",
        "detect",
    ]
    assert template.metadata["example_kind"] == "deployment-infer-opencv-health"
    assert template.metadata["deployment_instance_id_binding"] == "deployment_request"
    assert template.metadata["node_groups"]["input"] == [
        "decode_request_image",
        "deployment_request_input",
    ]
    assert template.metadata["node_groups"]["deployment"] == ["health", "detect"]
    assert application.template_ref.source_uri == (
        "docs/examples/workflows/yolox_deployment_infer_opencv_health.template.json"
    )
    assert application.runtime_mode == "python-json-workflow"
    assert [binding.binding_id for binding in application.bindings] == [
        "request_image",
        "deployment_request",
        "http_response",
    ]


@pytest.mark.parametrize(
    (
        "example_name",
        "expected_example_kind",
        "expected_binding_ids",
        "expected_input_nodes",
    ),
    [
        (
            "yolox_deployment_infer_opencv_health_zeromq",
            "deployment-infer-opencv-health-zeromq",
            [
                "request_image_base64",
                "request_image_ref",
                "deployment_request",
                "http_response",
            ],
            [
                "encode_request_image_ref",
                "resolve_request_image",
                "decode_request_image",
                "deployment_request_input",
            ],
        ),
        (
            "opencv_process_save_image_zeromq",
            "opencv-process-save-image-zeromq",
            ["request_image_base64", "request_image_ref", "http_response"],
            [
                "encode_request_image_ref",
                "resolve_request_image",
                "decode_request_image",
            ],
        ),
    ],
)
def test_zeromq_image_ref_example_documents_are_valid(
    example_name: str,
    expected_example_kind: str,
    expected_binding_ids: list[str],
    expected_input_nodes: list[str],
) -> None:
    """验证 ZeroMQ image-ref 示例模板与应用可以通过当前合同校验。"""

    example_dir = (
        Path(__file__).resolve().parents[1] / "docs" / "examples" / "workflows"
    )
    template_path = example_dir / f"{example_name}.template.json"
    application_path = example_dir / f"{example_name}.application.json"
    template = WorkflowGraphTemplate.model_validate(
        json.loads(template_path.read_text(encoding="utf-8"))
    )
    application = FlowApplication.model_validate(
        json.loads(application_path.read_text(encoding="utf-8"))
    )

    custom_nodes_root = Path(__file__).resolve().parents[1] / "custom_nodes"
    node_pack_loader = LocalNodePackLoader(custom_nodes_root)
    node_pack_loader.refresh()
    registry = NodeCatalogRegistry(node_pack_loader=node_pack_loader)
    validate_workflow_graph_template(
        template=template,
        node_definitions=registry.get_workflow_node_definitions(),
    )
    validate_flow_application_bindings(template=template, application=application)

    assert [node.node_type_id for node in template.nodes[:3]] == [
        "core.io.image-base64-encode",
        "core.logic.image-base64-coalesce",
        "core.io.image-base64-decode",
    ]
    assert template.template_inputs[0].input_id == "request_image_base64"
    assert template.template_inputs[0].payload_type_id == "image-base64.v1"
    assert template.template_inputs[0].required is False
    assert template.template_inputs[1].input_id == "request_image_ref"
    assert template.template_inputs[1].payload_type_id == "image-ref.v1"
    assert template.template_inputs[1].required is False
    assert template.metadata["example_kind"] == expected_example_kind
    assert template.metadata["trigger_source_input"] == "zeromq"
    assert template.metadata["node_groups"]["input"] == expected_input_nodes
    assert (
        application.template_ref.source_uri
        == f"docs/examples/workflows/{example_name}.template.json"
    )
    assert application.runtime_mode == "python-json-workflow"
    assert application.bindings[0].binding_kind == "api-request"
    assert application.bindings[0].required is False
    assert application.bindings[0].metadata["payload_type_id"] == "image-base64.v1"
    assert application.bindings[1].binding_kind == "trigger-source-input"
    assert application.bindings[1].required is False
    assert application.bindings[1].metadata["payload_type_id"] == "image-ref.v1"
    assert [
        binding.binding_id for binding in application.bindings
    ] == expected_binding_ids


def test_yolox_deployment_qr_crop_remap_example_documents_are_valid() -> None:
    """验证 deployment qr crop remap 示例模板与应用可以通过当前合同校验。"""

    example_dir = (
        Path(__file__).resolve().parents[1] / "docs" / "examples" / "workflows"
    )
    template_path = example_dir / "yolox_deployment_qr_crop_remap.template.json"
    application_path = example_dir / "yolox_deployment_qr_crop_remap.application.json"
    template = WorkflowGraphTemplate.model_validate(
        json.loads(template_path.read_text(encoding="utf-8"))
    )
    application = FlowApplication.model_validate(
        json.loads(application_path.read_text(encoding="utf-8"))
    )

    custom_nodes_root = Path(__file__).resolve().parents[1] / "custom_nodes"
    node_pack_loader = LocalNodePackLoader(custom_nodes_root)
    node_pack_loader.refresh()
    registry = NodeCatalogRegistry(node_pack_loader=node_pack_loader)
    validate_workflow_graph_template(
        template=template,
        node_definitions=registry.get_workflow_node_definitions(),
    )
    validate_flow_application_bindings(template=template, application=application)

    assert [node.node_id for node in template.nodes[:5]] == [
        "decode_request_image",
        "deployment_request_input",
        "detect",
        "export_crops",
        "decode_qr_crops",
    ]
    assert template.metadata["example_kind"] == "deployment-qr-crop-remap"
    assert template.metadata["deployment_instance_id_binding"] == "deployment_request"
    assert template.metadata["node_groups"]["input"] == [
        "decode_request_image",
        "deployment_request_input",
    ]
    assert template.metadata["node_groups"]["barcode"] == [
        "decode_qr_crops",
        "draw_results",
        "summary",
    ]
    assert application.template_ref.source_uri == (
        "docs/examples/workflows/yolox_deployment_qr_crop_remap.template.json"
    )
    assert application.runtime_mode == "python-json-workflow"
    assert [binding.binding_id for binding in application.bindings] == [
        "request_image",
        "deployment_request",
        "http_response",
    ]


def test_yolox_end_to_end_qr_crop_remap_example_documents_are_valid() -> None:
    """验证第一类完整端到端正式示例模板与应用可以通过当前合同校验。"""

    example_dir = (
        Path(__file__).resolve().parents[1] / "docs" / "examples" / "workflows"
    )
    template_path = example_dir / "yolox_end_to_end_qr_crop_remap.template.json"
    application_path = example_dir / "yolox_end_to_end_qr_crop_remap.application.json"
    template = WorkflowGraphTemplate.model_validate(
        json.loads(template_path.read_text(encoding="utf-8"))
    )
    application = FlowApplication.model_validate(
        json.loads(application_path.read_text(encoding="utf-8"))
    )

    custom_nodes_root = Path(__file__).resolve().parents[1] / "custom_nodes"
    node_pack_loader = LocalNodePackLoader(custom_nodes_root)
    node_pack_loader.refresh()
    registry = NodeCatalogRegistry(node_pack_loader=node_pack_loader)
    validate_workflow_graph_template(
        template=template,
        node_definitions=registry.get_workflow_node_definitions(),
    )
    validate_flow_application_bindings(template=template, application=application)

    assert [node.node_id for node in template.nodes[:12]] == [
        "import_request_input",
        "submit_import",
        "extract_import_task_id",
        "build_import_wait_request",
        "wait_import",
        "extract_import_dataset_id",
        "extract_import_dataset_version_id",
        "extract_import_task_task_id",
        "extract_import_task_state",
        "extract_import_task_result",
        "extract_import_task_error_message",
        "extract_import_task_detail",
    ]
    assert template.nodes[5].parameters["path"] == "task_spec.dataset_id"
    assert template.nodes[6].parameters["path"] == "result.dataset_version_id"
    assert template.nodes[3].parameters["fields"]["include_events"] is False
    default_warm_start_node = next(
        node
        for node in template.nodes
        if node.node_id == "resolve_default_training_warm_start_model_version_id"
    )
    assert default_warm_start_node.node_type_id == "core.logic.match-case"
    assert default_warm_start_node.parameters["default_value"] is None
    default_warm_start_request_node = next(
        node
        for node in template.nodes
        if node.node_id == "build_training_default_warm_start_request"
    )
    assert default_warm_start_request_node.parameters["keys"] == [
        "warm_start_model_version_id"
    ]
    pretrained_case_m_node = next(
        node
        for node in template.nodes
        if node.node_id == "build_training_pretrained_case_m"
    )
    assert (
        pretrained_case_m_node.parameters["fields"]["condition"]["path"]
        == "model_scale"
    )
    assert pretrained_case_m_node.parameters["fields"]["condition"]["right"] == "m"
    assert (
        pretrained_case_m_node.parameters["fields"]["then"]
        == "model-version-pretrained-yolox-m"
    )
    conversion_builds_node = next(
        node for node in template.nodes if node.node_id == "extract_conversion_builds"
    )
    assert conversion_builds_node.parameters["path"] == "result.builds"
    conversion_filter_node = next(
        node
        for node in template.nodes
        if node.node_id == "filter_conversion_tensorrt_builds"
    )
    assert conversion_filter_node.parameters["condition"]["path"] == "build_format"
    assert conversion_filter_node.parameters["condition"]["right"] == "tensorrt-engine"
    conversion_build_id_node = next(
        node
        for node in template.nodes
        if node.node_id == "extract_conversion_model_build_id"
    )
    assert conversion_build_id_node.node_type_id == "core.logic.list-item-get"
    assert conversion_build_id_node.parameters["index"] == 0
    deployment_create_node = next(
        node for node in template.nodes if node.node_id == "create_deployment"
    )
    assert deployment_create_node.parameters["cleanup_on_completion"] is True
    assert template.metadata["example_kind"] == "yolox-end-to-end-qr-crop-remap"
    assert template.metadata["deployment_cleanup_policy"] == "delete_on_completion"
    assert template.metadata["node_groups"]["training"] == [
        "build_training_pretrained_case_nano",
        "build_training_pretrained_case_tiny",
        "build_training_pretrained_case_s",
        "build_training_pretrained_case_m",
        "build_training_pretrained_case_l",
        "build_training_pretrained_case_x",
        "build_training_pretrained_cases",
        "resolve_default_training_warm_start_model_version_id",
        "build_training_default_warm_start_request",
        "build_training_dynamic_request",
        "merge_training_request",
        "submit_training",
        "build_training_wait_request",
        "wait_training",
    ]
    assert template.metadata["node_groups"]["deployment"] == [
        "build_deployment_dynamic_request",
        "merge_deployment_request",
        "create_deployment",
        "build_inference_dynamic_request",
        "merge_inference_request",
        "detect",
        "export_crops",
    ]
    assert application.template_ref.source_uri == (
        "docs/examples/workflows/yolox_end_to_end_qr_crop_remap.template.json"
    )
    assert application.runtime_mode == "python-json-workflow"
    assert [binding.binding_id for binding in application.bindings] == [
        "import_request_payload",
        "request_package",
        "export_request_payload",
        "training_request_payload",
        "evaluation_request_payload",
        "conversion_request_payload",
        "deployment_request_payload",
        "inference_request_payload",
        "request_image",
        "response_body",
    ]


def test_dataset_export_package_example_documents_are_valid() -> None:
    """验证 dataset export package 示例模板与应用可以通过当前合同校验。"""

    example_dir = (
        Path(__file__).resolve().parents[1] / "docs" / "examples" / "workflows"
    )
    template_path = example_dir / "dataset_export_package.template.json"
    application_path = example_dir / "dataset_export_package.application.json"
    template = WorkflowGraphTemplate.model_validate(
        json.loads(template_path.read_text(encoding="utf-8"))
    )
    application = FlowApplication.model_validate(
        json.loads(application_path.read_text(encoding="utf-8"))
    )

    registry = NodeCatalogRegistry()
    validate_workflow_graph_template(
        template=template,
        node_definitions=registry.get_workflow_node_definitions(),
    )
    validate_flow_application_bindings(template=template, application=application)

    assert [node.node_type_id for node in template.nodes] == [
        "core.io.template-input.object",
        "core.service.dataset-export.package",
    ]
    assert template.nodes[1].parameters["cleanup_on_completion"] is False
    assert template.metadata["example_kind"] == "dataset-export-package"
    assert template.metadata["cleanup_mode"] == "explicit-node-parameter"
    assert (
        application.template_ref.source_uri
        == "docs/examples/workflows/dataset_export_package.template.json"
    )
    assert application.runtime_mode == "python-json-workflow"
    assert [binding.binding_id for binding in application.bindings] == [
        "request_payload",
        "package_body",
    ]


def test_yolox_evaluation_package_example_documents_are_valid() -> None:
    """验证 YOLOX evaluation package 示例模板与应用可以通过当前合同校验。"""

    example_dir = (
        Path(__file__).resolve().parents[1] / "docs" / "examples" / "workflows"
    )
    template_path = example_dir / "yolox_evaluation_package.template.json"
    application_path = example_dir / "yolox_evaluation_package.application.json"
    template = WorkflowGraphTemplate.model_validate(
        json.loads(template_path.read_text(encoding="utf-8"))
    )
    application = FlowApplication.model_validate(
        json.loads(application_path.read_text(encoding="utf-8"))
    )

    registry = NodeCatalogRegistry()
    validate_workflow_graph_template(
        template=template,
        node_definitions=registry.get_workflow_node_definitions(),
    )
    validate_flow_application_bindings(template=template, application=application)

    assert [node.node_id for node in template.nodes] == [
        "request_payload_input",
        "sanitize_submit_request",
        "merge_submit_request",
        "submit_evaluation",
        "extract_evaluation_task_id",
        "build_evaluation_wait_request",
        "wait_evaluation",
        "extract_waited_task_id",
        "build_package_request",
        "package_result",
    ]
    assert template.nodes[2].parameters["base"]["save_result_package"] is False
    assert template.nodes[5].parameters["fields"]["include_events"] is False
    assert template.nodes[9].parameters["cleanup_on_completion"] is True
    assert template.metadata["example_kind"] == "yolox-evaluation-package"
    assert template.metadata["package_cleanup_policy"] == "delete_on_completion"
    assert template.metadata["submission_result_package_mode"] == "disabled_in_submit"
    assert (
        application.template_ref.source_uri
        == "docs/examples/workflows/yolox_evaluation_package.template.json"
    )
    assert application.runtime_mode == "python-json-workflow"
    assert [binding.binding_id for binding in application.bindings] == [
        "request_payload",
        "submission_body",
        "evaluation_task_detail",
        "package_body",
    ]


@pytest.mark.parametrize(
    (
        "example_name",
        "expected_example_kind",
        "expected_node_type_id",
        "expected_binding_ids",
    ),
    [
        pytest.param(
            "dataset_import_upload",
            "dataset-import-upload",
            "core.service.dataset-import.submit",
            ["request_payload", "request_package", "submission_body"],
            id="dataset-import-upload",
        ),
        pytest.param(
            "dataset_export_submit",
            "dataset-export-submit",
            "core.service.dataset-export.submit",
            ["request_payload", "submission_body"],
            id="dataset-export-submit",
        ),
        pytest.param(
            "yolox_training_submit",
            "yolox-training-submit",
            "core.service.yolox-training.submit",
            ["request_payload", "submission_body"],
            id="yolox-training-submit",
        ),
        pytest.param(
            "yolox_evaluation_submit",
            "yolox-evaluation-submit",
            "core.service.yolox-evaluation.submit",
            ["request_payload", "submission_body"],
            id="yolox-evaluation-submit",
        ),
        pytest.param(
            "yolox_conversion_submit",
            "yolox-conversion-submit",
            "core.service.yolox-conversion.submit",
            ["request_payload", "submission_body"],
            id="yolox-conversion-submit",
        ),
    ],
)
def test_submit_and_import_example_documents_are_valid(
    example_name: str,
    expected_example_kind: str,
    expected_node_type_id: str,
    expected_binding_ids: list[str],
) -> None:
    """验证 DatasetImport 与 submit family 正式示例可以通过当前合同校验。"""

    example_dir = (
        Path(__file__).resolve().parents[1] / "docs" / "examples" / "workflows"
    )
    template_path = example_dir / f"{example_name}.template.json"
    application_path = example_dir / f"{example_name}.application.json"
    template = WorkflowGraphTemplate.model_validate(
        json.loads(template_path.read_text(encoding="utf-8"))
    )
    application = FlowApplication.model_validate(
        json.loads(application_path.read_text(encoding="utf-8"))
    )

    registry = NodeCatalogRegistry()
    validate_workflow_graph_template(
        template=template,
        node_definitions=registry.get_workflow_node_definitions(),
    )
    validate_flow_application_bindings(template=template, application=application)

    assert [node.node_type_id for node in template.nodes] == [
        "core.io.template-input.object",
        expected_node_type_id,
    ]
    assert template.metadata["example_kind"] == expected_example_kind
    assert template.metadata["dynamic_request_binding_id"] == "request_payload"
    assert (
        application.template_ref.source_uri
        == f"docs/examples/workflows/{example_name}.template.json"
    )
    assert application.runtime_mode == "python-json-workflow"
    assert [
        binding.binding_id for binding in application.bindings
    ] == expected_binding_ids
