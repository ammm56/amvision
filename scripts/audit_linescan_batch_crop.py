"""用真实大图对照逐槽裁剪与列表裁剪的像素和来源坐标，不调用模型。"""

import json
from dataclasses import replace
from pathlib import Path
from time import perf_counter

import numpy as np
import cv2

from backend.contracts.workflows.workflow_graph import NodeDefinition
from backend.nodes import ExecutionImageRegistry
from backend.nodes.runtime_support import register_typed_image_matrix
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)
from custom_nodes.opencv_nodes.categories.geometry.backend.nodes.mapped_roi_crop import (
    handle_node,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.bmp import read_bgr24_bmp
from scripts.configure_linescan_3913_workflow import DATA


def main():
    """同一真实图、位姿与手选窗口；只改变节点调用数量。"""
    root = DATA / "validation/front-optimization-20261030"
    candidate = json.loads((root / "candidate.json").read_text("utf-8"))
    nodes = {n["node_id"]: n for n in candidate["template"]["nodes"]}
    baseline = json.loads(
        (
            DATA
            / "validation/front-performance/final-result-audit-production/report.json"
        ).read_text("utf-8")
    )
    response = baseline["runs"][0]["response"]
    outputs = response.get("outputs") or response["results"]
    diagnostic = outputs["audit_report"]["value"]
    pose = diagnostic["tray_localization"]
    angle = np.radians(pose["angle_degrees"])
    dx, dy = pose["translation_xy"]
    transform = {
        "transform_kind": "rigid",
        "matrix_3x3": [
            [np.cos(angle), -np.sin(angle), dx],
            [np.sin(angle), np.cos(angle), dy],
            [0, 0, 1],
        ],
        "source_coordinate_space": "template-image-pixels",
        "target_coordinate_space": "source-image-pixels",
        "match_count": 3,
        "inlier_count": 3,
        "inlier_match_ids": [],
    }
    regions = [item["source"] for item in diagnostic["placement_2d"]["items"]]
    window = {
        k: v
        for k, v in nodes["barcode_roi"]["parameters"].items()
        if k in {"roi_kind", "roi_id", "bbox_xyxy"}
    }
    x1, y1, x2, y2 = window["bbox_xyxy"]
    window.update(
        polygon_xy=[[x1, y1], [x2, y1], [x2, y2], [x1, y2]], area=(x2 - x1) * (y2 - y1)
    )
    definition = NodeDefinition.model_validate(
        json.loads(
            Path(
                "custom_nodes/opencv_nodes/categories/geometry/workflow/catalog_sources/nodes/mapped_roi_crop.json"
            ).read_text("utf-8")
        )
    )
    matrix = read_bgr24_bmp(DATA / "3913正面大图.bmp")
    overview = cv2.resize(matrix, (2500, 2048), interpolation=cv2.INTER_AREA)
    rows = []
    for batch in [False, True, True, False]:
        registry = ExecutionImageRegistry(decoded_cache_max_bytes=1)
        try:
            # 统一通过节点注册辅助函数生成标准 payload，不手工构造句柄元数据。
            request = WorkflowNodeExecutionRequest(
                node_id="crop",
                node_definition=definition,
                parameters=nodes["crop_search"]["parameters"],
                input_values={},
                execution_metadata={"execution_image_registry": registry},
            )
            source = register_typed_image_matrix(request, image_matrix=matrix)
            transform["source_b_image"] = register_typed_image_matrix(
                request, image_matrix=overview
            )
            started = perf_counter()
            records = []
            for subset in [regions] if batch else [[region] for region in regions]:
                result = handle_node(
                    replace(
                        request,
                        input_values={
                            "image": source,
                            "transform": transform,
                            **({"rois": subset} if batch else {"roi": subset[0]}),
                            "window_roi": window,
                        },
                    )
                )
                for item in result["crops"]["items"]:
                    records.append(
                        {
                            "id": item["roi_id"],
                            "sha256": item["content_sha256"],
                            "source_from_crop": item["mapped_source"][
                                "source_from_crop"
                            ],
                        }
                    )
            row = {
                "batch": batch,
                "elapsed_ms": (perf_counter() - started) * 1000,
                "records": records,
            }
            if rows:
                assert records == rows[0]["records"]
            rows.append(row)
            print(
                batch,
                round(row["elapsed_ms"], 2),
                "18 pixels/IDs/transforms equal",
                flush=True,
            )
        finally:
            registry.clear()
    (root / "crop-batch.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), "utf-8"
    )


if __name__ == "__main__":
    main()
