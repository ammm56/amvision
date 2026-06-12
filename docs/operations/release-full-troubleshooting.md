# release/full 排障手册

## 文档目的

本文档只回答 `release/full/` 现场最常见的几类问题：

- 为什么整套起不来
- 为什么 service 正常但任务不动
- 为什么 worker 起了但某类模型任务报错
- 出问题时先看哪几个文件和命令

## 先看这 5 个点

1. `logs/full-stack/runtime-state.json` 是否存在，内容里的 pid 是否还是活的。
2. `logs/full-stack/service.log` 是否正常持续写入。
3. 目标 `worker-*.log` 是否存在，是否和任务类型对应。
4. `config/backend-service.json`、`config/backend-worker.json` 里的路径是否指向同一套 `data/`。
5. `manifests/worker-profiles/*.json` 是否真的包含当前任务需要的 consumer kind。

## 默认观测入口

| 路径或接口 | 用途 |
| --- | --- |
| `logs/full-stack/service.log` | 看 backend-service 是否正常启动、端口是否绑定成功、API 是否有异常 |
| `logs/full-stack/worker-*.log` | 看具体 worker 是否成功装配、是否在消费队列、是否有模型运行时错误 |
| `logs/full-stack/runtime-state.json` | 看 full 根脚本当前记录的 service / worker pid 和日志路径 |
| `http://127.0.0.1:8000/api/v1/system/health` | 看 service 是否已对外可用 |
| `http://127.0.0.1:8000/docs` | 看 OpenAPI 和前端静态资源是否至少能正常返回 |

## 当前基础验收结果

2026-06-12 已完成一轮 `release/full` 基础验收：

- `assemble-release --profile-id full --release-root .\release --force --output text` 通过，`bundled_python_mode=preserved-existing`。
- `validate-layout` 通过，`frontend/`、`custom_nodes/`、`tools/ffmpeg/`、`python/python.exe` 和 worker profile 目录均存在。
- `release/full/python/python.exe` 可正常 import `torch / onnxruntime / openvino / tensorrt / cuda`。
- `start_amvision_full.py` 可拉起 `backend-service` 与 `dataset-import / dataset-export / training / conversion / evaluation / inference` 六个 worker profile。
- `/api/v1/system/health`、`/docs` 和 `/openapi.json` 均可访问；OpenAPI 中可见 `classification/conversion-tasks/{task_id}/result` 这类 non-detection conversion result 路由。
- `stop-amvision-full.bat` 可清理 `logs/full-stack/runtime-state.json`。

## 常见问题

### 1. `start-amvision-full` 提示已有实例在运行

先看：

- `logs/full-stack/runtime-state.json`
- 里面记录的 pid 是否还活着

处理顺序：

1. 先执行 `.\stop-amvision-full.bat`
2. 如果 stop 提示状态文件存在但 pid 已失效，手工删除 `runtime-state.json`
3. 再重新执行 `.\start-amvision-full.bat`

这类问题通常不是代码问题，而是上次异常退出后状态文件还在。

### 2. health 不通，`/docs` 也打不开

先看：

- `logs/full-stack/service.log`

高频原因：

- 端口被占用
- `config/backend-service.json` 指到了无权限目录
- `python/` 里的依赖没装全
- `frontend/` 或 `frontend/runtime-config.json` 缺失

先做：

```powershell
.\launchers\maintenance\invoke-backend-maintenance.bat -- validate-layout --output text
```

如果 `validate-layout` 先不过，不要继续看 worker。

### 3. API 能访问，但任务一直停在 `queued`

先看：

- `logs/full-stack/worker-*.log`
- `config/backend-worker.json`
- `manifests/worker-profiles/*.json`

重点确认：

- dataset 导入任务：看 `worker-dataset-import.log`
- 训练任务：看 `worker-training.log`
- 转换任务：看 `worker-conversion.log`
- 评估任务：看 `worker-evaluation.log`
- 异步推理任务：看 `worker-inference.log`

当前 `worker profile` 真实边界是：

- `training` 已覆盖 `yolox / yolov8 / yolo11 / yolo26 / rfdetr` detection 训练，以及 `classification / segmentation / pose / obb`
- `evaluation` 与 `inference` 已覆盖 `detection / classification / segmentation / pose / obb`

所以如果任务仍然不动，先不要再怀疑“是不是还没接通 non-detection worker”，优先检查日志、队列目录和配置路径。

### 4. 某类 non-detection 模型部署能建出来，但推理报 backend 错误

先看：

- 该任务对应的 deployment / inference API 返回
- `service.log`
- 相关 worker log

当前仓库已经有一条显式 real smoke matrix：

- `tests/integration/test_non_detection_runtime_backend_smoke_matrix.py`

覆盖组合：

- `classification + yolo11`
- `segmentation + yolo26`
- `pose + yolov8`
- `obb + yolo26`

覆盖 backend：

- `onnxruntime`
- `openvino`
- `tensorrt`

如果现场问题和这四类代表组合一致，先对照这条矩阵判断是：

- 现场机器驱动 / runtime 版本问题
- 发布目录资产不完整
- 还是当前代码主线真的回归了

### 5. `openvino` 或 `tensorrt` 相关任务只在现场机器失败

先看：

- 驱动版本
- GPU / NPU 是否真的可用
- 发布目录里模型构建产物是否齐全
- `tools/ffmpeg/`、`python/`、厂商 runtime 是否来自同一套打包

当前判断原则：

- 如果 `onnxruntime` 能跑、`openvino/tensorrt` 不能跑，优先查现场 runtime 环境
- 如果三条 backend 都不能跑，再回头查模型构建、labels、部署绑定和 API 入参

### 6. `release/full/python` 看起来存在，但一 `import torch` 就直接崩

这是 bundled Python 漂移的典型信号，先不要直接怀疑业务代码。

当前已真实遇到过的现象是：

- `release/full/python/python.exe -c "import torch"` 直接报 `libiomp5md.dll already initialized`
- 同一台机器上的源码开发环境 `D:\software\anaconda3\envs\amvision\python.exe -c "import torch"` 却是正常的

高频原因：

- 当前 `release/full/python` 来自 `bundled_python_mode=preserved-existing`
- 旧 bundle 里残留了历史 DLL 或厂商 runtime 文件

先做：

```powershell
python -m backend.maintenance.main assemble-release --profile-id full --release-root .\release --force --bundled-python-source-dir D:\software\anaconda3\envs\amvision --output text
```

判断方式：

- 如果重建后 `release/full/python/python.exe -c "import torch"` 正常，说明是旧 bundle 漂移，不是当前仓库源码主链坏了
- 如果重建后仍然异常，再继续查 Python 来源目录本身和系统级 DLL 干扰

### 7. stop 脚本执行后还有进程残留

先看：

- `runtime-state.json` 是否被更新
- stop 前后 `worker-*.log` 是否还在持续写入

当前 stop 语义是：

- 先停 `backend-service` 和各类 `backend-worker:*`
- 再给 `full-stack-root` 一个自然收尾退出窗口
- 只有 root 没有自行退出时，才转入强制停止

处理顺序：

1. 先再执行一次 `.\stop-amvision-full.bat`
2. 再按 `runtime-state.json` 里的 pid 检查是否还有活进程
3. 只在确认 stop 脚本已经失败时，再手工清理残留进程和状态文件

## 推荐排障顺序

1. `validate-layout`
2. `service.log`
3. `runtime-state.json`
4. 对应 `worker-*.log`
5. `system/health`
6. 最小 API smoke
7. 必要时回到仓库侧 integration smoke

## 仓库侧验证入口

如果需要在开发仓库复现 release/full 现场问题，当前最直接的入口是：

```powershell
D:\software\anaconda3\envs\amvision\python.exe -m pytest --basetemp .tmp\pytest_openvino_matrix tests/integration/test_non_detection_runtime_backend_smoke_matrix.py -k openvino -q
```

```powershell
D:\software\anaconda3\envs\amvision\python.exe -m pytest --basetemp .tmp\pytest_tensorrt_matrix tests/integration/test_non_detection_runtime_backend_smoke_matrix.py -k tensorrt -q
```

`Windows + OpenVINO` 下如果临时目录句柄占用导致清理失败，优先换一个新的 `--basetemp`，不要直接把这种现象判断成模型主链错误。
