# 完整发行栈排障

本文适用于 `release/full-windows-x64-cpu/` 和 `release/full-windows-x64-nvidia/`。

## 先看五项

1. `logs/full-stack/runtime-state.json` 是否存在且指向当前进程。
2. `backend-service-<当天 YYYYMMDD>.log` 是否正常持续写入。
3. `inference-daemon-<当天 YYYYMMDD>.log` 是否出现 ready 和 probe 成功。
4. 目标 `backend-worker-<profile>-<当天 YYYYMMDD>.log` 是否存在。
5. `GET http://127.0.0.1:5600/api/v1/system/health` 是否返回 `status=ok`。

日志每天切换文件。排障时先确认日期，不要只查看前一天文件。

## 日志对应关系

| 文件 | 内容 |
| --- | --- |
| `database-migration-YYYYMMDD.log` | Alembic revision、备份和迁移错误 |
| `inference-daemon-YYYYMMDD.log` | daemon、Deployment 进程、控制队列和 mmap mailbox |
| `backend-service-YYYYMMDD.log` | API、bootstrap、Workflow Runtime、Trigger 和静态前端 |
| `backend-worker-dataset-import-YYYYMMDD.log` | 数据集导入 |
| `backend-worker-dataset-export-YYYYMMDD.log` | 数据集导出 |
| `backend-worker-training-YYYYMMDD.log` | 训练 |
| `backend-worker-conversion-YYYYMMDD.log` | 转换 |
| `backend-worker-evaluation-YYYYMMDD.log` | 评估 |
| `backend-worker-inference-YYYYMMDD.log` | 异步推理 |

## 启动立即失败

先运行布局检查：

```powershell
.\launchers\maintenance\invoke-backend-maintenance.bat -- validate-layout --output text
```

核对：

- `python/python.exe` 存在且可启动。
- `frontend/index.html` 与 `frontend/runtime-config.json` 存在。
- `config/backend-service.json`、`config/backend-worker.json` 是合法 JSON。
- 发行目录只有一个 `manifests/release-profiles/*.json`。
- 六个 `manifests/worker-profiles/*.json` 与 release manifest 一致。
- 端口未被其他实例占用。

迁移失败时只看 migration 日志并恢复数据库问题；不能跳过 migration 强行启动服务。

## backend-service 可用但页面 checking

检查：

```powershell
Invoke-RestMethod http://127.0.0.1:5600/api/v1/system/health
Invoke-WebRequest http://127.0.0.1:5600/openapi.json
```

如果 API 正常：

- 查看浏览器 Network/Console。
- 核对 `frontend/runtime-config.json` 的 API base URL。
- 确认当前访问的是这份发行目录对应的 service。

如果 API 随后退出，检查 Supervisor 终端和各 Profile 日志；某组件首次启动失败会使完整 stack 回收，不能只看曾经短暂成功的 service health。

## Worker 显示 degraded

设置页只读取：

```text
data/runtime/backend-workers/active.json
  → topologies/<epoch>/manifest.json
  → profiles/<profile-id>.json
```

检查 active pointer、manifest 中的 generation/epoch、目标 Profile heartbeat 和 `worker_instance_id` 是否一致。历史 epoch、旧目录或手工创建的心跳不属于当前状态。

单 Profile 崩溃时 Supervisor 应只恢复该 Profile，并生成新的 instance id。其他 Profile、daemon 和 service PID 应保持不变。反复恢复时查看对应 Profile 日志的首个异常，不要手工启动第二个 Worker。

## 任务一直 queued

1. 根据任务类型找到正确 Profile。
2. 检查该 Profile 是否 `running` 且 heartbeat 新鲜。
3. 确认 service 与 worker 的 `queue.root_dir` 指向同一发行目录 `data/queue`。
4. 查看 Task events 与 Profile 日志。
5. 检查队列文件权限、磁盘空间和杀毒软件锁定。

不要通过提高 lease、重复提交或启动旧兼容 Worker 掩盖消费者未运行的问题。

## Deployment 或同步推理失败

依次检查：

1. inference daemon 日志和 probe。
2. DeploymentInstance 的 desired/observed state、generation 和健康实例数。
3. 模型 runtime、device、precision 和输入尺寸。
4. `data/buffers/` 与 mmap mailbox 权限和容量。
5. OpenVINO/TensorRT/CUDA 的版本与目标硬件。

容量已满时同步接口会直接返回错误；系统不在内部排队或自动重试。调用方应按业务节奏再次调用。

## Workflow Runtime 或 Trigger 失败

检查 Runtime：

- active/desired revision
- generation
- snapshot fingerprint
- worker instance id
- recent error

检查 Run：

- revision/version/generation/fingerprint/worker provenance
- state 与 error details
- 输入引用是否仍存在

切版前必须停止 Runtime 并处理活动 Run/Trigger。Trigger 保持稳定 runtime id；版本更新不应要求更换 Trigger 或 SDK 配置。

图片输入：

- ObjectStore 使用相对 `object_key`。
- 磁盘文件使用显式绝对路径。
- Windows JSON 字符串中的反斜杠必须正确转义，或使用 `/`。
- `media_type` 必须与实际文件内容一致。

## CPU/NVIDIA 包不匹配

CPU-only 机器使用：

```text
release/full-windows-x64-cpu/
```

NVIDIA 机器使用：

```text
release/full-windows-x64-nvidia/
```

CPU 包不包含 TensorRT/cuDNN。NVIDIA 包要求兼容 driver；`python/` 中 TensorRT wheel、`tools/tensorrt/bin` DLL 和 `trtexec` 必须同版本。

快速导入核对：

```powershell
.\python\python.exe -c "import torch, onnxruntime, openvino; print(torch.__version__)"
```

NVIDIA 包再核对：

```powershell
.\python\python.exe -c "import tensorrt; print(tensorrt.__version__)"
```

## 正确停止

```powershell
.\stop-amvision-full.bat
```

stop 会校验 PID、创建时间、解释器、工作目录和命令行。仍有进程存活时返回非零并保留 `runtime-state.json`。此时：

1. 根据输出定位仍存活进程。
2. 查看其当天日志。
3. 处理文件句柄或子进程。
4. 再次执行 stop。

不要直接删除状态文件或只按 PID 强杀不明进程。

## 回归与 soak

仓库根目录执行发行组装测试：

```powershell
conda activate amvision
python -m pytest tests/test_release_assembly.py -q
```

完整进程验收：

```powershell
python -m pytest tests/integration/test_release_full_stack_acceptance.py -q
```

长时负载应覆盖实际 Deployment、Workflow Runtime 和 Trigger，监控：

- RSS、CPU、线程和句柄趋势
- Profile 重启次数与 instance id
- 请求成功率和时延分位数
- mmap 槽位 generation/owner/deadline
- Run 终态与版本 provenance
- 跨日日志切换
- stop 后端口、进程和状态文件是否完全回收

空载常驻不能替代真实模型和 Workflow 持续负载。
