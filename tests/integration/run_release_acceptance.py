"""以独立配置启动发行验收；不隐式连接开发服务，不自动组装活动发行包。"""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import shutil

from tests.integration.acceptance_contract import positive_seconds


def main() -> int:
    """配置中的 output 必须是新目录；duration_seconds 只表示真实稳定负载。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8-sig"))
    if "profile" in config or config.get("acceptance_profile", "short") not in {"short", "performance", "soak"}:
        raise ValueError("使用 acceptance_profile=short/performance/soak 指定验收模式")
    output = Path(config["output"]).resolve()
    if output.exists():
        raise FileExistsError(output)
    duration = positive_seconds(config["duration_seconds"], "duration_seconds")
    environment = dict(os.environ)
    environment.update({
        "OMP_NUM_THREADS": "2", "MKL_NUM_THREADS": "2",
        "AMVISION_RELEASE_FULL_ROOT": str(Path(config["release_root"]).resolve()),
        "AMVISION_RELEASE_FULL_PORT": str(config["backend_port"]),
        "AMVISION_RELEASE_FULL_LOGS_SUBDIR": output.name,
        "AMVISION_RELEASE_FULL_SOAK_SECONDS": str(duration + positive_seconds(config.get("setup_budget_seconds", 600), "setup_budget_seconds")),
        "AMVISION_RELEASE_FULL_RESOURCE_SAMPLE_INTERVAL_SECONDS": str(config.get("sample_interval_seconds", 10)),
        "AMVISION_RELEASE_FULL_RESOURCE_WARMUP_SECONDS": "0",
        "AMVISION_RELEASE_FULL_RESOURCE_LIMITS_JSON": json.dumps(config.get("resource_limits", {
            "rss_bytes": 268435456, "private_bytes": 268435456, "handles": 128, "threads": 32})),
        "AMVISION_RELEASE_FULL_VERIFY_PROFILE_RECOVERY": "true",
        "AMVISION_ACCEPTANCE_OBSERVATION_LIMITS": json.dumps(config.get("observation_limits", {})),
        "AMVISION_RELEASE_FULL_SOAK_WORKLOAD_CWD": str(Path.cwd()),
        "AMVISION_RELEASE_FULL_SOAK_WORKLOAD_COMMAND_JSON": json.dumps([
            sys.executable, "-m", "tests.integration.model_matrix_release_workload", "--config", str(args.config.resolve())]),
    })
    if str(config.get("device", "")).startswith("cuda:"):
        environment["AMVISION_ACCEPTANCE_GPU_INDEX"] = str(config["device"]).split(":")[1]
    if manifest := config.get("candidate_manifest"):
        from tests.integration.acceptance_candidate import verify_candidate
        if verify_candidate(Path(manifest))["status"] != "passed":
            raise ValueError("验收候选内容已变化，必须重新冻结")
        environment["AMVISION_ACCEPTANCE_CANDIDATE_MANIFEST"] = str(Path(manifest).resolve())
    output.parent.mkdir(parents=True, exist_ok=True)
    with (output.parent / (output.name + ".pytest.log")).open("w", encoding="utf-8") as stream:
        completed = subprocess.run([sys.executable, "-m", "pytest", "tests/integration/test_release_full_stack_acceptance.py",
                                    "--basetemp", str(Path(".tmp") / output.name), "-q"], env=environment,
                                   stdout=stream, stderr=subprocess.STDOUT, check=False)
    # 发行目录可重新组装，完整门禁与日志必须先归档到本轮独立证据目录。
    logs = Path(config["release_root"]) / "logs" / output.name
    if logs.exists():
        output.mkdir(parents=True, exist_ok=True)
        shutil.copytree(logs, output / "release-logs")
    return completed.returncode


if __name__ == "__main__":
    sys.exit(main())
