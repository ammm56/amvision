"""B13 完整原云的点身份与量值链路；不冒充节点发布或实体精度验收。"""

from hashlib import sha256
from math import dist
from pathlib import Path

import numpy as np
import pytest

from backend.service.application.runtime.resource_scope import ResourceScope
from backend.service.application.workflows.point_cloud.runtime import get_cloud_runtime
from custom_nodes.metrology3d_nodes.shared.io.read_file import read_file_reference
from custom_nodes.metrology3d_nodes.shared.relation_runtime import measure_relation
from custom_nodes.metrology3d_nodes.shared.relation_result import relation_evidence
from backend.contracts.workflows.measurement3d_evidence import MeasurementEvidence3d
from tests.integration.metrology3d.full_cloud_sample import ARRAY_SHA, FILE_SHA, POINTS
from tests.point_cloud_support import create_resource_service, options, policy
from tests.test_metrology3d_relations import parameters


def test_relation_complete_source_rows_and_cleanup(tmp_path, request):
    """完整读取、逐块校验，然后用不同原始行号计算，不使用显示采样。"""
    supplied = request.config.getoption("--cloud-sample")
    if not supplied:
        pytest.skip("完整原云必须显式提供 --cloud-sample")
    service = create_resource_service(tmp_path)
    with Path(supplied).open("rb") as stream:
        meta = service.storage.write_immutable_stream(
            object_prefix="projects/test/results/cloud",
            source_stream=stream,
            media_type="application/octet-stream",
            extension="ply",
        ).metadata
    assert meta.checksum == FILE_SHA
    file = dict(
        transport_kind="storage",
        storage_ref="object-store",
        object_key=meta.object_key,
        file_name="sample.ply",
        media_type=meta.media_type,
        content_length=meta.content_length,
        checksum_algorithm="sha256",
        checksum=meta.checksum,
        immutable_version=meta.immutable_version,
    )
    limits = policy(
        max_header_bytes=65536,
        max_decoded_bytes=400000000,
        max_working_bytes=134217728,
        chunk_rows=65536,
        chunk_bytes=4194304,
        max_live_array_bytes=800000000,
    )
    scope = ResourceScope(kind="workflow")
    runtime = get_cloud_runtime(scope, run_id="b13-full-sample", policy=limits)
    try:
        cloud = read_file_reference(
            runtime=runtime,
            object_store=service.storage,
            project_id="test",
            file=file,
            options=options(),
            cancel=lambda: None,
        )
        assert cloud.point_count == POINTS
        digest = sha256()
        first = last = None
        with runtime.borrow(cloud) as view:
            for start in range(0, POINTS, limits.chunk_rows):
                block = view.chunk(start, min(start + limits.chunk_rows, POINTS))[
                    "positions"
                ]
                assert block.dtype == np.dtype("float32")
                digest.update(block.tobytes())
                rows = np.flatnonzero(np.isfinite(block).all(axis=1))
                if len(rows):
                    if first is None:
                        first = (
                            start + int(rows[0]),
                            tuple(float(x) for x in block[rows[0]]),
                        )
                    last = (
                        start + int(rows[-1]),
                        tuple(float(x) for x in block[rows[-1]]),
                    )
                block = rows = None
        assert digest.hexdigest() == ARRAY_SHA
        assert first[0] < last[0]
        p = parameters(
            reference=dict(kind="source-point", source_index=first[0]),
            target=dict(kind="source-point", source_index=last[0]),
        )
        before = runtime.budget.used
        result = measure_relation(runtime, cloud, [], p, cancel=lambda: None)
        assert result.value == pytest.approx(dist(first[1], last[1]), rel=1e-13)
        assert result.reference.point.source_index == first[0]
        assert result.target.point.source_index == last[0]
        assert runtime.budget.used == before
        evidence = relation_evidence(runtime, cloud, [], p, cancel=lambda: None)
        restored = MeasurementEvidence3d.model_validate_json(evidence.model_dump_json())
        assert restored.numeric_table().items[0].value == result.value
        assert restored.items[0].support[0].point.source_index == first[0]
        assert restored.items[0].support[1].point.source_index == last[0]
        assert all(
            side.source_point_count == POINTS for side in restored.items[0].support
        )
        assert runtime.budget.used == before
    finally:
        assert scope.close() == () and runtime.budget.used == 0
