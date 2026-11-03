"""汇总同一真实图的交替对照与连续调用证据，不重跑模型或修改业务资源。"""

import json
from statistics import median

import numpy as np

from scripts.audit_linescan_front_result import validate_coordinates
from scripts.configure_linescan_3913_workflow import DATA


def main():
    """按 ID、独立坐标复算、清理状态和 Worker 资源核对保存的报告。"""
    root = DATA / "validation/front-performance"
    output = DATA / "validation/front-optimization-20261030/verification.json"
    summary = {}
    for name in [
        "ab-a1",
        "ab-b1",
        "ab-b2",
        "ab-a2",
        "optimized-repeat-20",
        "optimized-missing",
        "optimized-empty",
    ]:
        report = json.loads((root / name / "report.json").read_text("utf-8"))
        assert (
            report["cleanup"]["runtime_deleted"]
            and report["cleanup"]["application_deleted"]
        )
        pid = report["started"]["worker_process_id"]
        resources = []
        coordinate_errors = []
        for run in report["runs"]:
            assert (
                run["correctness"]["codes_equal_by_id"]
                and run["correctness"]["final_result_matches"]
            )
            response = run["response"]
            results = response.get("outputs") or response["results"]
            coordinate_errors.append(
                validate_coordinates(
                    results["report"]["value"], results["audit_report"]["value"]
                )
            )
            resources.append(next(p for p in run["memory"] if p["pid"] == pid))
        durations = [r["elapsed_ms"] for r in report["runs"]]
        stages = {}
        for node in (
            "decoded_source",
            "overview",
            "locate",
            "align",
            "batch_detect",
            "prepared_end",
            "crop_search",
            "final_end",
            "final_box_end",
        ):
            values = [
                n["duration_ms"]
                for r in report["runs"]
                for n in r["response"].get("node_records", [])
                if n["node_id"] == node
            ]
            if values:
                stages[node] = median(values)
        summary[name] = {
            "runs": len(durations),
            "elapsed_ms": durations,
            "median_ms": median(durations),
            "p95_ms": float(np.percentile(durations, 95)),
            "maximum_coordinate_error_pixels": max(coordinate_errors),
            "worker_pid": pid,
            "worker_resources": resources,
            "cpu_percent": [
                r["environment"]["cpu_percent_since_previous_sample"]
                for r in report["runs"]
            ],
            "node_median_ms": stages,
            "temporary_resources_deleted": True,
        }
    for group, names in {
        "before": ["ab-a1", "ab-a2"],
        "after": ["ab-b1", "ab-b2"],
    }.items():
        values = [v for name in names for v in summary[name]["elapsed_ms"]]
        summary[group] = {
            "median_ms": median(values),
            "min_ms": min(values),
            "max_ms": max(values),
        }
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), "utf-8")
    print(
        json.dumps(
            {
                k: {
                    field: value
                    for field, value in v.items()
                    if field not in {"worker_resources", "elapsed_ms"}
                }
                for k, v in summary.items()
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
