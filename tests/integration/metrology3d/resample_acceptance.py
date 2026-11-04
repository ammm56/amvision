"""完整工件三方法的真实发布及可选页面验收，复用现有隔离系统。"""

import argparse
import json
from pathlib import Path

from backend.contracts.workflows.workflow_graph import (
    WorkflowGraphTemplate,
    FlowApplication,
)
from backend.service.application.workflows.documents.measurement_resources import (
    MeasurementResourceService,
)
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
    DatasetStorageSettings,
)
from tests.integration.metrology3d.capacity_support import settings
from tests.integration.metrology3d.detail_acceptance import documents, save_sample
from tests.integration.metrology3d.package_acceptance import serve
from tests.integration.metrology3d.published_support import published_system
from tests.integration.metrology3d.resample_documents import resample_documents


def main():
    """只在新隔离目录保存原云；通过真实草稿/发布/worker 执行各方法。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--sample", type=Path, required=True)
    parser.add_argument("--serve", type=int)
    args = parser.parse_args()
    if args.serve is not None and (
        args.serve in (5600, 5601) or not 1024 <= args.serve <= 65535
    ):
        parser.error("必须使用隔离端口")
    args.root.mkdir(parents=True, exist_ok=False)
    policy = settings().workflow_runtime.point_cloud
    report = []
    with published_system(args.root / "system", point_cloud_policy=policy) as system:
        service = MeasurementResourceService(
            LocalDatasetStorage(
                DatasetStorageSettings(
                    root_dir=system.settings.dataset_storage.root_dir
                )
            )
        )
        reference = save_sample(service, args.sample, policy)
        for kind in ("stride", "voxel-representative", "voxel-centroid"):
            template, app = documents(reference)
            graph = template.model_dump(mode="json")
            sample_template, sample_app = resample_documents(kind)
            graph["nodes"] = [n for n in graph["nodes"] if n["node_id"] != "response"]
            graph["edges"] = [e for e in graph["edges"] if e["edge_id"] != "response"]
            graph["template_outputs"] = [
                p.model_dump(mode="json") for p in sample_template.template_outputs
            ]
            app = FlowApplication.model_validate(
                {
                    **app.model_dump(mode="json"),
                    "bindings": [
                        b.model_dump(mode="json")
                        for b in sample_app.bindings
                        if b.direction == "output"
                    ],
                }
            )
            node = next(
                n
                for n in sample_template.nodes
                if n.node_type_id.endswith("resample-cloud")
            )
            graph["nodes"].append(node.model_dump(mode="json"))
            graph["edges"][0]["source_node_id"] = node.node_id
            graph["edges"].append(
                dict(
                    edge_id="sample-input",
                    source_node_id="read",
                    source_port="cloud",
                    target_node_id=node.node_id,
                    target_port="cloud",
                )
            )
            graph["nodes"].append(
                dict(
                    node_id="input-preview",
                    node_type_id="custom.metrology3d.cloud-preview",
                    parameters=dict(
                        point_limit=100000,
                        color=dict(mode="solid"),
                        prepare_details=False,
                    ),
                )
            )
            graph["edges"].append(
                dict(
                    edge_id="input-display",
                    source_node_id="read",
                    source_port="cloud",
                    target_node_id="input-preview",
                    target_port="cloud",
                )
            )
            graph["template_outputs"].append(
                dict(
                    output_id="input_view",
                    display_name="Original cloud",
                    payload_type_id="response-body.v1",
                    source_node_id="input-preview",
                    source_port="body",
                )
            )
            app = FlowApplication.model_validate(
                {
                    **app.model_dump(mode="json"),
                    "bindings": [
                        *(b.model_dump(mode="json") for b in app.bindings),
                        dict(
                            binding_id="input_view",
                            direction="output",
                            template_port_id="input_view",
                            binding_kind="http-response",
                        ),
                    ],
                }
            )
            next(n for n in graph["nodes"] if n["node_id"] == "preview")["parameters"][
                "prepare_details"
            ] = False
            version = system.publish(
                point_limit=100000,
                documents=(WorkflowGraphTemplate.model_validate(graph), app),
            )
            if system.runtime_id is not None:
                stopped = system.call("GET", f"/app-runtimes/{system.runtime_id}")
                system.call(
                    "POST",
                    f"/app-runtimes/{system.runtime_id}/select-version",
                    json=dict(
                        workflow_app_version_id=version,
                        expected_generation=stopped["revision_generation"],
                    ),
                )
            system.start(version)
            response = system.call(
                "POST",
                f"/app-runtimes/{system.runtime_id}/invoke",
                json=dict(
                    input_bindings={},
                    execution_metadata={"workflow_run_record_mode": "full"},
                ),
            )
            assert response["state"] == "succeeded", response
            body = response["results"]["body"]
            assert body["point_count"] == (4915033 if kind == "stride" else 16912)
            system.assert_reclaimed()
            report.append(
                dict(
                    kind=kind,
                    version=version,
                    runtime_id=system.runtime_id,
                    run_id=response.get("workflow_run_id"),
                    point_count=body["point_count"],
                )
            )
            print(json.dumps(report[-1]), flush=True)
            system.call("POST", f"/app-runtimes/{system.runtime_id}/stop")
        (args.root / "report.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )
        if args.serve:
            serve(system, args.root, args.serve)


if __name__ == "__main__":
    main()
