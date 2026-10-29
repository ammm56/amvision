"""使用现有通用节点配置批量推理；图片与结果按显式 roi_id 关联。"""

import copy


def build(application, template):
    """先收集正常槽位的搜索图，再一次推理；没有正常槽位时显式跳过模型。"""
    application, template = copy.deepcopy(application), copy.deepcopy(template)
    nodes = {item["node_id"]: item for item in template["nodes"]}
    parameters = nodes["detect_code"]["parameters"]
    edges = [
        edge
        for edge in template["edges"]
        if edge["target_node_id"]
        not in {"source_id", "detect_code", "search_image", "barcodes_field"}
        and not (
            edge["source_node_id"] == "search_image_value"
            and edge["target_node_id"] == "source_mapping"
        )
    ]

    def node(name, kind, **params):
        """创建通用节点定义。"""
        nodes[name] = dict(
            node_id=name,
            node_type_id=kind,
            parameters=params,
            enabled=True,
            metadata={},
            ui_state={},
        )

    def edge(source, port, target, target_port):
        """连接明确端口，不使用连线或布局顺序关联数据。"""
        edges.append(
            dict(
                edge_id="pending",
                source_node_id=source,
                source_port=port,
                target_node_id=target,
                target_port=target_port,
            )
        )

    # 原循环仅负责窗口裁图；局部图总计约 54 MB，生命周期仍属于本次运行。
    node("prepared_image", "core.io.image-refs-item-get", index=0)
    node("prepared_value", "core.logic.payload-to-value")
    node("prepared_end", "core.logic.for-each-end")
    edge("crop_search", "crops", "prepared_image", "images")
    edge("prepared_image", "image", "prepared_value", "image")
    edge("prepared_value", "value", "prepared_end", "result")
    node("prepared_count", "core.logic.list-length")
    node("prepared_nonempty", "core.logic.compare", operator="gt", right_value=0)
    node("batch_condition", "core.logic.conditional-start")
    node("batch_condition_end", "core.logic.conditional-end")
    edge("prepared_end", "results", "prepared_count", "items")
    edge("prepared_count", "value", "prepared_nonempty", "left")
    edge("prepared_nonempty", "result", "batch_condition", "condition")
    edge("prepared_end", "results", "batch_condition", "value")
    edge("batch_condition", "if_false", "batch_condition_end", "result")
    edge("barcode_end", "results", "barcodes_field", "value")

    node("batch_images", "core.logic.value-to-image-refs")
    node("batch_input", "core.logic.value-field-extract", path="")
    node(
        "batch_detect",
        "core.model.detection-batch",
        **{
            key: value
            for key, value in parameters.items()
            if key not in {"return_preview_image_base64", "save_result_image"}
        },
    )
    node("batch_items", "core.logic.detections-batch-to-items")
    node("batch_results_by_id", "core.logic.list-group-by", path="item_id")
    node("batch_results_field", "core.logic.object-field", key="results_by_id")
    node("batch_images_field", "core.logic.object-field", key="images")
    node("batch_context", "core.logic.object-build")
    node("batch_context_images", "core.logic.value-field-extract", path="images")
    node("decode_loop", "core.logic.for-each-start")
    edge("batch_condition", "if_true", "batch_input", "value")
    edge("batch_input", "value", "batch_images", "value")
    edge("batch_images", "images", "batch_detect", "images")
    edge("batch_detect", "detections_batch", "batch_items", "detections_batch")
    edge("batch_items", "items", "batch_condition_end", "result")
    edge("batch_condition_end", "result", "batch_results_by_id", "items")
    edge("batch_results_by_id", "value", "batch_results_field", "value")
    edge("prepared_end", "results", "batch_images_field", "value")
    edge("batch_results_field", "field", "batch_context", "entries")
    edge("batch_images_field", "field", "batch_context", "entries")
    edge("batch_context", "value", "batch_context_images", "value")
    edge("batch_context_images", "value", "decode_loop", "items")

    # 动态路径只使用已生成的槽位 ID；取该 ID 分组中的唯一模型结果。
    node("source_id", "core.logic.value-field-extract", path="roi_id")
    node("search_image", "core.logic.value-to-image-ref")
    node("selected_result", "core.logic.value-field-extract", path="")
    node("selected_detection", "core.logic.value-field-extract", path="0.result")
    node("detect_code", "core.logic.value-to-detections")
    edge("decode_loop", "item", "source_id", "value")
    edge("decode_loop", "item", "search_image", "value")
    edge("batch_results_by_id", "value", "selected_result", "value")
    edge("source_id", "value", "selected_result", "path")
    edge("selected_result", "value", "selected_detection", "value")
    edge("selected_detection", "value", "detect_code", "value")
    edge("search_image_value", "value", "source_mapping", "value")

    # 保持既有前三阶段；后续依次为窗口准备、批量检测、逐槽读码、汇总。
    stages = [
        (
            "04 正常工件 / 手选条码区域",
            [
                ["editor_slot_value", "editor_slot_roi", "crop_part", "part_image"],
                [
                    "part_display_encode",
                    "barcode_roi",
                    "roi_field",
                    "barcode_passed_field",
                ],
                [
                    "barcode_context",
                    "barcode_context_items",
                    "barcode_loop",
                    "part_roi_value",
                ],
                ["part_roi", "crop_search", "prepared_image", "prepared_value"],
                ["prepared_end"],
            ],
        ),
        (
            "05 批量检测 / 空列表分支",
            [
                [
                    "prepared_count",
                    "prepared_nonempty",
                    "batch_condition",
                    "batch_input",
                ],
                ["batch_images", "batch_detect", "batch_items", "batch_condition_end"],
                [
                    "batch_results_by_id",
                    "batch_results_field",
                    "batch_images_field",
                    "batch_context",
                ],
                ["batch_context_images", "decode_loop"],
            ],
        ),
        (
            "06 按槽位关联 / 外扩 / 读码",
            [
                ["source_id", "selected_result", "selected_detection", "detect_code"],
                [
                    "search_image",
                    "search_image_value",
                    "source_mapping",
                    "search_preview",
                ],
                ["code_regions", "filter_codes", "code_grayscale", "crop_code"],
                [
                    "draw_detection",
                    "detection_preview",
                    "code_crop_preview",
                    "decode_codes",
                ],
                ["detection_value", "detection_values_preview", "code_values_preview"],
            ],
        ),
        (
            "07 按槽位汇总",
            [
                [
                    "item_id_field",
                    "source_field",
                    "code_result_field",
                    "detection_field",
                ],
                ["code_item", "barcode_end", "barcodes_field", "pose_field"],
                ["inspection_field", "report", "report_preview"],
            ],
        ),
    ]
    template["groups"] = template["groups"][:3]
    for stage_index, (title, rows) in enumerate(stages, start=4):
        x = 400 + (stage_index - 1) * 1760
        members = [name for row in rows for name in row]
        for row_index, row in enumerate(rows):
            for column, name in enumerate(row):
                nodes[name]["ui_state"] = dict(
                    x=x + 40 + column * 420, y=80 + row_index * 1200, width=350
                )
        template["groups"].append(
            dict(
                group_id=f"stage-{stage_index}",
                name=title,
                enabled=True,
                rect=dict(x=x, y=0, width=1720, height=len(rows) * 1200 + 120),
                member_node_ids=members,
                member_note_ids=[],
                membership_policy="full-containment",
                color="#22b8cf",
                collapsed=False,
                locked=False,
                metadata={},
            )
        )
    assigned = [
        name for group in template["groups"] for name in group["member_node_ids"]
    ]
    assert len(assigned) == len(set(assigned)) and set(assigned) == set(nodes)
    application.setdefault("metadata", {}).setdefault("workflow_graph_editor", {})[
        "boundary_positions"
    ] = {"entry": {"x": 0, "y": 80}, "result": {"x": 12800, "y": 2480}}
    for index, item in enumerate(edges):
        item["edge_id"] = f"e{index + 1:03}"
    template.update(nodes=list(nodes.values()), edges=edges)
    return dict(application=application, template=template)
