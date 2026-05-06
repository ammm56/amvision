# 测试目录约定

- `tests/`：默认常规快速测试，只验证代码逻辑、契约、编排和错误处理。
- `tests/integration/`：真实数据、真实模型、真实 runtime、真实子进程或真实链路回归。

# 默认行为

- 默认执行 `pytest` 或 `pytest tests` 时，不会递归收集 `tests/integration/`。
- 常规开发阶段应优先补 `tests/` 下的快速逻辑测试，不应默认新增真实链路测试。
- 只有在明确需要真实回归时，才在 `tests/integration/` 下新增或维护对应测试。

# 手动执行

显式指定路径时，`tests/integration/` 下的测试会执行，例如：

```powershell
D:/software/anaconda3/envs/amvision/python.exe -m pytest tests/integration/test_yolox_tensorrt_inference_tasks_api.py -q
```