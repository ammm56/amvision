# Windows 发行与生产启动

当前可交付 profile：

- `full-windows-x64-cpu`
- `full-windows-x64-nvidia`

Ubuntu profile 仅保留命名，不可组装或交付。

## 1. 准备构建环境

从仓库根目录执行：

```powershell
conda activate amvision
python -c "import sys; print(sys.version); print(sys.executable)"
Set-Location frontend/web-ui
npm ci
npm run build
Set-Location ../..
```

Python 要求 3.12+，Node.js 要求以 `frontend/web-ui/package.json` 为准。

## 2. 组装发行目录

CPU：

```powershell
python -m backend.maintenance.main assemble-release --profile-id full-windows-x64-cpu --release-root .\release --force --output text
```

NVIDIA：

```powershell
python -m backend.maintenance.main assemble-release --profile-id full-windows-x64-nvidia --release-root .\release --force --output text
```

组装会复制当前 backend、config 模板、Node Pack、前端 `dist`、launcher、manifest 和对应 runtime 工具。`release/<profile-id>/app/` 是生成结果，不能直接修改。

`--force` 会保留既有 `python/` 后重新组装其他内容。首次生成只创建 Python 占位目录，不复制当前 conda 环境。

## 3. 准备 bundled Python

把与 profile、Python 版本和依赖锁一致的 Windows Python 环境放到：

```text
release/<profile-id>/python/python.exe
```

目标机不依赖系统 Python 或 conda。详细步骤见 [Bundled Python](bundled-python-deployment.md)。

NVIDIA profile 还必须核对：

- 目标机 NVIDIA driver；
- `tools/tensorrt/`、`tools/cudnn/`；
- bundled Python 中 TensorRT wheel 与 `tools/tensorrt/bin` DLL 同版本；
- CUDA Toolkit 等不能随包提供的系统依赖。

CPU profile 不应包含 TensorRT/cuDNN，也不应安装 `tensorrt-cu12`、`cuda-python`。

## 4. 校验布局

进入发行目录：

```powershell
Set-Location release/full-windows-x64-cpu
.\launchers\maintenance\invoke-backend-maintenance.bat -- validate-layout --output text
```

NVIDIA 环境替换为对应目录。布局校验失败必须修正发行资产，不能通过删除 manifest 或绕过 launcher 启动。

## 5. 启动完整服务

```powershell
.\start-amvision-full.bat
```

默认监听地址为 `0.0.0.0`，默认端口为 `5600`。只有需要改变监听范围或端口时才传 `--host`、`--port`。

启动器按顺序：

1. Alembic `upgrade head`，SQLite schema 变化前创建一致性备份；
2. inference daemon 启动并通过 ready/probe；
3. backend-service 启动并通过 health；
4. 六个 Worker Profile 启动并通过 heartbeat；
5. 写入 `logs/full-stack/runtime-state.json`。

任一关键步骤失败都会回收已经启动的组件并返回非零。根脚本保持前台运行；直接按 `Ctrl+C` 会按逆序停止进程树。

## 6. 验收

```powershell
Invoke-RestMethod http://127.0.0.1:5600/api/v1/system/health
```

同时核对：

- `http://127.0.0.1:5600/docs` 可用；
- 发行静态前端可加载并完成登录/bootstrap；
- Settings 服务页显示 daemon、service 和六个 Profile healthy；
- `runtime-state.json` 中 pid、创建时间、命令行和日志路径完整；
- 当天已创建 `*-YYYYMMDD.log`；
- 数据集/训练/转换/评估/异步推理中至少一个目标 smoke 能从 queued 到终态；
- 目标 Deployment 和 Workflow Runtime 能 start、health、invoke、stop。

新机器完整清单见 [首次部署](full-first-deploy-checklist.md)。

## 7. 停止

在发行目录的另一终端执行：

```powershell
.\stop-amvision-full.bat
```

stop 会按 Worker、backend-service、inference daemon、根监督进程的逆序停止，并同时核对 PID、创建时间、解释器、工作目录和命令行。只有全部退出才删除 runtime state；返回非零时必须先查看状态文件和当日日志。

不要手工删除 `runtime-state.json`、只按 PID 杀进程或直接运行低层 Worker 来绕过失败。

## 日志

```text
logs/full-stack/
├─ database-migration-YYYYMMDD.log
├─ inference-daemon-YYYYMMDD.log
├─ backend-service-YYYYMMDD.log
├─ backend-worker-<profile>-YYYYMMDD.log
└─ runtime-state.json
```

同一天持续 append 到当天文件；本地日期变化后的第一段输出切换到新文件。日志和排障见 [完整发行栈排障](../operations/release-full-troubleshooting.md)。

## 发行内容边界

- 包含应用代码、配置模板、前端、Node Pack、launcher、manifest 和 profile 对应 runtime 工具；
- 不包含开发数据库、Project/Dataset/Workflow 业务数据、预训练权重或本地调试文件；
- `data/` 初始为空，由目标环境初始化；
- NVIDIA driver 和明确列出的系统依赖不随包复制；
- 源码更新后必须重新 build/assemble/validate，不在发行目录打补丁。

相关文档：[发布 Profile](runtime-profiles.md)、[Backend Service](backend-service-startup.md)、[Worker Topology](backend-worker-startup.md)、[Inference Daemon](inference-daemon.md)。
