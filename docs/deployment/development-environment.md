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

### worker 开发调试启动

全量默认 worker：

```powershell
python -m backend.workers.main
```

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