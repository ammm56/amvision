"""生成可审阅的连接器工程 Workflow；只写显式指定的隔离资源目录。"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from backend.contracts.workflows.measurement_resources import MeasurementResourceContent
from backend.contracts.workflows.metrology import PlanarCalibration
from backend.contracts.workflows.workflow_app_mode import (
    WorkflowAppModeConfig,
    WorkflowAppModeDisplay,
)
from backend.contracts.workflows.workflow_graph import (
    FlowApplication,
    WorkflowGraphTemplate,
)
from backend.service.application.workflows.documents.measurement_resources import (
    MeasurementResourceService,
)
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings,
    LocalDatasetStorage,
)


def build_example(
    service: MeasurementResourceService, assets: Path, *, project_id: str, family: str
):
    """参考图建配方；禁止读取待检缺陷图真值来反推检查结果。"""
    if family not in {"single10_front", "dual08_top"}:
        raise ValueError("Unknown engineering connector family")
    truth = json.loads(
        (assets / "truth" / f"{family}__reference.json").read_text(encoding="utf-8")
    )
    reference = json.loads(
        (assets / "references" / f"{family}.json").read_text(encoding="utf-8")
    )
    encoded = (assets / reference["image"]).read_bytes()
    polygon = np.asarray(reference["template_roi_polygon_px"])
    low, high = (
        np.floor(polygon.min(axis=0) - 5).astype(int),
        np.ceil(polygon.max(axis=0) + 5).astype(int),
    )
    template = service.save(
        project_id=project_id,
        name=f"{family} synthetic reference",
        content=MeasurementResourceContent(
            kind="localization-template",
            template=dict(
                reference_id=family,
                image_width=1280,
                image_height=800,
                template_roi=(*low.tolist(), *(high - low).tolist()),
                anchor=reference["template_anchor_image_px"],
                image_sha256=hashlib.sha256(encoded).hexdigest(),
            ),
        ),
        image_bytes=encoded,
    )
    # 合成正交相机的已知比例，仅作为工程配方，不能用作真实相机的物理标定。
    scale = 1 / truth["camera"]["pixels_per_mm"]
    calibration = service.save(
        project_id=project_id,
        name=f"{family} SYNTHETIC scale only",
        content=MeasurementResourceContent(
            kind="planar-calibration",
            calibration=PlanarCalibration(
                image_width=1280,
                image_height=800,
                model="similarity",
                world_from_image=(
                    (scale, 0.0, 0.0),
                    (0.0, scale, 0.0),
                    (0.0, 0.0, 1.0),
                ),
                unit="millimeter",
                plane_id="synthetic-orthographic",
                valid_polygon=(
                    (0.0, 0.0),
                    (1279.0, 0.0),
                    (1279.0, 799.0),
                    (0.0, 799.0),
                ),
                fit_rms=0.0,
                validation_max_error=0.0,
            ),
        ),
    )
    pins = [
        dict(
            pin_id=p["pin_id"],
            row_id=p["pin_id"].split("P")[0],
            pin_type="normal",
            center=p["nominal_center_image_px"],
        )
        for p in truth["pins"]
    ]
    layout = dict(
        reference_id=family,
        reference_sha256=template.reference.sha256,
        pins=pins,
        types=[
            dict(
                type_id="normal",
                min_width=12.0,
                max_width=35.0,
                # sRGB 逆变换后的线性强度梯度；固定阈值覆盖开发态的低照度工况。
                gradient_threshold=0.005,
                relative_gradient_threshold=0.2,
            )
        ],
        candidate_bands=[],
    )
    items, rules = [], []
    for pin in pins:
        items.extend(
            [
                dict(
                    item_id="width:" + pin["pin_id"],
                    kind="width",
                    pin_a=pin["pin_id"],
                    section=pin["center"][1],
                ),
                dict(
                    item_id="offset:" + pin["pin_id"],
                    kind="offset",
                    pin_a=pin["pin_id"],
                ),
            ]
        )
        rules.extend(
            [
                dict(
                    item_id="presence:" + pin["pin_id"],
                    unit="unitless",
                    lower=1.0,
                    upper=1.0,
                ),
                dict(
                    item_id="width:" + pin["pin_id"],
                    unit="millimeter",
                    lower=0.59,
                    upper=0.69,
                ),
                dict(
                    item_id="offset:" + pin["pin_id"],
                    unit="millimeter",
                    lower=-0.1,
                    upper=0.1,
                ),
            ]
        )
    for row in sorted({p["row_id"] for p in pins}):
        members = [p for p in pins if p["row_id"] == row]
        positions = np.asarray([p["center"] for p in members])
        layout["candidate_bands"].append(
            dict(
                band_id=row,
                center=positions.mean(axis=0).tolist(),
                length=float(np.ptp(positions[:, 0]) + 60),
                sampling_type="normal",
            )
        )
        for a, b in zip(members, members[1:]):
            for kind, nominal in [("pitch", 2.54), ("gap", 1.90)]:
                identifier = f"{kind}:{a['pin_id']}:{b['pin_id']}"
                items.append(
                    dict(
                        item_id=identifier,
                        kind=kind,
                        pin_a=a["pin_id"],
                        pin_b=b["pin_id"],
                        section=a["center"][1] if kind == "gap" else None,
                    )
                )
                rules.append(
                    dict(
                        item_id=identifier,
                        unit="millimeter",
                        lower=nominal - 0.05,
                        upper=nominal + 0.05,
                    )
                )
        identifier = "total:" + row
        items.append(
            dict(
                item_id=identifier,
                kind="total_pitch",
                pin_a=members[0]["pin_id"],
                pin_b=members[-1]["pin_id"],
            )
        )
        rules.append(
            dict(
                item_id=identifier,
                unit="millimeter",
                lower=(len(members) - 1) * 2.54 - 0.08,
                upper=(len(members) - 1) * 2.54 + 0.08,
            )
        )
    # 壳体外搜索带的背景纹理不同于 PIN 截面，使用独立、固定的最低梯度。
    layout["types"].append(
        dict(layout["types"][0], type_id="outside", gradient_threshold=0.01)
    )
    layout["candidate_bands"].append(
        dict(
            band_id="outside-row",
            center=[640.0, 156.0 if family == "single10_front" else 280.0],
            length=850.0,
            sampling_type="outside",
        )
    )
    rules.extend(
        dict(item_id="extra:" + b["band_id"], unit="unitless", lower=0.0, upper=0.0)
        for b in layout["candidate_bands"]
    )
    nodes = [
        ("input", "core.io.template-input.image", {}, 0, 0),
        (
            "locate",
            "custom.opencv.rigid-locate",
            {"template_resource": template.reference.model_dump(mode="json")},
            320,
            0,
        ),
        (
            "pins",
            "custom.connector.pin-array-locate",
            # Blender Standard 输出为 sRGB；计量边缘使用显式线性化，原图显示不改变。
            {"layout": layout, "pose_mode": "input", "image_encoding": "srgb"},
            650,
            0,
        ),
        (
            "measure",
            "custom.connector.measure",
            {
                "items": items,
                "unit": "millimeter",
                "calibration_resource": calibration.reference.model_dump(mode="json"),
            },
            990,
            0,
        ),
        ("merge", "core.value.numeric-tables-merge", {}, 1300, 0),
        ("limits", "core.rule.check-limits", {"rules": rules}, 1600, 0),
        (
            "draw",
            "custom.opencv.draw-measurements",
            {"allow_empty": True, "font_scale": 0.45},
            1600,
            430,
        ),
        (
            "display",
            "core.io.value-display",
            {
                "title": "Connector checks",
                "fields": [
                    {
                        "path": "state",
                        "label": "Result",
                        "format": "status",
                        "states": {"ok": "#00C896", "ng": "#F04452"},
                    },
                    {
                        "path": "required_count",
                        "label": "Required",
                        "format": "integer",
                    },
                    {"path": "passed_count", "label": "Passed", "format": "integer"},
                ],
            },
            1920,
            0,
        ),
        ("image", "core.io.image-preview", {"title": family}, 2240, 0),
    ]
    connections = [
        ("input", "image", "locate", "image"),
        ("input", "image", "pins", "image"),
        ("locate", "pose", "pins", "pose"),
        ("pins", "pins", "measure", "pins"),
        ("pins", "features", "measure", "features"),
        ("pins", "checks", "merge", "tables"),
        ("measure", "measurements", "merge", "tables"),
        ("merge", "table", "limits", "table"),
        ("limits", "summary", "display", "value"),
        ("input", "image", "draw", "image"),
        ("measure", "annotations", "draw", "measurement"),
        ("draw", "image", "image", "image"),
        ("display", "body", "image", "presentation"),
    ]
    graph = WorkflowGraphTemplate(
        template_id="connector-" + family,
        template_version="0.1.8",
        display_name="Connector Engineering " + family,
        nodes=[
            dict(
                node_id=n,
                node_type_id=t,
                parameters=p,
                ui_state={"position": {"x": x, "y": y}},
            )
            for n, t, p, x, y in nodes
        ],
        edges=[
            dict(
                edge_id=f"e{i}",
                source_node_id=a,
                source_port=b,
                target_node_id=c,
                target_port=d,
            )
            for i, (a, b, c, d) in enumerate(connections)
        ],
        template_inputs=[
            dict(
                input_id="image",
                display_name="Image",
                payload_type_id="image-ref.v1",
                target_node_id="input",
                target_port="payload",
            )
        ],
        template_outputs=[
            dict(
                output_id="result",
                display_name="Result",
                payload_type_id="value.v1",
                source_node_id="limits",
                source_port="summary",
            ),
            dict(
                output_id="image",
                display_name="Image",
                payload_type_id="response-body.v1",
                source_node_id="image",
                source_port="body",
            ),
        ],
        metadata={
            "engineering_only": True,
            "source_family": family,
            "synthetic_calibration": True,
        },
    )
    app = FlowApplication(
        application_id="connector-" + family,
        display_name=graph.display_name,
        template_ref=dict(
            template_id=graph.template_id,
            template_version=graph.template_version,
            source_kind="embedded",
        ),
        bindings=[
            dict(
                binding_id="image",
                direction="input",
                template_port_id="image",
                binding_kind="workflow-execute-input",
                config={"payload_type_id": "image-ref.v1"},
            )
        ]
        + [
            dict(
                binding_id="output_" + o.output_id,
                direction="output",
                template_port_id=o.output_id,
                binding_kind="workflow-execute-output",
                config={"payload_type_id": o.payload_type_id},
            )
            for o in graph.template_outputs
        ],
        metadata={
            "project_id": project_id,
            "app_mode": WorkflowAppModeConfig(
                displays=(
                    WorkflowAppModeDisplay(
                        node_id="image", output_port="body", title=family, size="large"
                    ),
                )
            ).model_dump(mode="json"),
            "engineering_only": True,
        },
    )
    return graph, app, (template, calibration)


def main():
    """全部目标由命令行明确提供，不写入当前客户 App 或发布版本。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--storage-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--project-id", required=True)
    parser.add_argument(
        "--family", choices=["single10_front", "dual08_top"], required=True
    )
    args = parser.parse_args()
    service = MeasurementResourceService(
        LocalDatasetStorage(
            DatasetStorageSettings(root_dir=str(args.storage_root.resolve()))
        )
    )
    graph, app, resources = build_example(
        service, args.assets, project_id=args.project_id, family=args.family
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, value in [("template", graph), ("application", app)]:
        (args.output_dir / f"{args.family}.{name}.json").write_text(
            value.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )
    for resource in resources:
        (args.output_dir / f"{resource.reference.kind}.zip").write_bytes(
            service.export(resource.reference, project_id=args.project_id)
        )
    print(
        json.dumps(
            {
                "output": str(args.output_dir.resolve()),
                "project_id": args.project_id,
                "engineering_only": True,
            }
        )
    )


if __name__ == "__main__":
    main()
