"""隔离发行实例的监听丢失故障注入；仅显式命令执行，不接触开发服务。"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import psutil

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))


def main() -> None:
    """启动指定隔离发行，按启动 ID 注入一次故障，验证换代并停止。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--release-root", type=Path, required=True)
    parser.add_argument("--port", type=int, default=5610)
    parser.add_argument("--real-assets", type=Path)
    args = parser.parse_args()
    root = args.release_root.resolve()
    if "http-recovery-validation" not in root.parts:
        raise ValueError("仅接受明确的 http-recovery-validation 隔离发行目录")
    if any(c.laddr.port == args.port and c.status == "LISTEN" for c in psutil.net_connections(kind="tcp")):
        raise RuntimeError("测试端口已占用")
    temporary = Path.cwd() / ".tmp" / "http-release-probe"
    temporary.mkdir(parents=True, exist_ok=True)
    fault_file = temporary / "fault.json"
    injected = temporary / "injected.json"
    fault_file.unlink(missing_ok=True)
    injected.unlink(missing_ok=True)
    (temporary / "result.json").unlink(missing_ok=True)
    # sitecustomize 仅用于隔离测试，按具体 Uvicorn 子进程 PID 关闭真实监听。
    (temporary / "sitecustomize.py").write_text('''import os, sys
if "uvicorn" in sys.orig_argv and os.environ.get("AMVISION_TEST_HTTP_FAULT"):
    import asyncio, json
    from pathlib import Path
    import uvicorn
    original = uvicorn.Server.startup
    async def startup(self, sockets=None):
        await original(self, sockets=sockets)
        async def watch():
            path = Path(os.environ["AMVISION_TEST_HTTP_FAULT"])
            while not self.should_exit:
                await asyncio.sleep(.2)
                if not path.is_file():
                    continue
                try:
                    data = json.loads(path.read_text())
                    if data.get("pid") != os.getpid():
                        continue
                except (ValueError, OSError):
                    continue
                for server in self.servers:
                    server.close()
                    await server.wait_closed()
                path.unlink()
                path.with_name("injected.json").write_text(json.dumps({"pid": os.getpid()}))
                return
        self._test_fault_task = asyncio.create_task(watch())
    uvicorn.Server.startup = startup
''', encoding="utf-8")
    env = os.environ.copy()
    env["PYTHONPATH"] = str(temporary)
    env["AMVISION_TEST_HTTP_FAULT"] = str(fault_file)
    python = root / "python" / "python.exe"
    state_path = root / "logs" / "http-test" / "launcher-status.json"
    log_path = temporary / "supervisor.log"
    report = {}

    def wait_running(generation: int):
        """等待指定 generation 正式通过完整启动门禁。"""
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(f"Supervisor 提前退出：{process.returncode}；{log_path}")
            try:
                value = json.loads(state_path.read_text())
                if value.get("root_process", {}).get("pid") != process.pid:
                    time.sleep(.5)
                    continue
                if value.get("state") == "failed":
                    raise RuntimeError(str(value.get("error")))
                if value.get("state") == "running" and value.get("generation") == generation:
                    return value
            except (OSError, ValueError):
                pass
            time.sleep(.5)
        raise TimeoutError(f"generation {generation} 未就绪")

    with log_path.open("wb") as log:
        process = subprocess.Popen([str(python), str(root / "start_amvision_full.py"),
            "--host", "127.0.0.1", "--port", str(args.port), "--logs-subdir", "http-test"],
            cwd=root, env=env, stdout=log, stderr=subprocess.STDOUT)
        client = None
        try:
            first = wait_running(1)
            model_route = None
            if args.real_assets:
                import httpx
                from tests import test_model_deployment_full_acceptance as acceptance
                base = f"http://127.0.0.1:{args.port}"
                client = httpx.Client(base_url=base + "/api/v1", timeout=180)
                login = client.post("/auth/login", json={"username": "amvar", "password": "123456"})
                login.raise_for_status()
                headers = {"Authorization": "Bearer " + login.json()["access_token"]}
                client.headers.update(headers)
                acceptance.build_test_headers = lambda **_: headers
                # 重复演练只操作隔离发行；把上一轮保留的目标状态恢复为停止。
                previous = client.get("/models/classification/deployment-instances", params={"project_id": "project-1"})
                previous.raise_for_status()
                for deployment in previous.json():
                    route = "/models/classification/deployment-instances/" + deployment["deployment_instance_id"]
                    for mode in ("sync", "async"):
                        client.post(route + f"/{mode}/stop").raise_for_status()
                acceptance.run(base, args.real_assets.resolve(), import_package=True, delete_after=False)
                deployments = client.get("/models/classification/deployment-instances", params={"project_id": "project-1"})
                deployments.raise_for_status()
                model_route = "/models/classification/deployment-instances/" + deployments.json()[0]["deployment_instance_id"]
                client.post(model_route + "/sync/start").raise_for_status()
                client.post(model_route + "/sync/warmup").raise_for_status()
            sys.path.insert(0, str(root / "launchers"))
            from http_service_monitor import probe_service
            identity = probe_service("127.0.0.1", args.port)
            assert identity.kind == "ready"
            old_children = [(p.pid, p.create_time()) for p in psutil.Process(process.pid).children(recursive=True)]
            fault_file.write_text(json.dumps({"pid": identity.pid}))
            started = time.monotonic()
            second = wait_running(2)
            new_identity = probe_service("127.0.0.1", args.port)
            assert new_identity.kind == "ready" and new_identity.instance_id != identity.instance_id
            assert first["root_process"] == second["root_process"]
            for pid, created in old_children:
                try:
                    assert psutil.Process(pid).create_time() != created
                except psutil.NoSuchProcess:
                    pass
            assert injected.exists()
            report = {"result": "passed", "old_pid": identity.pid, "new_pid": new_identity.pid,
                "recovery_seconds": round(time.monotonic() - started, 3), "old_processes": len(old_children)}
            if model_route:
                expected = json.loads((args.real_assets / "expected.json").read_text(encoding="utf-8"))
                deadline = time.monotonic() + 90
                while time.monotonic() < deadline:
                    health = client.get(model_route + "/sync/status")
                    health.raise_for_status()
                    if health.json().get("observed_state") == "running":
                        break
                    time.sleep(.5)
                else:
                    raise TimeoutError("恢复后的模型未进入 running")
                with (args.real_assets / "sample.jpg").open("rb") as sample:
                    result = client.post(model_route + "/infer", files={"input_image": ("sample.jpg", sample, "image/jpeg")},
                                         data={"top_k": "3", "save_result_image": "false"})
                result.raise_for_status()
                actual = result.json()["categories"]
                assert len(actual) == len(expected)
                for item, reference in zip(actual, expected, strict=True):
                    assert item["class_id"] == reference["class_id"]
                    assert abs(item["probability"] - reference["probability"]) < 1e-5
                report["real_model_after_recovery"] = "passed"
                report["categories"] = actual
        finally:
            if client is not None:
                client.close()
            stopped = subprocess.run([str(python), str(root / "stop_amvision_full.py"),
                "--state-file", str(root / "logs" / "http-test" / "runtime-state.json")],
                cwd=root, stdout=log, stderr=subprocess.STDOUT, timeout=120)
            process.wait(timeout=30)
            if stopped.returncode != 0:
                raise RuntimeError("隔离发行停止失败")
    (temporary / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
