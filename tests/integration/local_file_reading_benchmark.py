"""通过真实 WorkflowGraphExecutor 验证 1,000/10,000 文件选取与资源稳定性。"""

from __future__ import annotations

import gc
import json
import os
from pathlib import Path
import statistics
import tempfile
import time
import tracemalloc
import threading

import psutil

from backend.contracts.workflows.workflow_graph import (
    WorkflowGraphEdge,
    WorkflowGraphNode,
    WorkflowGraphOutput,
    WorkflowGraphTemplate,
)
from backend.nodes.core_nodes.io.directory.directory_latest_file import (
    CORE_NODE_SPEC as LATEST,
)
from backend.nodes.core_nodes.io.local.json_load_local import CORE_NODE_SPEC as JSON
from backend.service.application.workflows.graph_executor import (
    WorkflowGraphExecutor,
    WorkflowNodeRuntimeRegistry,
)


def build_executor(directory: Path):
    """构建无文件写入副作用的选择/读取图。"""
    registry = WorkflowNodeRuntimeRegistry()
    for spec in (LATEST, JSON):
        registry.register_python_callable(spec.node_definition, spec.handler)
    template = WorkflowGraphTemplate(
        template_id="local-read-scale",
        template_version="1.0.0",
        display_name="Local Read Scale",
        nodes=(
            WorkflowGraphNode(
                node_id="latest",
                node_type_id=LATEST.node_definition.node_type_id,
                parameters={"directory_path": str(directory), "extensions": ["json"]},
            ),
            WorkflowGraphNode(
                node_id="read", node_type_id=JSON.node_definition.node_type_id
            ),
        ),
        edges=(
            WorkflowGraphEdge(
                edge_id="file",
                source_node_id="latest",
                source_port="file",
                target_node_id="read",
                target_port="file",
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="result",
                display_name="Result",
                payload_type_id="value.v1",
                source_node_id="read",
                source_port="value",
            ),
        ),
    )
    return WorkflowGraphExecutor(registry=registry), template


def sample_process() -> dict:
    """读取当前进程 Private/RSS 与句柄数量。"""
    process = psutil.Process()
    info = process.memory_info()
    return {
        "rss_bytes": info.rss,
        "private_bytes": getattr(info, "private", None),
        "handles": process.num_handles() if os.name == "nt" else process.num_fds(),
        "os_threads": process.num_threads(),
        "python_threads": [thread.name for thread in threading.enumerate()],
    }


def main() -> None:
    """测试后自动移除本次临时文件，仅 stdout 输出报告。"""
    temp_root = Path(__file__).resolve().parents[2] / ".tmp"
    temp_root.mkdir(exist_ok=True)
    reports = []
    for count in (1000, 10000):
        with tempfile.TemporaryDirectory(
            prefix="local-read-scale-", dir=temp_root
        ) as temporary:
            directory = Path(temporary)
            for index in range(count):
                path = directory / f"item-{index:05d}.json"
                path.write_text(json.dumps({"index": index}), encoding="utf-8")
                ns = 1_700_000_000_000_000_000 + index * 1_000_000
                os.utime(path, ns=(ns, ns))
            executor, template = build_executor(directory)

            def run():
                """断言每次执行都选到唯一最新文件。"""
                output = executor.execute(
                    template=template, input_values={}, execution_metadata={}
                )
                assert output.outputs["result"]["value"] == {"index": count - 1}

            for _ in range(5):
                run()
            gc.collect()
            before = sample_process()
            timings = []
            checkpoints = []
            for index in range(100):
                started = time.perf_counter()
                run()
                timings.append((time.perf_counter() - started) * 1000)
                if (index + 1) % 25 == 0:
                    gc.collect()
                    checkpoints.append({"calls": index + 1, **sample_process()})
            gc.collect()
            after = sample_process()
            tracemalloc.start()
            run()
            _, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            reports.append(
                {
                    "files": count,
                    "calls": 100,
                    "median_ms": statistics.median(timings),
                    "p95_ms": sorted(timings)[94],
                    "python_peak_bytes": peak,
                    "before": before,
                    "after": after,
                    "checkpoints": checkpoints,
                }
            )
            print(json.dumps(reports[-1], ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
