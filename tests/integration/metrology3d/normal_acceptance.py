"""完整样本 B02 -> B03 三种邻域的正式发布、切版与页面验收。"""

import argparse
import json
from pathlib import Path

import numpy as np

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
from tests.integration.metrology3d.detail_acceptance import save_sample
from tests.integration.metrology3d.normal_documents import normal_documents
from tests.integration.metrology3d.resample_documents import resample_documents
from tests.integration.metrology3d.package_acceptance import serve
from tests.integration.metrology3d.published_support import published_system
from tests.integration.metrology3d.test_normals_full_sample import sample_parameters
from tests.test_metrology3d_preview import decode


def documents(reference, kind, *, original=False):
    """显式区分完整原云与 1 mm 质心法向，不替代原工件尺寸配方。"""
    template, app = normal_documents(
        kind, settings=sample_parameters(kind, coarse=not original)
    )
    graph = template.model_dump(mode="json")
    next(n for n in graph["nodes"] if n["node_id"] == "read")["parameters"] = dict(
        source=dict(kind="asset", reference=reference.model_dump(mode="json"))
    )
    if not original:
        resample, _ = resample_documents("voxel-centroid")
        graph["nodes"].append(
            next(
                n
                for n in resample.model_dump(mode="json")["nodes"]
                if n["node_id"] == "resample"
            )
        )
        next(e for e in graph["edges"] if e["edge_id"] == "normal-input")[
            "source_node_id"
        ] = "resample"
        graph["edges"].append(
            dict(
                edge_id="sample-input",
                source_node_id="filter",
                source_port="cloud",
                target_node_id="resample",
                target_port="cloud",
            )
        )
    graph["template_inputs"] = []
    graph["template_outputs"].append(
        dict(
            output_id="summary",
            display_name="Normals",
            payload_type_id="value.v1",
            source_node_id="normals",
            source_port="summary",
        )
    )
    raw = app.model_dump(mode="json")
    raw["bindings"] = [b for b in raw["bindings"] if b["direction"] == "output"]
    raw["bindings"].append(
        dict(
            binding_id="summary",
            direction="output",
            template_port_id="summary",
            binding_kind="http-response",
        )
    )
    return WorkflowGraphTemplate.model_validate(graph), FlowApplication.model_validate(
        raw
    )


def main():
    """测试服务限定隔离端口，存储和依赖不进入业务实例。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--sample", type=Path, required=True)
    parser.add_argument("--serve", type=int)
    parser.add_argument("--original", action="store_true")
    args = parser.parse_args()
    if args.serve is not None and (
        args.serve in (5600, 5601) or not 1024 <= args.serve <= 65535
    ):
        parser.error("必须使用隔离端口")
    args.root.mkdir(parents=True, exist_ok=False)
    policy = settings().workflow_runtime.point_cloud
    if args.original:
        policy = policy.model_copy(
            update={
                "io": policy.io.model_copy(
                    update={
                        "max_working_bytes": 8 * 1024**3,
                        "max_live_array_bytes": 2 * 1024**3,
                    }
                )
            }
        )
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
        for kind in ("knn",) if args.original else ("knn", "radius", "hybrid"):
            version = system.publish(
                point_limit=100000,
                documents=documents(reference, kind, original=args.original),
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
            run = system.call(
                "POST",
                f"/app-runtimes/{system.runtime_id}/invoke",
                json=dict(
                    input_bindings={},
                    execution_metadata={"workflow_run_record_mode": "full"},
                ),
            )
            assert run["state"] == "succeeded", run
            body = run["results"]["body"]
            arrays = decode(body)
            assert body["point_count"] == (14745099 if args.original else 16912)
            if not args.original:
                assert body["lineage_kind"] == "voxel-aggregate"
            valid = int(np.count_nonzero(arrays["normal_valid"]))
            assert valid > 0
            assert (
                body["normal_info"]["method"]["parameters"]["neighborhood"]["kind"]
                == kind
            )
            report.append(
                dict(
                    kind=kind,
                    original=args.original,
                    version=version,
                    point_count=body["point_count"],
                    valid_count=valid,
                    summary=run["results"]["summary"],
                )
            )
            print(json.dumps(report[-1]), flush=True)
            system.assert_reclaimed()
            system.call("POST", f"/app-runtimes/{system.runtime_id}/stop")
        (args.root / "report.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )
        if args.serve:
            serve(system, args.root, args.serve)


if __name__ == "__main__":
    main()
