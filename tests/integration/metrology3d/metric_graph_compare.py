"""完整样本实际邻域的局部构图对照，不把重复计算计入正式节拍。"""

import argparse
from hashlib import file_digest
import json
from pathlib import Path
from time import perf_counter

import numpy as np
from scipy.spatial import cKDTree
from scipy.sparse import coo_array, csr_array
from scipy.sparse.csgraph import connected_components
from pytest import MonkeyPatch

from backend.service.application.runtime.resource_scope import (
    WORKFLOW_RESOURCE_SCOPE_METADATA_KEY,
)
from backend.service.application.workflows.graph_executor import WorkflowGraphExecutor
from backend.service.application.workflows.service_runtime.context import (
    WorkflowServiceNodeRuntimeContext,
)
from custom_nodes.metrology3d_nodes.shared import envelope_grid
from tests.integration.metrology3d.compute_profile import numerical_graph
from tests.integration.metrology3d.representative_workflow import representative_policy
from tests.integration.metrology3d.test_measurement_output import measurement_registry
from tests.integration.metrology3d.test_transport_full_sample import ARRAY_SHA, POINTS
from tests.integration.metrology3d.workpiece_workflow import (
    workpiece_documents,
    check_workpiece_body,
)
from tests.test_metrology3d_preprocess import make_cloud


def compare(points, radius):
    """保留所有邻接关系；比较包含计数、查询和 CSR 转换的墙钟。"""
    records, expected = [], None
    for mode in ("pairs", "rows", "sparse", "csr", "csr-leaf8", "csr-leaf32", "csr-leaf64"):
        started = perf_counter()
        leafsize = int(mode.split("leaf")[-1]) if "leaf" in mode else 16
        tree = cKDTree(points, copy_data=False, leafsize=leafsize)
        count = len(points)
        pair_count = (int(tree.count_neighbors(tree, radius)) - count) // 2
        if mode == "pairs" or mode.startswith("csr"):
            pairs = tree.query_pairs(radius, eps=0, output_type="ndarray")
            if mode == "pairs":
                graph = coo_array(
                    (np.ones(len(pairs), dtype=np.uint8), (pairs[:, 0], pairs[:, 1])),
                    shape=(count, count),
                ).tocsr()
            else:
                order = np.argsort(pairs[:, 0], kind="stable")
                indptr = np.r_[0, np.cumsum(np.bincount(pairs[:, 0], minlength=count))]
                graph = csr_array(
                    (np.ones(len(pairs), dtype=np.uint8), pairs[order, 1], indptr),
                    shape=(count, count),
                )
        elif mode == "rows":
            lengths = tree.query_ball_point(points, radius, eps=0, return_length=True)
            indptr = np.r_[0, np.cumsum(lengths)]
            indices = np.empty(indptr[-1], dtype=np.int64)
            for start in range(0, count, 2048):
                stop = min(count, start + 2048)
                neighbors = tree.query_ball_point(
                    points[start:stop], radius, eps=0, return_sorted=False
                )
                indices[indptr[start] : indptr[stop]] = np.concatenate(neighbors)
            graph = csr_array(
                (np.ones(len(indices), dtype=np.uint8), indices, indptr),
                shape=(count, count),
            )
        else:
            graph = tree.sparse_distance_matrix(
                tree, radius, output_type="coo_matrix"
            ).tocsr()
            graph.data[:] = 1
        components, labels = connected_components(graph, directed=False)
        elapsed = perf_counter() - started
        if mode == "pairs" or mode.startswith("csr"):
            graph = graph + graph.T
            graph.setdiag(1)
        graph.sort_indices()
        assert graph.nnz == pair_count * 2 + count
        if expected is None:
            expected = graph, labels
        else:
            assert (graph != expected[0]).nnz == 0
            np.testing.assert_array_equal(labels, expected[1])
        records.append(
            dict(
                method=mode,
                points=count,
                pairs=pair_count,
                components=components,
                seconds=elapsed,
            )
        )
    return records


def main():
    """只复用已严格解析且摘要吻合的临时数组，不能用于正式输入验收。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("binary", type=Path)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    with args.binary.open("rb") as stream:
        assert file_digest(stream, "sha256").hexdigest() == ARRAY_SHA
    points = np.memmap(args.binary, dtype="<f4", mode="r", shape=(POINTS, 3))
    policy = representative_policy()
    scope, runtime, cloud = make_cloud(
        unit="mm", coordinates=points, runtime_policy=policy.io
    )
    original, reports = envelope_grid.metric_membership, []

    def measured(uvh, settings, **kwargs):
        result = original(uvh, settings, **kwargs)
        if not reports:
            positive = (
                uvh[:, 2] > 0
                if settings.profiles.foreground == "above"
                else uvh[:, 2] < 0
            )
            reports.extend(
                compare(
                    np.ascontiguousarray(uvh[positive, :2]),
                    settings.selection.connection_distance,
                )
            )
        return result

    try:
        with MonkeyPatch.context() as patch:
            patch.setattr(envelope_grid, "metric_membership", measured)
            result = WorkflowGraphExecutor(registry=measurement_registry()).execute(
                template=numerical_graph(workpiece_documents(visible=True)[0]),
                input_values={"input": cloud.model_dump(mode="json")},
                execution_metadata={
                    "project_id": "test",
                    "workflow_run_id": runtime.run_id,
                    WORKFLOW_RESOURCE_SCOPE_METADATA_KEY: scope,
                },
                runtime_context=WorkflowServiceNodeRuntimeContext(
                    session_factory=None,
                    dataset_storage=None,
                    point_cloud_policy=policy,
                ),
            )
            check_workpiece_body(
                result.outputs["body"],
                matrix=Path(__file__).parents[3]
                / "docs/development/assets/r5-f4/workpiece-windows.json",
            )
    finally:
        assert not scope.close() and runtime.budget.used == 0
    args.report.write_text(json.dumps(reports, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
