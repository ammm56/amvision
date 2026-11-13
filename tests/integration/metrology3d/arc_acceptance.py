"""B10 完整 S1/S2 发布验收；复用正式工件几何，不重新设计拟圆参数。"""

import argparse
import json
from pathlib import Path

from backend.contracts.workflows.workflow_graph import (
    WorkflowGraphTemplate,
    FlowApplication,
)
from backend.contracts.workflows.measurement3d_evidence import MeasurementEvidence3d
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
    DatasetStorageSettings,
)
from tests.integration.metrology3d.published_support import published_system
from tests.integration.metrology3d.workpiece_workflow import workpiece_documents
from tests.integration.metrology3d import workpiece_recipe as recipe
from tests.integration.metrology3d.representative_workflow import representative_policy
from tests.integration.metrology3d.package_acceptance import serve
from tests.test_metrology3d_arc_measurement import arc_parameters


def documents():
    """原图只取 S1/S2 及其共享基准祖先，输入仍为完整原文件。"""
    template, app = workpiece_documents(file=True, inspection="S1")
    graph = template.model_dump(mode="json")
    wanted = {
        "read",
        "filter",
        "preview",
        "D-crop",
        "D",
        "frame",
        "S1.boundary",
        "S1.circle",
        "S2.boundary",
        "S2.circle",
    }
    graph["nodes"] = [n for n in graph["nodes"] if n["node_id"] in wanted]
    graph["edges"] = [
        e
        for e in graph["edges"]
        if e["source_node_id"] in wanted and e["target_node_id"] in wanted
    ]
    for name in ("S1", "S2"):
        circle = recipe.circle(name)
        selection = circle.selection.model_dump(mode="json")
        selection["feature_id"] = circle.feature_id
        p = arc_parameters(
            union=True,
            selection=selection,
            evaluation=dict(
                kind="feature",
                frame_id=circle.evaluation.frame_id,
                length_unit=circle.evaluation.length_unit,
            ),
            outputs=[
                dict(component=c, item_id=name + "." + c)
                for c in ("coverage_angle", "supported_length")
            ],
        )
        graph["nodes"].append(
            dict(
                node_id=name + ".arc",
                node_type_id="custom.metrology3d.measure-arc",
                parameters=dict(settings=p.model_dump(mode="json")),
            )
        )
        for a, b, c, d in (
            (name + ".circle", "features", name + ".arc", "features"),
            (name + ".arc", "evidence", "preview", "evidence"),
        ):
            graph["edges"].append(
                dict(
                    edge_id=f"arc-{len(graph['edges'])}",
                    source_node_id=a,
                    source_port=b,
                    target_node_id=c,
                    target_port=d,
                )
            )
    graph["nodes"].append(
        dict(
            node_id="http",
            node_type_id="core.output.http-response",
            parameters=dict(status_code=200),
        )
    )
    graph["edges"].append(
        dict(
            edge_id="http-body",
            source_node_id="preview",
            source_port="body",
            target_node_id="http",
            target_port="body",
        )
    )
    graph["template_outputs"] = [
        dict(
            output_id="http_response",
            display_name="Arcs",
            payload_type_id="http-response.v1",
            source_node_id="http",
            source_port="response",
        )
    ]
    application = app.model_dump(mode="json")
    application["bindings"] = [
        b for b in application["bindings"] if b["direction"] == "input"
    ] + [
        dict(
            binding_id="http_response",
            direction="output",
            template_port_id="http_response",
            binding_kind="http-response",
        )
    ]
    application["metadata"]["app_mode"] = dict(
        format_id="amvision.workflow-app-mode.v1",
        title="S1 / S2 圆弧测量",
        displays=[
            dict(
                node_id="preview",
                output_port="body",
                title="圆弧与实测支持",
                size="large",
            )
        ],
    )
    return WorkflowGraphTemplate.model_validate(graph), FlowApplication.model_validate(
        application
    )


def main():
    """隔离目录运行，报告保留全部证据，服务可供真实页面检查。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--sample", type=Path, required=True)
    parser.add_argument("--serve", type=int)
    args = parser.parse_args()
    if args.serve in (5600, 5601):
        parser.error("不能占用业务端口")
    root = args.root.resolve()
    root.mkdir(parents=True, exist_ok=False)
    with published_system(root, point_cloud_policy=representative_policy()) as system:
        storage = LocalDatasetStorage(
            DatasetStorageSettings(root_dir=system.settings.dataset_storage.root_dir)
        )
        with args.sample.open("rb") as stream:
            meta = storage.write_immutable_stream(
                object_prefix="projects/project-1/results/cloud",
                source_stream=stream,
                media_type="application/octet-stream",
                extension="ply",
            ).metadata
        file = dict(
            transport_kind="storage",
            storage_ref="object-store",
            object_key=meta.object_key,
            file_name=args.sample.name,
            media_type=meta.media_type,
            content_length=meta.content_length,
            checksum_algorithm="sha256",
            checksum=meta.checksum,
            immutable_version=meta.immutable_version,
        )
        version = system.publish(documents=documents(), point_limit=100000)
        system.start(version)
        run = system.call(
            "POST",
            f"/app-runtimes/{system.runtime_id}/invoke?response_mode=run",
            json=dict(input_bindings={"cloud": file}, execution_metadata={}),
        )
        assert run["state"] == "succeeded", run
        body = run["outputs"]["http_response"]["body"]
        assert body["source_point_count"] == 14745099
        evidence = MeasurementEvidence3d.model_validate(body["measurements"])
        assert len(evidence.items) == 4
        assert all(i.valid for i in evidence.items), [
            (i.item_id, i.reason) for i in evidence.items
        ]
        system.assert_reclaimed()
        report = dict(
            version=version,
            input_sha256=meta.checksum,
            source_points=body["source_point_count"],
            measurements=evidence.model_dump(mode="json"),
            file=file,
        )
        (root / "acceptance.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (root / "display.json").write_text(
            json.dumps(body, ensure_ascii=False), encoding="utf-8"
        )
        print(json.dumps({i.item_id: i.value for i in evidence.items}), flush=True)
        if args.serve:
            serve(system, root, args.serve)


if __name__ == "__main__":
    main()
