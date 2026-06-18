# 测试目录约定

- `tests/`：默认常规快速测试，只验证代码逻辑、规则、编排和错误处理。
- `tests/integration/`：真实数据、真实模型、真实 runtime、真实子进程或真实链路回归。
- `docs/architecture/yoloe-sam3-soak-baseline.md`：YOLOE / SAM3 显式 soak / benchmark 的目标机器基线结果。

# 默认行为

- 默认执行 `pytest` 或 `pytest tests` 时，不会递归收集 `tests/integration/`。
- 常规开发阶段应优先补 `tests/` 下的快速逻辑测试，不应默认新增真实链路测试。
- 只有在明确需要真实回归时，才在 `tests/integration/` 下新增或维护对应测试。
- `tests/integration/` 也用于真实资产、真实 runtime 和短时 benchmark；这类测试只有显式指定文件路径时才执行。
- 训练类 integration 只允许做几分钟内的 smoke，例如 checkpoint 覆盖率、tiny backward、短时转换校验。真实长时间训练不放进 pytest，由现场调试时通过平台训练任务执行和观察。
- 真实全链路脚本如果需要通过公开 API 串起 DatasetImport、DatasetExport、training、conversion、deployment 和 inference，应放在 `tests/integration/`，不要放进 `backend/maintenance` 或业务代码目录；这类脚本不加 `test_` 前缀，避免默认 pytest 自动收集。
- `docs/examples/workflows/`、`docs/api/examples/workflows/` 与 Postman/样例 JSON 的规则校验，当前主要放在常规测试集里的 `tests/test_workflow_example_documents.py` 与 `tests/test_workflow_api_document_examples.py`；`tests/integration/` 只负责真实资产、真实 runtime、真实子进程和更重闭环。
- 当前 non-detection runtime backend 组合验证会覆盖 YOLOv8、YOLO11、YOLO26 在 classification、segmentation、pose、obb 四类任务下的真实 conversion -> runtime predict；RF-DETR segmentation 保持在独立测试文件中验证。
- RF-DETR full core 短时 smoke / benchmark 放在 `test_rfdetr_full_core_soak_benchmark.py`，默认跳过，必须通过环境变量显式打开。
- RF-DETR 真实本地 checkpoint 覆盖率 smoke 也放在 `test_rfdetr_full_core_soak_benchmark.py`，默认跳过，只在显式指定环境变量时读取 `data/files/models/pretrained/rfdetr`。默认清单覆盖 detection `nano / s / m / l` 和 segmentation `nano / s / m / l / x`，并同时输出 raw coverage 与真实加载路径 coverage。
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
D:/software/anaconda3/envs/amvision/python.exe -m tests.integration.yolov8_full_chain_smoke --tasks detection classification segmentation pose obb --target-formats onnx --start-processes
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
$env:AMVISION_RUN_RFDETR_CHECKPOINT_SMOKE="1"
D:/software/anaconda3/envs/amvision/python.exe -m pytest --basetemp .tmp/pytest_rfdetr_checkpoint_smoke tests/integration/test_rfdetr_full_core_soak_benchmark.py -k checkpoint -q -s
```

如果只想临时验证某几个本地权重，可以设置 `AMVISION_RFDETR_CHECKPOINT_SMOKE_CASES`，格式为 `task_type:scale:checkpoint_path`，多项用分号分隔。没有设置时使用当前平台公开的全部 RF-DETR 本地预训练 scale。

```powershell
$env:AMVISION_RUN_RFDETR_FULL_CORE_SOAK="1"
$env:AMVISION_RFDETR_FULL_CORE_SOAK_ITERATIONS="50"
D:/software/anaconda3/envs/amvision/python.exe -m pytest --basetemp .tmp/pytest_rfdetr_full_core_soak tests/integration/test_rfdetr_full_core_soak_benchmark.py -k tiny -q -s
```

```powershell
$env:AMVISION_RUN_RFDETR_FULL_CORE_SOAK="1"
$env:AMVISION_RUN_RFDETR_FULL_CORE_CONVERSION_SOAK="1"
$env:AMVISION_RFDETR_FULL_CORE_CONVERSION_TASKS="detection,segmentation"
D:/software/anaconda3/envs/amvision/python.exe -m pytest --basetemp .tmp/pytest_rfdetr_full_core_conversion_soak tests/integration/test_rfdetr_full_core_soak_benchmark.py -k onnx -q -s
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

RF-DETR deployment 常驻 soak 应先创建真实 deployment 任务和真实转换产物，再结合 release/full 启停验收执行；不要用普通模型前向测试冒充 deployment soak。
RF-DETR 真实长时间训练不通过 pytest 跑；需要按现场数据集、训练参数和目标 GPU 手动提交平台训练任务，再用任务日志、模型输出文件和后续转换/部署结果判断。
RF-DETR ONNX conversion smoke 会先尝试 PyTorch 2.8 新 exporter；如果当前模型算子路径不被新 exporter 完整支持，会受控回退到 TorchScript exporter，并在 ONNX metadata 中写入实际导出模式。测试关注导出产物、输出名和 ONNXRuntime 数值摘要，不把 exporter warning 当成长时间训练或部署失败。
