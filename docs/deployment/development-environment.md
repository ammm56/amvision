# 开发环境说明

## 文档目的

本文档用于给开发调试阶段提供统一入口，说明仓库根目录下的推荐启动顺序、常用命令和细分文档阅读路径。

## 适用范围

- conda 开发环境
- 仓库根目录直接调试
- service、worker、maintenance 分开启动

## 当前推荐顺序

1. 激活 conda 环境
2. 按需执行 maintenance 命令
3. 启动 backend-service
4. 启动一个或多个 backend-worker
5. 调用 health、docs 和目标业务接口做联调

## 常用命令

### 激活环境

```powershell
conda activate amvision
```

### service 开发调试启动

```powershell
python -m uvicorn backend.service.api.app:app --host 127.0.0.1 --port 8000 --reload
```

VS Code 中当前推荐直接使用 Run and Debug 里的 `Python 调试程序: backend-service 热重载` 或 `Python 调试程序: backend-service 全量启动`。

### worker 开发调试启动

全量默认 worker：

```powershell
python -m backend.workers.main
```

VS Code 中当前推荐直接在终端或任务里执行 `python -m backend.workers.main`，不通过 Python debugpy 启动 worker。
打开命令面板 ctrl + p
执行 Tasks: Run Task
选择 amvision: 启动 backend-worker 全量

### workflow 开发调试启动说明

workflow 当前没有单独的 `python -m ...` 常驻进程入口，不需要再额外手工启动一个独立的 workflow worker 主进程。

- preview run 通过 backend-service 当前进程按请求临时拉起隔离子进程，执行完成后回收
- WorkflowAppRuntime 的长期运行实例由 backend-service 启动时一并创建的 runtime manager 托管；真正的 runtime worker 进程在调用 `POST /api/v1/workflows/app-runtimes/{workflow_runtime_id}/start` 或 restart 后按需拉起
- sync invoke 和 async run 都复用已经启动的 WorkflowAppRuntime 单实例 worker；如果 runtime 还没有处于 running，需要先调用 start

当前开发联调如果只覆盖 workflow template save、application save、execution policy、preview run、app runtime start、sync invoke、async runs 和 cancel，启动 backend-service 即可看到 workflow 相关进程被按需拉起。

`python -m backend.workers.main` 仍然是任务系统和后台 consumer 的独立入口，但它不负责 workflow runtime 的长期实例管理。只有当 workflow 节点内部依赖现有后台任务系统、异步推理、训练、转换、评估、导出等 worker consumer 时，才需要同时启动 backend-worker。

单一 profile worker：

```powershell
python runtimes/launchers/worker/start_backend_worker.py --worker-profile-file runtimes/manifests/worker-profiles/dataset-import.json
```

### maintenance 常用命令

```powershell
python -m backend.maintenance.main validate-layout --output json
python -m backend.maintenance.main assemble-release --profile-id full --release-root ./release --force --output text
```

## 细分文档入口

- service 细节：`backend-service-startup.md`
- worker 细节：`backend-worker-startup.md`
- maintenance 细节：`backend-maintenance.md`

## 边界说明

- 开发环境优先保留 service 和 worker 分开启动，方便观察单个进程日志和局部排障
- 生产环境的一键启动不替代开发联调；需要看单一消费者问题时仍应回到单独 worker 启动方式