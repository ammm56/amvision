"""B13 完整 S1/S2 已有模型关系与持久支持验收，不改变工件必检集合。"""

import argparse
import json
from math import dist
from pathlib import Path

import numpy as np

from backend.contracts.workflows.workflow_graph import (
    WorkflowGraphTemplate,
    FlowApplication,
)
from backend.service.application.runtime.resource_scope import ResourceScope
from backend.service.application.workflows.point_cloud.runtime import get_cloud_runtime
from backend.service.application.workflows.documents.measurement_resources import (
    MeasurementResourceService,
)
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
    DatasetStorageSettings,
)
from custom_nodes.metrology3d_nodes.shared.cloud_assets import read_asset_bundle
from tests.integration.metrology3d.arc_acceptance import documents as arc_documents
from tests.integration.metrology3d.published_support import published_system
from tests.integration.metrology3d.representative_workflow import representative_policy
from tests.integration.metrology3d.package_acceptance import serve
from tests.integration.metrology3d import workpiece_recipe as recipe
from tests.integration.metrology3d.full_cloud_sample import FILE_SHA, POINTS
from tests.test_metrology3d_relations import parameters


def documents():
    """沿正式工件的两圆拟合；只增加圆心关系、支持保存和证据输出。"""
    template, app = arc_documents()
    graph = template.model_dump(mode="json")
    graph["nodes"] = [n for n in graph["nodes"] if not n["node_id"].endswith(".arc")]
    graph["edges"] = [
        e
        for e in graph["edges"]
        if not e["source_node_id"].endswith(".arc")
        and not e["target_node_id"].endswith(".arc")
    ]
    p = parameters(
        reference=dict(kind="circle-center", feature_id=recipe.circle("S1").feature_id),
        target=dict(kind="circle-center", feature_id=recipe.circle("S2").feature_id),
    )
    p = type(p).model_validate(
        {
            **p.model_dump(),
            "space": dict(
                kind="spatial",
                frame_id=recipe.circle("S1").evaluation.frame_id,
                length_unit="mm",
            ),
        }
    )
    graph["nodes"] += [
        dict(
            node_id="relation",
            node_type_id="custom.metrology3d.measure-relation",
            parameters=dict(settings=p.model_dump(mode="json")),
        ),
        dict(
            node_id="relation-save",
            node_type_id="custom.metrology3d.save-cloud",
            parameters=dict(
                mode="derived", target=dict(kind="new", name="S1-S2 relation")
            ),
        ),
    ]
    for a, b, c, d in (
        ("filter", "cloud", "relation", "cloud"),
        ("S1.circle", "features", "relation", "features"),
        ("S2.circle", "features", "relation", "features"),
        ("relation", "evidence", "preview", "evidence"),
        *(
            ("relation", port, "relation-save", port)
            for port in ("cloud", "features", "evidence")
        ),
    ):
        graph["edges"].append(
            dict(
                edge_id=f"relation-{len(graph['edges'])}",
                source_node_id=a,
                source_port=b,
                target_node_id=c,
                target_port=d,
            )
        )
    app_data = app.model_dump(mode="json")
    app_data["metadata"]["app_mode"]["title"] = "S1 / S2 关系测量"
    return WorkflowGraphTemplate.model_validate(graph), FlowApplication.model_validate(
        app_data
    )


def run(root, sample, *, port=None):
    """原始文件进入正式发布；完整支持读回与独立圆心距离核对。"""
    policy = representative_policy()
    with published_system(root, point_cloud_policy=policy) as system:
        storage = LocalDatasetStorage(
            DatasetStorageSettings(root_dir=system.settings.dataset_storage.root_dir)
        )
        service = MeasurementResourceService(storage, cloud_policy=policy.assets())
        with sample.open("rb") as stream:
            meta = storage.write_immutable_stream(
                object_prefix="projects/project-1/results/cloud",
                source_stream=stream,
                media_type="application/octet-stream",
                extension="ply",
            ).metadata
        assert meta.checksum == FILE_SHA
        file = dict(
            transport_kind="storage",
            storage_ref="object-store",
            object_key=meta.object_key,
            file_name=sample.name,
            media_type=meta.media_type,
            content_length=meta.content_length,
            checksum_algorithm="sha256",
            checksum=meta.checksum,
            immutable_version=meta.immutable_version,
        )
        version = system.publish(documents=documents(), point_limit=100000)
        system.start(version)
        result = system.call(
            "POST",
            f"/app-runtimes/{system.runtime_id}/invoke?response_mode=run",
            json=dict(input_bindings={"cloud": file}, execution_metadata={}),
        )
        assert result["state"] == "succeeded", result
        body = result["outputs"]["http_response"]["body"]
        assert body["source_point_count"] == POINTS
        item = body["measurements"]["items"][0]
        assert item["valid"], item
        expected = dist(
            *(side["feature"]["geometry"]["center"] for side in item["support"])
        )
        assert abs(item["value"] - expected) < 1e-10
        resource = service.list_versions(project_id="project-1")[0].reference
        scope = ResourceScope(kind="acceptance")
        runtime = get_cloud_runtime(
            scope, run_id="relation-restored-full", policy=policy.io
        )
        try:
            cloud, features, evidence = read_asset_bundle(
                runtime,
                resource,
                service=service,
                project_id="project-1",
                policy=policy.assets(),
                cancel=lambda: None,
            )
            assert runtime.source_point_count(cloud) == POINTS
            assert len(features.items) == 2
            assert abs(evidence.items[0].value - expected) < 1e-10
            assert {f.support.observation_id for f in features.items} == {
                cloud.observation_id
            }
            assert all(f.support.vertex_kind == "generated" for f in features.items)
            assert not np.isnan(evidence.items[0].value)
        finally:
            assert not scope.close() and runtime.budget.used == 0
        system.assert_reclaimed()
        report = dict(
            version=version,
            source_points=POINTS,
            input_sha256=meta.checksum,
            value=item["value"],
            resource=resource.model_dump(mode="json"),
            file=file,
        )
        (root / "acceptance.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (root / "display.json").write_text(
            json.dumps(body, ensure_ascii=False), encoding="utf-8"
        )
        print(json.dumps(report, ensure_ascii=False), flush=True)
        if port:
            serve(system, root, port)
        return report


def main():
    """仅隔离环境，禁止使用业务端口。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--sample", type=Path, required=True)
    parser.add_argument("--serve", type=int)
    args = parser.parse_args()
    if args.serve in (5600, 5601):
        parser.error("不能占用业务端口")
    args.root.mkdir(parents=True, exist_ok=False)
    run(args.root.resolve(), args.sample, port=args.serve)


if __name__ == "__main__":
    main()
