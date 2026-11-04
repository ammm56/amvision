"""A09 真实完整工件的独立调用方和服务进程分角色资源观测。"""

import argparse
import json
import os
from pathlib import Path
import platform
import subprocess
import sys


def identity(pid):
    """复用内核出生标识；WSL 墙钟校正不应改变角色身份。"""
    import psutil
    from backend.runtime.processes.birth_identity import read_process_birth_identity

    process = psutil.Process(pid)
    return dict(
        pid=pid,
        create_time=process.create_time(),
        birth_identity=read_process_birth_identity(pid),
    )


def summarize_roles(path, roles):
    """只汇总完整采样；各角色峰值不相加作为同一时刻总峰值。"""
    fields = ("rss_bytes", "private_bytes", "threads", "handles")
    result = {
        name: dict(identity=value, samples=0, peak={}, last={})
        for name, value in roles.items()
    }
    identities = {
        (value["pid"], value["birth_identity"]): name for name, value in roles.items()
    }
    unassigned = {}
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            sample = json.loads(line)
            if "error" in sample or "discarded" in sample:
                continue
            for process in sample.get("processes", []):
                key = process["pid"], process["birth_identity"]
                name = identities.get(key)
                if name is None:
                    name = f"service-support-{key[0]}-{key[1]}"
                    target = unassigned.setdefault(
                        name,
                        dict(
                            identity=dict(pid=key[0], birth_identity=key[1]),
                            samples=0,
                            peak={},
                            last={},
                        ),
                    )
                else:
                    target = result[name]
                target["samples"] += 1
                target["last"] = {field: process[field] for field in fields}
                for field in fields:
                    target["peak"][field] = max(
                        target["peak"].get(field, 0), process[field]
                    )
    if any(not value["samples"] for value in result.values()):
        raise AssertionError(f"角色没有实际采样：{result}")
    return dict(roles=result, service_support=unassigned)


def main():
    """入口仅编排验收，数据面使用正式客户端，不新写共享内存协议。"""
    from scripts.metrology_workpiece import build_documents
    from tests.integration.metrology3d.asset_operations import observe_processes
    from tests.integration.metrology3d.published_support import published_system
    from tests.integration.metrology3d.representative_workflow import (
        representative_policy,
    )
    from tests.integration.metrology3d.test_published_runtime import (
        sample_array,
        assert_process_exited,
    )
    from tests.integration.metrology3d.workpiece_workflow import check_record
    from tests.point_cloud_support import spatial
    from tests.test_point_cloud_delivery import isolated_environment

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--sample", required=True, type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    root.mkdir(parents=True, exist_ok=False)
    binary = root / "cloud.bin"
    cloud = sample_array(args.sample, binary).model_copy(update=dict(spatial=spatial()))
    descriptor = root / "cloud.json"
    descriptor.write_text(cloud.model_dump_json(), encoding="utf-8")
    client_root = root / "client"
    (client_root / "config").mkdir(parents=True)
    roles = {"backend-and-orchestrator": identity(os.getpid())}
    report = dict(
        platform=platform.platform(),
        point_count=cloud.point_count,
        input_bytes=cloud.content_length,
        calls=[],
        sampler_seconds=0.25,
        numerical_gate="absolute 1e-7 mm",
        timing_acceptance=False,
    )
    with observe_processes(root):
        with published_system(
            root / "service", point_cloud_policy=representative_policy()
        ) as system:
            version = system.publish(
                documents=build_documents(input_kind="array", view="numeric")
            )
            runtime = system.start(version)
            generation = system.enable_source(create=True)
            roles["workflow-worker"] = identity(runtime["worker_process_id"])
            roles["broker"] = identity(system.idle()[1]["process_id"])
            (client_root / "config/backend-service.json").write_text(
                system.settings.model_dump_json(), encoding="utf-8"
            )
            environment = isolated_environment()
            environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[3])
            for index in range(2):
                command = [
                    sys.executable,
                    "-m",
                    "runtimes.clients.point_cloud",
                    "--descriptor",
                    str(descriptor),
                    "--array",
                    str(binary),
                    "--source",
                    system.source_id,
                    "--generation",
                    str(generation),
                    "--timeout-ms",
                    "120000",
                ]
                with (
                    (root / f"client-{index}.json").open(
                        "w", encoding="utf-8"
                    ) as output,
                    (root / f"client-{index}.err").open(
                        "w", encoding="utf-8"
                    ) as errors,
                ):
                    process = subprocess.Popen(
                        command,
                        cwd=client_root,
                        env=environment,
                        stdout=output,
                        stderr=errors,
                    )
                    try:
                        roles[f"external-client-{index}"] = identity(process.pid)
                        code = process.wait(timeout=150)
                    finally:
                        if process.poll() is None:
                            process.kill()
                            process.wait(timeout=15)
                assert code == 0, (root / f"client-{index}.err").read_text("utf-8")
                reply = json.loads((root / f"client-{index}.json").read_text("utf-8"))
                assert reply["state"] == "succeeded", reply
                record = check_record(
                    reply["response_payload"]["results"]["body"], system
                )
                trigger, broker = system.assert_reclaimed()
                run = system.call(
                    "GET", f"/runs/{reply['workflow_run_id']}?response_mode=run"
                )
                assert (
                    run["workflow_app_version_id"] == version
                    and run["worker_instance_id"] == runtime["worker_instance_id"]
                )
                assert run["node_records"] == []
                assert_process_exited(process.pid)
                report["calls"].append(
                    dict(
                        run_id=reply["workflow_run_id"],
                        state=record["state"],
                        measurements=50,
                        matches_reference=True,
                        saved_matches_reply=True,
                        active_leases=broker["active_lease_count"],
                        active_permits=trigger["routes"]["active_source_permit_count"],
                        client_exited=True,
                    )
                )
            system.call("POST", f"/app-runtimes/{system.runtime_id}/stop")
            assert_process_exited(runtime["worker_process_id"])
            system.assert_reclaimed()
        assert_process_exited(roles["broker"]["pid"])
    summary = json.loads((root / "resources-summary.json").read_text("utf-8"))
    assert not summary["failures"], summary
    report.update(summarize_roles(root / "resources.jsonl", roles))
    report.update(
        resource_summary=summary,
        stopped_and_reclaimed=True,
        browser="separate A08 viewer ledger; not part of this process tree",
        private_memory_semantics="Windows private commit; Linux RSS fallback, not USS",
    )
    (root / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
