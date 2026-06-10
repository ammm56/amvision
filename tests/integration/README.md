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
