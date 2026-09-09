"""真实 RF-DETR IR 的 AUTO 冷启动门禁；设置模型路径后执行独立进程循环。"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from time import perf_counter

import pytest


@pytest.mark.parametrize("cycle", range(20))
def test_rfdetr_auto_cold_process(cycle: int) -> None:
    """每轮全新进程编译、执行 20 帧并正常回收，覆盖 AUTO 原切换窗口。"""
    path = os.environ.get("AMVISION_RFDETR_AUTO_IR")
    if not path:
        pytest.skip("需要 AMVISION_RFDETR_AUTO_IR 指向真实 RF-DETR segmentation IR")
    assert Path(path).is_file()
    completed = subprocess.run(
        [sys.executable, "-m", "tests.integration.test_rfdetr_openvino_auto", path],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    result = json.loads(completed.stdout.strip().splitlines()[-1])
    assert result["frames"] == 20
    assert result["output_names"] == ["pred_boxes", "pred_logits", "pred_masks"]
    print(json.dumps({"cycle": cycle, **result}), flush=True)


def _probe(path: str) -> None:
    """通过正式编译入口运行真实三输出模型，记录启动和帧耗时。"""
    import numpy as np
    import openvino as ov
    from backend.service.application.runtime.support.openvino_execution import (
        OpenVinoCompilationPolicy,
        compile_openvino_model,
        get_openvino_runtime_diagnostics,
    )
    from backend.service.domain.deployments.deployment_runtime_configuration import (
        DeploymentRuntimeConfiguration,
        OpenVinoAutoRuntimeOptions,
    )

    started = perf_counter()
    model = compile_openvino_model(
        openvino_module=ov,
        model_path=path,
        device_name="AUTO",
        base_properties={},
        runtime_configuration=DeploymentRuntimeConfiguration(
            backend_options=OpenVinoAutoRuntimeOptions()
        ),
        compilation_policy=OpenVinoCompilationPolicy(
            False, "rfdetr-segmentation-auto-output-handover"
        ),
    )
    compile_seconds = perf_counter() - started
    required = ("pred_boxes", "pred_logits", "pred_masks")
    ports = {
        name: next(port for port in model.outputs if name in port.get_names())
        for name in required
    }
    data = np.random.default_rng(0).random(
        tuple(model.input(0).shape), dtype=np.float32
    )
    durations = []
    for _ in range(20):
        started = perf_counter()
        outputs = model.infer_new_request({model.input(0): data})
        durations.append(perf_counter() - started)
        for name, port in ports.items():
            value = outputs[port]
            assert value.size > 0 and np.isfinite(value).all(), name
            assert value.shape[0] == 1
    diagnostics = get_openvino_runtime_diagnostics(model)
    print(
        json.dumps(
            {
                "frames": 20,
                "output_names": list(required),
                "compile_seconds": compile_seconds,
                "first_frame_seconds": durations[0],
                "mean_frame_seconds": sum(durations) / len(durations),
                "devices": model.get_property("EXECUTION_DEVICES"),
                "diagnostics": diagnostics.effective,
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    _probe(sys.argv[1])
