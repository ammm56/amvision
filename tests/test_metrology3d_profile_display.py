"""轮廓概览与原始细节保留实际采集身份，生成点不冒充原样点。"""

import numpy as np
import pytest

from backend.contracts.workflows.point_cloud_runtime import FilterCloudValid
from backend.service.application.runtime.resource_scope import ResourceScope
from backend.service.application.workflows.point_cloud.runtime import get_cloud_runtime
from backend.service.application.workflows.point_cloud.detail_index import (
    prepare_index,
    read_block,
)
from custom_nodes.metrology3d_nodes.shared.preview import build_cloud_preview
from custom_nodes.metrology3d_nodes.shared.filter_valid import filter_valid
from custom_nodes.metrology3d_nodes.shared.cloud_assets import save_cloud, read_asset
from custom_nodes.metrology3d_nodes.shared.resample import resample_cloud
from tests.test_metrology3d_profile_runtime import source
from tests.test_metrology3d_resample import parameters
from tests.test_metrology3d_preview import decode
from tests.point_cloud_support import create_resource_service
from tests.test_point_cloud_details import detail_policy


@pytest.mark.parametrize("generated", [False, True])
def test_profile_preview_and_saved_details(tmp_path, generated):
    policy = detail_policy()
    policy = policy.model_copy(
        update={"preview": policy.preview.model_copy(update={"max_points": 6})}
    )
    service = create_resource_service(tmp_path)
    scope = ResourceScope(kind="profile-display")
    runtime = get_cloud_runtime(scope, run_id="display", policy=policy.io)
    try:
        cloud, _ = source(runtime, service, entry="array", method="encoder-positions")
        cloud, _ = filter_valid(
            runtime,
            cloud,
            FilterCloudValid(finite_fields=("positions",), sentinels=()),
            cancel=lambda: None,
        )
        if generated:
            params = parameters("voxel-centroid")
            params = params.model_copy(
                update={
                    "settings": params.settings.model_copy(
                        update={"frame_id": cloud.spatial.frame_id}
                    )
                }
            )
            cloud, _ = resample_cloud(runtime, cloud, params, cancel=lambda: None)
        saved = save_cloud(
            runtime,
            cloud,
            service=service,
            project_id="test",
            name="Profiles",
            mode="derived",
            write_identity="1" * 64,
            policy=policy.assets(),
            cancel=lambda: None,
        )
        cloud = read_asset(
            runtime,
            saved,
            service=service,
            project_id="test",
            policy=policy.assets(),
            cancel=lambda: None,
        )
        body = build_cloud_preview(
            runtime,
            cloud,
            {"point_limit": 6, "color": {"mode": "solid"}},
            policy=policy.preview,
            cancel=lambda: None,
        )
        assert body["profile_source"]["profile_count"] == 4
        assert body["profile_source"]["point_count"] == body["source_point_count"] == 6
        assert body["profile_empty_count"] == 1
        assert "file" not in body["profile_source"]
        points = decode(body)
        assert ("acquisition_line_id" in points) is not generated
        if not generated:
            with runtime.borrow(cloud) as view:
                for name in ("acquisition_line_id", "profile_sample_index"):
                    expected = np.concatenate(
                        [
                            view.chunk(
                                start,
                                min(start + policy.io.chunk_rows, cloud.point_count),
                            )[name].copy()
                            for start in range(
                                0, cloud.point_count, policy.io.chunk_rows
                            )
                        ]
                    )
                    np.testing.assert_array_equal(points[name], expected)
            raw = None
        index = prepare_index(
            runtime,
            cloud,
            service=service,
            project_id="test",
            policy=policy,
            cancel=lambda: None,
        )
        assert index.profile_records is not generated
        if not generated:
            fields = {f.name: f for f in index.fields}
            seen = []
            for block in index.blocks:
                raw = read_block(
                    service,
                    index.source,
                    block.block_id,
                    generation=index.generation,
                    project_id="test",
                    policy=policy.preview,
                )
                lines = np.ndarray(
                    (block.count,),
                    dtype="<u8",
                    buffer=raw,
                    offset=fields["acquisition_line_id"].offset,
                    strides=(index.row_bytes,),
                )
                seen.extend(lines.tolist())
            assert sorted(seen) == sorted(points["acquisition_line_id"][:, 0].tolist())
    finally:
        assert not scope.close()
        assert runtime.budget.used == 0
