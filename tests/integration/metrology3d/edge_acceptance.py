"""完整工件公开边诊断验收，复用已经审计的显式配置和正式发布系统。"""

import argparse
import json
from pathlib import Path

from backend.contracts.workflows.workflow_graph import WorkflowGraphTemplate
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
    DatasetStorageSettings,
)
from tests.integration.metrology3d.published_support import published_system
from tests.integration.metrology3d.test_edge_published import documents
from tests.integration.metrology3d.representative_workflow import representative_policy
from tests.integration.metrology3d.representative_recipe import boxes
from tests.integration.metrology3d.workpiece_recipe import STEEL
from tests.test_metrology3d_height_map import parameters
from tests.integration.metrology3d.package_acceptance import serve


def main():
    """不修改业务库；必须显式给出前序逐行核对生成的配置报告。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--sample", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--serve", type=int)
    args = parser.parse_args()
    if args.serve is not None and (
        args.serve in (5600, 5601) or not 1024 <= args.serve <= 65535
    ):
        parser.error("必须使用隔离端口")
    root = args.root.resolve()
    root.mkdir(parents=True, exist_ok=False)
    evidence = json.loads(args.evidence.read_text(encoding="utf-8"))
    grid = parameters("median").model_dump(mode="json")
    grid.update(width=40, height=44)
    grid["grid"].update(origin=[-38, -24, 0], column_step=0.25, row_step=0.25)
    settings = dict(
        feature_id="A_top_L-edge",
        evaluation=dict(kind="height-map", frame_id="fixture", length_unit="mm"),
        method=dict(
            kind="height-jump",
            candidates=evidence["settings"],
            pairing=evidence["pairing"],
            chains=evidence["chain_settings"],
        ),
        selection=evidence["target_parameters"],
    )
    template, app = documents(settings, grid, file=True)
    graph = template.model_dump(mode="json")
    region = boxes("edge-steel", [[*STEEL["A_top_L"][3], -30, 0]])
    root_roi = next(roi for roi in region.rois if roi.roi_id == region.roi_id)
    graph["nodes"].append(
        dict(
            node_id="crop",
            node_type_id="custom.metrology3d.crop-roi",
            parameters=dict(
                source=dict(
                    kind="parameters",
                    roi=root_roi.model_dump(mode="json"),
                    bounds=[
                        roi.model_dump(mode="json")
                        for roi in region.rois
                        if roi.roi_id != region.roi_id
                    ],
                )
            ),
        )
    )
    for edge in graph["edges"]:
        if edge["target_node_id"] == "height":
            edge["source_node_id"] = "crop"
    graph["edges"].append(
        dict(
            edge_id="to-crop",
            source_node_id="filter",
            source_port="cloud",
            target_node_id="crop",
            target_port="cloud",
        )
    )
    with published_system(root, point_cloud_policy=representative_policy()) as system:
        storage = LocalDatasetStorage(
            DatasetStorageSettings(root_dir=system.settings.dataset_storage.root_dir)
        )
        with args.sample.open("rb") as stream:
            metadata = storage.write_immutable_stream(
                object_prefix="projects/project-1/results/cloud",
                source_stream=stream,
                media_type="application/octet-stream",
                extension="ply",
            ).metadata
        file = dict(
            transport_kind="storage",
            storage_ref="object-store",
            object_key=metadata.object_key,
            file_name=args.sample.name,
            media_type=metadata.media_type,
            content_length=metadata.content_length,
            checksum_algorithm="sha256",
            checksum=metadata.checksum,
            immutable_version=metadata.immutable_version,
        )
        version = system.publish(
            point_limit=100000,
            documents=(WorkflowGraphTemplate.model_validate(graph), app),
        )
        system.start(version)
        run = system.call(
            "POST",
            f"/app-runtimes/{system.runtime_id}/invoke",
            json=dict(input_bindings={"cloud": file}, execution_metadata={}),
        )
        assert run["state"] == "succeeded", run
        body = run["results"]["body"]
        diagnostic = body["edge_diagnostics"]
        assert diagnostic["state"] == "ready", diagnostic
        assert body["source_point_count"] == evidence["source_count"]
        assert diagnostic["edge"]["pair_count"] == evidence["pair_count"]
        assert [r["reason"] for r in diagnostic["edge"]["reports"]] == [
            r["reason"] for r in evidence["targets"]
        ]
        system.assert_reclaimed()
        report = dict(
            version=version,
            source_points=body["source_point_count"],
            input_points=body["point_count"],
            display_points=body["display_point_count"],
            pair_count=diagnostic["edge"]["pair_count"],
            records=diagnostic["edge"]["record_count"],
            targets=[
                dict(target_id=r["target_id"], reason=r["reason"])
                for r in diagnostic["edge"]["reports"]
            ],
            data_sha256=diagnostic["data"]["checksum"],
        )
        (root / "acceptance.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )
        print(json.dumps(report), flush=True)
        if args.serve:
            serve(system, root, args.serve)


if __name__ == "__main__":
    main()
