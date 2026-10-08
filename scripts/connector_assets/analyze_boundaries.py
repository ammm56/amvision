"""分解合成连接器临界宽度误差；真值只用于离线比较，不进入节点推理。"""

from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path
from time import perf_counter

import cv2
import numpy as np

from backend.nodes import ExecutionImageRegistry
from backend.nodes.runtime_support import register_image_matrix
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)
from backend.service.application.workflows.documents.measurement_resources import (
    MeasurementResourceService,
    PreparedMeasurementResources,
)
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings,
    LocalDatasetStorage,
)
from custom_nodes.connector_nodes.categories.array.backend.nodes.pin_array_locate import (
    handle_node as pins_node,
)
from custom_nodes.connector_nodes.categories.measurement.backend.nodes.measure import (
    handle_node as measure_node,
)
from custom_nodes.opencv_nodes.categories.matching.backend.nodes.rigid_locate import (
    handle_node as pose_node,
)
from custom_nodes.opencv_nodes.shared.backend.metrology import (
    EdgePairSettings,
    extract_edge_pair,
    measure_section,
    prepare_gray,
)
from scripts.connector_assets.workflow import build_example


def request(registry, parameters, inputs, prepared):
    """构造离线调用；所有图像和资源仍通过生产节点的同次身份检查。"""
    return WorkflowNodeExecutionRequest(
        node_id="boundary-analysis",
        node_definition=object(),
        parameters=parameters,
        input_values=inputs,
        execution_metadata={
            "execution_image_registry": registry,
            "workflow_run_id": "boundary-analysis",
            "project_id": "boundary-analysis",
            "prepared_measurement_resources": prepared,
        },
    )


def width(gray, center, settings):
    """在相同有限截面读取真实边缘对，失败保留原因。"""
    pair = extract_edge_pair(gray, center, [1.0, 0.0], settings)
    if pair["state"] != "found":
        return {"state": pair["state"], "reason": pair["reason"]}
    left = measure_section(pair["left"], np.array([1.0, 0.0]), center[1])
    right = measure_section(pair["right"], np.array([1.0, 0.0]), center[1])
    return {
        "state": "found",
        "width_px": float(right[0] - left[0]),
        "left_px": float(left[0]),
        "right_px": float(right[0]),
        "residual_px": pair["residual_px"],
    }


def analyze(assets: Path, scratch: Path) -> dict:
    """相同原图比较固定姿态/实际定位、标定映射及采样敏感性。"""
    storage = LocalDatasetStorage(
        DatasetStorageSettings(root_dir=str(scratch / "store"))
    )
    service = MeasurementResourceService(storage)
    report = {
        "synthetic_only": True,
        "image_encoding": "srgb",
        "samples": [],
        "ideal_controls": [],
    }
    for family in ("single10_front", "dual08_top"):
        graph, _, resources = build_example(
            service, assets, project_id="boundary-analysis", family=family
        )
        prepared = PreparedMeasurementResources(storage).prepare(
            tuple(resource.reference for resource in resources),
            project_id="boundary-analysis",
        )
        parameters = {node.node_id: node.parameters for node in graph.nodes}
        layout = parameters["pins"]["layout"]
        for condition in (
            "reference",
            "width_inside_limit",
            "width_on_limit",
            "width_outside_limit",
            "translate",
            "rotate_pos",
            "rotate_neg",
            "dark",
            "bright",
        ):
            name = f"{family}__{condition}"
            truth = json.loads(
                (assets / "truth" / f"{name}.json").read_text(encoding="utf-8")
            )
            image = cv2.imdecode(
                np.fromfile(assets / "images" / f"{name}.png", np.uint8),
                cv2.IMREAD_COLOR,
            )
            registry = ExecutionImageRegistry()
            req = request(registry, {}, {}, prepared)
            payload = register_image_matrix(req, image_matrix=image)
            tick = perf_counter()
            pose = pose_node(
                request(registry, parameters["locate"], {"image": payload}, prepared)
            )["pose"]
            pose_ms = (perf_counter() - tick) * 1000
            outputs = pins_node(
                request(
                    registry,
                    parameters["pins"],
                    {"image": payload, "pose": pose},
                    prepared,
                )
            )
            inputs = {key: outputs[key] for key in ("pins", "features")}
            physical = measure_node(
                request(registry, parameters["measure"], inputs, prepared)
            )
            pixel_params = dict(
                parameters["measure"], unit="pixel", calibration_resource=None
            )
            pixels = measure_node(request(registry, pixel_params, inputs, prepared))
            px_items = {i["item_id"]: i for i in pixels["measurements"]["items"]}
            scale = truth["camera"]["pixels_per_mm"]
            nominal = {"width:" + p["pin_id"]: p for p in truth["pins"]}
            items = []
            for item in physical["measurements"]["items"]:
                if not item["item_id"].startswith("width:"):
                    continue
                target = nominal[item["item_id"]]
                value, px = item["value"], px_items[item["item_id"]]["value"]
                ends = np.asarray(target["width_endpoints_image_px"])
                items.append(
                    {
                        "id": item["item_id"],
                        "nominal_mm": target["width_mm"],
                        "projected_px": float(np.linalg.norm(ends[1] - ends[0])),
                        "measured_px": px,
                        "measured_mm": value,
                        "reason": item["reason"],
                        "error_mm": None
                        if value is None
                        else value - target["width_mm"],
                        "mapping_delta_mm": None
                        if value is None
                        else value - px / scale,
                    }
                )
            row = {"sample": name, "pose": pose, "pose_ms": pose_ms, "widths": items}
            if condition in (
                "reference",
                "width_inside_limit",
                "width_on_limit",
                "width_outside_limit",
            ):
                # 固定姿态只是本分析的对照组，不替换产品的实际定位结果。
                fixed = pins_node(
                    request(
                        registry,
                        dict(parameters["pins"], pose_mode="fixed"),
                        {"image": payload},
                        prepared,
                    )
                )
                fixed_values = measure_node(
                    request(
                        registry,
                        parameters["measure"],
                        {k: fixed[k] for k in ("pins", "features")},
                        prepared,
                    )
                )
                row["fixed_widths_mm"] = {
                    i["item_id"]: i["value"]
                    for i in fixed_values["measurements"]["items"]
                    if i["item_id"].startswith("width:")
                }
                index = 4
                center = layout["pins"][index]["center"]
                gray = prepare_gray(
                    image, image_encoding=parameters["pins"]["image_encoding"]
                )
                settings = EdgePairSettings(
                    min_width=12.0,
                    max_width=35.0,
                    gradient_threshold=layout["types"][0]["gradient_threshold"],
                )
                row["sampling"] = [
                    {
                        "step": step,
                        **width(gray, center, replace(settings, sample_step=step)),
                    }
                    for step in (0.25, 0.5, 1.0)
                ]
                row["blur"] = [
                    {
                        "sigma_px": sigma,
                        **width(
                            cv2.GaussianBlur(gray, (0, 0), sigma) if sigma else gray,
                            center,
                            settings,
                        ),
                    }
                    for sigma in (0, 0.5, 1.0)
                ]
                row["gray_gain"] = [
                    {
                        "gain": gain,
                        **width(np.clip(gray * gain, 0, 1), center, settings),
                    }
                    for gain in (0.7, 1.0, 1.2)
                ]
            report["samples"].append(row)
            print(
                name,
                "pose",
                pose["state"],
                "max width error",
                max(
                    (abs(i["error_mm"]) for i in items if i["error_mm"] is not None),
                    default=None,
                ),
                flush=True,
            )
        # 解析面积覆盖的理想光栅控制，不使用 Blender 图或真值作为检测输入。
        for resolution in (1, 2):
            for phase in (0.0, 0.25, 0.5, 0.75):
                center = [100.0 + phase, 24.0]
                target_width = 0.68 * scale * resolution
                x = np.arange(220)
                left, right = center[0] - target_width / 2, center[0] + target_width / 2
                coverage = np.clip(
                    np.minimum(x + 0.5, right) - np.maximum(x - 0.5, left), 0, 1
                )
                gray = np.tile((0.15 + 0.65 * coverage).astype(np.float32), (50, 1))
                settings = EdgePairSettings(
                    search_length=96, min_width=10, max_width=70
                )
                result = width(gray, center, settings)
                report["ideal_controls"].append(
                    {
                        "family": family,
                        "resolution_multiplier": resolution,
                        "phase_px": phase,
                        "target_width_mm": 0.68,
                        "error_mm": (result["width_px"] - target_width)
                        / (scale * resolution),
                        **result,
                    }
                )
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--scratch", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    result = analyze(args.assets.resolve(), args.scratch.resolve())
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
