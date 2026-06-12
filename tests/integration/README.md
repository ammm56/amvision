# 测试目录约定

- `tests/`：默认常规快速测试，只验证代码逻辑、规则、编排和错误处理。
- `tests/integration/`：真实数据、真实模型、真实 runtime、真实子进程或真实链路回归。
- `docs/architecture/yoloe-sam3-soak-baseline.md`：YOLOE / SAM3 显式 soak / benchmark 的目标机器基线结果。

# 默认行为

- 默认执行 `pytest` 或 `pytest tests` 时，不会递归收集 `tests/integration/`。
- 常规开发阶段应优先补 `tests/` 下的快速逻辑测试，不应默认新增真实链路测试。
- 只有在明确需要真实回归时，才在 `tests/integration/` 下新增或维护对应测试。
- `tests/integration/` 也用于长时 soak / benchmark；这类测试只有显式指定文件路径时才执行。
- `docs/examples/workflows/`、`docs/api/examples/workflows/` 与 Postman/样例 JSON 的规则校验，当前主要放在常规测试集里的 `tests/test_workflow_example_documents.py` 与 `tests/test_workflow_api_document_examples.py`；`tests/integration/` 只负责真实资产、真实 runtime、真实子进程和更重闭环。
- 当前 non-detection runtime backend 矩阵会覆盖 YOLOv8、YOLO11、YOLO26 在 classification、segmentation、pose、obb 四类任务下的真实 conversion -> runtime predict；RF-DETR segmentation 保持在独立测试文件中验证。
- `release/full` 真实启停验收也放在本目录，默认只做短时驻留；需要更长 soak 时通过环境变量显式调大时长。该测试会检查陈旧状态文件恢复、组件日志、资源快照和 stop 后进程回收，并在本次 logs 子目录写出 `resource-baseline.json`。

# 手动执行

显式指定路径时，`tests/integration/` 下的测试会执行，例如：

```powershell
D:/software/anaconda3/envs/amvision/python.exe -m pytest tests/integration/test_yolox_tensorrt_inference_tasks_api.py -q
```

```powershell
D:/software/anaconda3/envs/amvision/python.exe -m pytest tests/integration/test_yoloe_sam3_soak_benchmark.py -q
```

```powershell
D:/software/anaconda3/envs/amvision/python.exe -m pytest tests/integration/test_yoloe_sam3_extended_soak_benchmark.py -q
```

```powershell
D:/software/anaconda3/envs/amvision/python.exe -m pytest tests/integration/test_yoloe_sam3_workflow_app_runtime_smoke.py -q
```

```powershell
D:/software/anaconda3/envs/amvision/python.exe -m pytest tests/integration/test_sam3_video_interactive_regression.py -q
```

```powershell
D:/software/anaconda3/envs/amvision/python.exe -m pytest tests/integration/test_sam3_video_workflow_closure.py -q
```

```powershell
D:/software/anaconda3/envs/amvision/python.exe -m pytest tests/integration/test_sam3_video_memory_attention_benchmark.py -q -s
```

```powershell
D:/software/anaconda3/envs/amvision/python.exe -m pytest --basetemp .tmp/pytest_openvino_matrix tests/integration/test_non_detection_runtime_backend_smoke_matrix.py -k openvino -q
```

```powershell
D:/software/anaconda3/envs/amvision/python.exe -m pytest --basetemp .tmp/pytest_tensorrt_matrix tests/integration/test_non_detection_runtime_backend_smoke_matrix.py -k tensorrt -q
```

```powershell
D:/software/anaconda3/envs/amvision/python.exe -m pytest --basetemp .tmp/pytest_non_detection_full_matrix tests/integration/test_non_detection_runtime_backend_smoke_matrix.py -q
```

```powershell
D:/software/anaconda3/envs/amvision/python.exe -m pytest --basetemp .tmp/pytest_release_full_acceptance tests/integration/test_release_full_stack_acceptance.py -q
```

```powershell
$env:AMVISION_RELEASE_FULL_SOAK_SECONDS="600"; D:/software/anaconda3/envs/amvision/python.exe -m pytest --basetemp .tmp/pytest_release_full_soak tests/integration/test_release_full_stack_acceptance.py -q
```
