"""完整工件刚性真值对照与真实发布；隔离预算明确区别生产配置。"""

import argparse
from hashlib import sha256
import json
from pathlib import Path
from time import perf_counter

import numpy as np
from scipy.spatial.transform import Rotation

from backend.contracts.workflows.point_cloud import CloudField
from backend.contracts.workflows.point_cloud_runtime import CloudLocalSource
from backend.service.application.runtime.resource_scope import ResourceScope
from backend.service.application.workflows.point_cloud.runtime import get_cloud_runtime
from backend.service.application.workflows.documents.measurement_resources import (
    MeasurementResourceService,
)
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
    DatasetStorageSettings,
)
from custom_nodes.metrology3d_nodes.shared.cloud_assets import read_asset, save_cloud
from tests.test_point_cloud_runtime import own
from tests.test_metrology3d_registration import settings as registration_settings
from tests.integration.metrology3d.capacity_support import settings
from tests.integration.metrology3d.detail_acceptance import save_sample
from tests.integration.metrology3d.registration_documents import registration_documents
from tests.integration.metrology3d.published_support import published_system
from tests.integration.metrology3d.package_acceptance import serve


def prepare_reference(service, source_asset, policy):
    """外部真值按固定公式生成完整参考，算法未参与参考数据生成。"""
    scope = ResourceScope(kind="workflow")
    runtime = get_cloud_runtime(scope, run_id="reference-preparation", policy=policy.io)
    try:
        source = read_asset(
            runtime,
            source_asset,
            service=service,
            project_id="project-1",
            policy=policy.assets(),
            cancel=lambda: None,
        )
        assert source.point_count == 14745099
        rotation = Rotation.from_euler("xyz", [2, -1, 3], degrees=True).as_matrix()
        translation = np.array([0.1, -0.12, 0.08])
        values = np.empty((source.point_count, 3), dtype="f8")
        digest = sha256()
        with runtime.borrow(source) as view:
            for start in range(0, source.point_count, policy.io.chunk_rows):
                stop = min(start + policy.io.chunk_rows, source.point_count)
                points = view.chunk(start, stop)["positions"]
                np.testing.assert_array_equal(
                    view.source_indices(start, stop), np.arange(start, stop)
                )
                values[start:stop] = points.astype("f8") @ rotation.T + translation
                digest.update(memoryview(values[start:stop]).cast("B"))
        reference = runtime.register_source(
            owner=own(runtime, dict(positions=values)),
            point_count=len(values),
            fields=(
                CloudField(
                    name="positions",
                    semantic="position",
                    dtype="float64",
                    components=3,
                    unit=None,
                ),
            ),
            spatial=source.spatial.model_copy(update={"frame_id": "reference"}),
            source=CloudLocalSource(
                kind="local-array",
                content_sha256=digest.hexdigest(),
                descriptor_sha256=sha256(
                    b"B04 explicit XYZ float64 SE3 reference"
                ).hexdigest(),
                source_observation_id=None,
            ),
            source_metadata=None,
            cancel=lambda: None,
        )
        return save_cloud(
            runtime,
            reference,
            service=service,
            project_id="project-1",
            name="B04 reference",
            mode="derived",
            write_identity="b" * 64,
            policy=policy.assets(),
            cancel=lambda: None,
        )
    finally:
        assert scope.close() == () and runtime.budget.used == 0


def main():
    """全量核验没有隐式采样；仅显示 100000 点，配准使用所有 14745099 点。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--sample", type=Path, required=True)
    parser.add_argument("--serve", type=int)
    parser.add_argument("--registration-stride", type=int)
    args = parser.parse_args()
    if args.registration_stride is not None and args.registration_stride < 1:
        parser.error("配准支路步长必须显式为正整数")
    if args.serve is not None and (
        args.serve in (5600, 5601) or not 1024 <= args.serve <= 65535
    ):
        parser.error("必须使用隔离端口")
    args.root.mkdir(parents=True, exist_ok=False)
    policy = settings().workflow_runtime.point_cloud
    # 双云全量原生索引按保守预留超过工程 4GiB；只增加本轮明确测试预算。
    raw = policy.model_dump()
    raw["io"].update(
        max_working_bytes=(16 if args.registration_stride is None else 4) * 1024**3,
        max_live_array_bytes=2 * 1024**3,
    )
    policy = type(policy).model_validate(raw)
    with published_system(args.root / "system", point_cloud_policy=policy) as system:
        service = MeasurementResourceService(
            LocalDatasetStorage(
                DatasetStorageSettings(
                    root_dir=system.settings.dataset_storage.root_dir
                )
            )
        )
        asset = save_sample(service, args.sample, policy)
        reference = prepare_reference(service, asset, policy)
        # 密集实测云使用已知精确初值做全量链路核验；偏差恢复由独立椭球回归验证。
        p = registration_settings(
            initial_translation=[0.1, -0.12, 0.08],
            initial_rotation_degrees=[2, -1, 3],
            max_iterations=10,
            max_correspondence_distance=0.0001,
        )
        docs = registration_documents(
            assets=(asset, reference),
            parameters=p,
            registration_stride=args.registration_stride,
        )
        version = system.publish(point_limit=100000, documents=docs)
        system.start(version)
        started = perf_counter()
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
        frame = body["geometry"]["frame"]
        assert body["point_count"] == 14745099 and frame["state"] == "found", frame
        expected = np.eye(4)
        expected[:3, :3] = Rotation.from_euler(
            "xyz", [2, -1, 3], degrees=True
        ).as_matrix()
        expected[:3, 3] = [0.1, -0.12, 0.08]
        matrix_error = float(
            np.max(np.abs(np.asarray(frame["transform"]["matrix"]) - expected))
        )
        assert matrix_error < 1e-6
        result = dict(
            point_count=body["point_count"],
            matrix_error=matrix_error,
            published_seconds=perf_counter() - started,
            quality=frame["quality"],
            version=version,
            runtime_id=system.runtime_id,
            test_working_bytes=policy.io.max_working_bytes,
            registration_stride=args.registration_stride,
        )
        system.assert_reclaimed()
        system.call("POST", f"/app-runtimes/{system.runtime_id}/stop")
        (args.root / "report.json").write_text(
            json.dumps(result, indent=2), encoding="utf-8"
        )
        print(json.dumps(result), flush=True)
        if args.serve:
            serve(system, args.root, args.serve)


if __name__ == "__main__":
    main()
