"""用真实正面参考图、受控扰动和实际图执行器验证拆分后的检查链。"""

from copy import deepcopy
from dataclasses import replace
import gc
import json
from pathlib import Path
from time import perf_counter

import cv2
import numpy as np
import psutil

from backend.contracts.workflows.workflow_graph import (
    WorkflowGraphTemplate,
    validate_workflow_graph_template,
)
from backend.nodes import ExecutionImageRegistry
from backend.nodes.local_node_pack_loader import LocalNodePackLoader
from backend.nodes.node_catalog_registry import NodeCatalogRegistry
from backend.nodes.runtime_support import register_typed_image_matrix
from backend.service.application.workflows.graph_executor import (
    WorkflowGraphExecutor,
    WorkflowNodeExecutionRequest,
)
from backend.service.application.workflows.runtime_registry_loader import (
    WorkflowNodeRuntimeRegistryLoader,
)
from custom_nodes.opencv_nodes.categories.defect.backend.nodes.roi_foreground_compare import (
    handle_node as old_compare,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.images import load_image_matrix
from scripts.configure_linescan_front_inspection import OUT, CHECKS, build
from scripts.simplify_linescan_front_grid import OUT as GRID_OUT
from scripts.validate_linescan_front_cases import ROOT
from scripts.validate_linescan_front_registration import (
    image_ref,
    request,
    hough,
    locate,
)


def extract_graph(template, *, evidence=False):
    """只抽取放置检查子图，输入保持已配准坐标；不模拟任何测量和判定处理器。"""
    t = deepcopy(template)
    allowed = {
        "slot_array",
        "align",
        "load_reference",
        "compare_foreground",
        "inspection_checks",
    }
    for group in t["groups"]:
        if (
            group["group_id"] in {"inspection-extract", "inspection-checks"}
            or evidence
            and group["group_id"] == "inspection-evidence"
        ):
            allowed.update(group["member_node_ids"])
    allowed.discard("reference_path")
    t["groups"] = []
    t["notes"] = []
    t["nodes"] = [n for n in t["nodes"] if n["node_id"] in allowed]
    for n in t["nodes"]:
        if n["node_id"] in {"align", "load_reference"}:
            n.update(node_type_id="core.io.template-input.image", parameters={})
        if n["node_id"] == "slot_array":
            n["parameters"]["debug_image_panel_enabled"] = False
    t["edges"] = [
        e
        for e in t["edges"]
        if e["source_node_id"] in allowed
        and e["target_node_id"] in allowed
        and e["target_node_id"] not in {"align", "load_reference"}
    ]
    t["template_inputs"] = [
        {
            "input_id": key,
            "display_name": key,
            "payload_type_id": "image-ref.v1",
            "target_node_id": node,
            "target_port": "payload",
        }
        for key, node in [("current", "align"), ("reference", "load_reference")]
    ]
    t["template_outputs"] = [
        {
            "output_id": "summary",
            "display_name": "Summary",
            "payload_type_id": "value.v1",
            "source_node_id": "compare_foreground",
            "source_port": "summary",
        },
        {
            "output_id": "rois",
            "display_name": "ROIs",
            "payload_type_id": "roi-list.v1",
            "source_node_id": "slot_array",
            "source_port": "rois",
        },
    ]
    if evidence:
        for name, *_ in CHECKS:
            for prefix, port, kind in [
                ("evidence", "images", "image-refs.v1"),
                ("values", "body", "response-body.v1"),
                ("gallery", "body", "response-body.v1"),
            ]:
                t["template_outputs"].append(
                    {
                        "output_id": prefix + "_" + name,
                        "display_name": name,
                        "payload_type_id": kind,
                        "source_node_id": prefix + "_" + name,
                        "source_port": port,
                    }
                )
    return WorkflowGraphTemplate.model_validate(t)


def main():
    """验证整体草稿结构、七类真实/受控图片、可视化链和重复执行资源。"""
    OUT.mkdir(parents=True, exist_ok=True)
    baseline = json.loads((GRID_OUT / "grid-workflow.json").read_text("utf-8"))
    prepared = build(**baseline)
    nodes = {n["node_id"]: n for n in baseline["template"]["nodes"]}
    pack = LocalNodePackLoader(Path("custom_nodes").resolve())
    pack.refresh()
    catalog = NodeCatalogRegistry(node_pack_loader=pack)
    validate_workflow_graph_template(
        template=WorkflowGraphTemplate.model_validate(prepared["template"]),
        node_definitions=catalog.get_workflow_node_definitions(),
    )
    loader = WorkflowNodeRuntimeRegistryLoader(
        node_catalog_registry=catalog, node_pack_loader=pack
    )
    loader.refresh()
    executor = WorkflowGraphExecutor(registry=loader.get_runtime_registry())
    graph = extract_graph(prepared["template"])
    graph_evidence = extract_graph(prepared["template"], evidence=True)
    report = {
        "cases": [],
        "repeats": [],
        "scope": "registered-overview inspection subgraph; no model/barcode runtime measurement",
    }
    reference = cv2.imdecode(
        np.fromfile(ROOT / "reference.png", np.uint8), cv2.IMREAD_COLOR
    )
    aligned_original = None
    for name, path in [
        (n, ROOT / f"localization-{n}.png")
        for n in ["original", "shift", "rotate", "rotate-negative"]
    ] + [
        (n, ROOT / f"controlled-{n}.png")
        for n in ["missing", "displaced", "tilted", "no-anchors"]
    ]:
        circles = hough(
            request(
                "shape",
                "hough_circles",
                {"image": image_ref(path)},
                nodes["circles"]["parameters"],
            )
        )
        try:
            pose = locate(
                request(
                    "matching",
                    "circle_pattern_locate",
                    {"circles": circles["circles"]},
                    nodes["locate"]["parameters"],
                )
            )
        except Exception:
            if name != "no-anchors":
                raise
            report["cases"].append({"case": name, "localization_rejected": True})
            continue
        assert name != "no-anchors"
        source = cv2.imdecode(np.fromfile(path, np.uint8), cv2.IMREAD_COLOR)
        aligned = cv2.warpPerspective(
            source,
            np.array(pose["transform"]["matrix_3x3"]),
            (2500, 2048),
            flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
            borderValue=(255, 255, 255),
        )
        if name == "original":
            aligned_original = aligned
        registry = ExecutionImageRegistry()
        req = WorkflowNodeExecutionRequest(
            node_id="validation",
            node_definition=object(),
            input_values={},
            parameters={},
            execution_metadata={"execution_image_registry": registry},
        )
        try:
            inputs = {
                "current": register_typed_image_matrix(req, image_matrix=aligned),
                "reference": register_typed_image_matrix(req, image_matrix=reference),
            }
            started = perf_counter()
            output = executor.execute(
                template=graph_evidence,
                input_values=inputs,
                execution_metadata=req.execution_metadata,
            ).outputs
            elapsed = (perf_counter() - started) * 1000
            summary = output["summary"]["value"]
            failed = [
                i["item_id"] for i in summary["items"] if not i["result"]["passed"]
            ]
            expected = (
                ["slot-02-03", "slot-02-04"]
                if name == "displaced"
                else ["slot-02-03"]
                if name in {"missing", "tilted"}
                else []
            )
            assert failed == expected, (name, failed, expected)
            previous = old_compare(
                replace(
                    req,
                    input_values={
                        "image": inputs["current"],
                        "reference_image": inputs["reference"],
                        "rois": output["rois"],
                    },
                    parameters=nodes["compare_foreground"]["parameters"],
                )
            )["summary"]["value"]
            old = {i["item_id"]: i["result"] for i in previous["items"]}
            for item in summary["items"]:
                c = item["result"]["checks"]
                p = old[item["item_id"]]
                for check, key in [
                    ("missing", "missing_ratio"),
                    ("excess", "excess_ratio"),
                    ("shift", "centroid_shift_pixels"),
                    ("angle", "axis_angle_difference_degrees"),
                ]:
                    if key in p and p[key] is not None:
                        assert abs(c[check]["value"] - p[key]) < 1e-8, (
                            name,
                            item["item_id"],
                            check,
                            c[check]["value"],
                            p[key],
                        )
            evidence = []
            for check, *_ in CHECKS:
                table = output["values_" + check]
                assert len(table["rows"]) == 18 and all(
                    row["slot"] for row in table["rows"]
                )
                selected = next(
                    (
                        i
                        for i in output["evidence_" + check]["items"]
                        if i["roi_id"] == "slot-02-03"
                    ),
                    None,
                )
                _, _, matrix = load_image_matrix(
                    replace(req, input_values={"image": selected})
                )
                filename = f"{name}-{check}.jpg"
                (OUT / filename).write_bytes(cv2.imencode(".jpg", matrix)[1].tobytes())
                evidence.append(filename)
            report["cases"].append(
                {
                    "case": name,
                    "failed": failed,
                    "with_evidence_ms": elapsed,
                    "summary": summary,
                    "evidence": evidence,
                }
            )
            print(name, failed, round(elapsed, 1), "ms", flush=True)
        finally:
            registry.clear()
    process = psutil.Process()
    for i in range(30):
        registry = ExecutionImageRegistry()
        req = WorkflowNodeExecutionRequest(
            node_id="bench",
            node_definition=object(),
            input_values={},
            parameters={},
            execution_metadata={"execution_image_registry": registry},
        )
        try:
            inputs = {
                "current": register_typed_image_matrix(
                    req, image_matrix=aligned_original
                ),
                "reference": register_typed_image_matrix(req, image_matrix=reference),
            }
            start = perf_counter()
            result = executor.execute(
                template=graph,
                input_values=inputs,
                execution_metadata=req.execution_metadata,
            )
            elapsed = (perf_counter() - start) * 1000
            assert result.outputs["summary"]["value"]["passed"]
        finally:
            registry.clear()
        del result, inputs, req, registry
        gc.collect()
        mem = process.memory_info()
        report["repeats"].append(
            {
                "iteration": i + 1,
                "ms": elapsed,
                "private_bytes": getattr(mem, "private", mem.rss),
                "handles": process.num_handles(),
            }
        )
    (OUT / "inspection-workflow.json").write_text(
        json.dumps(prepared, ensure_ascii=False, indent=2), "utf-8"
    )
    (OUT / "validation.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), "utf-8"
    )
    print(
        "validated",
        len(prepared["template"]["nodes"]),
        "nodes; repeats",
        len(report["repeats"]),
        flush=True,
    )


if __name__ == "__main__":
    main()
