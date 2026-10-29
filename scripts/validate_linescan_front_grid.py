"""按已保存网格配方复测真实概览图与已有受控扰动，不作为现场缺陷精度认证。"""

from dataclasses import replace
import json

import cv2
import numpy as np

from backend.nodes import ExecutionImageRegistry
from backend.nodes.core_nodes.vision.roi.roi_grid_create import _roi_grid_create_handler
from backend.nodes.runtime_support import register_typed_image_matrix
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)
from custom_nodes.opencv_nodes.categories.defect.backend.nodes.roi_foreground_compare import (
    handle_node as compare,
)
from scripts.simplify_linescan_front_grid import OUT
from scripts.validate_linescan_front_cases import ROOT
from scripts.validate_linescan_front_registration import (
    image_ref,
    request,
    hough,
    locate,
)


def main():
    """执行定位、校正、网格和实际比较处理器；每次释放图像注册表。"""
    bundle = json.loads((OUT / "grid-workflow.json").read_text("utf-8"))
    nodes = {n["node_id"]: n for n in bundle["template"]["nodes"]}
    rois = _roi_grid_create_handler(
        WorkflowNodeExecutionRequest(
            node_id="grid",
            node_definition=object(),
            parameters=nodes["slot_array"]["parameters"],
            input_values={},
            execution_metadata={},
        )
    )["rois"]
    records = []
    cases = [
        (name, ROOT / f"localization-{name}.png")
        for name in ["original", "shift", "rotate", "rotate-negative"]
    ]
    cases += [
        (name, ROOT / f"controlled-{name}.png")
        for name in ["missing", "displaced", "tilted", "no-anchors"]
    ]
    for name, path in cases:
        registry = ExecutionImageRegistry()
        try:
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
                records.append({"case": name, "localization_rejected": True})
                continue
            assert name != "no-anchors"
            source = cv2.imdecode(np.fromfile(path, np.uint8), cv2.IMREAD_COLOR)
            aligned = cv2.warpPerspective(
                source,
                np.asarray(pose["transform"]["matrix_3x3"]),
                (2500, 2048),
                flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
            )
            req = replace(
                request(
                    "defect",
                    "roi_foreground_compare",
                    {},
                    nodes["compare_foreground"]["parameters"],
                ),
                execution_metadata={"execution_image_registry": registry},
            )
            output = compare(
                replace(
                    req,
                    input_values={
                        "image": register_typed_image_matrix(req, image_matrix=aligned),
                        "reference_image": image_ref(ROOT / "reference.png"),
                        "rois": rois,
                    },
                )
            )
            items = output["summary"]["value"]["items"]
            failed = [r["item_id"] for r in items if not r["result"]["passed"]]
            expected = (
                ["slot-02-03", "slot-02-04"]
                if name == "displaced"
                else ["slot-02-03"]
                if name in {"missing", "tilted"}
                else []
            )
            assert failed == expected, (name, failed)
            records.append({"case": name, "failed": failed, "items": items})
            print(name, "passed", 18 - len(failed), "failed", failed, flush=True)
        finally:
            registry.clear()
    (OUT / "placement-cases.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2), "utf-8"
    )


if __name__ == "__main__":
    main()
