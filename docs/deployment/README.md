# 启动与部署

本目录区分源码开发启动和发行包生产启动。两者共享业务拓扑，但使用不同运行时、入口和前端形态，不能混用。

## 入口

| 场景 | 文档 |
| --- | --- |
| 从源码完整启动开发环境 | [开发环境](development-environment.md) |
| 组装并启动发行包 | [生产环境](production-environment.md) |
| backend-service 参数与健康检查 | [backend-service](backend-service-startup.md) |
| Worker Supervisor、Profile 和 Topology | [backend-worker](backend-worker-startup.md) |
| inference daemon | [inference daemon](inference-daemon.md) |
| 数据库迁移与维护命令 | [维护命令](backend-maintenance.md) |
| bundled Python | [同目录 Python](bundled-python-deployment.md) |
| 发布 profile 与目录 | [运行时 profile](runtime-profiles.md) |
| 新机器首次验收 | [首次部署清单](full-first-deploy-checklist.md) |

## 源码开发

开发环境使用 conda 中的 Python 和 Vite，不进入 `release/`：

```text
Alembic
  → inference daemon
  → backend-service（Uvicorn reload）
  → backend.workers.supervisor（六个 Profile）
  → Vite
```

完整命令与停止顺序见 [开发环境](development-environment.md)。只启动 Uvicorn 和 Vite 是 API/UI 局部调试，不是完整业务链路。

## 生产发行

生产使用 `assemble-release` 的输出和随包 Python；进入对应 `release/<profile-id>/` 后直接运行：

```powershell
.\start-amvision-full.bat
```

默认监听 `0.0.0.0:5600`。只有现场需要覆盖默认值时才显式传 `--host` 或 `--port`。完整步骤见 [生产环境](production-environment.md)。

## 日志

发行日志位于 `logs/full-stack/`，按本地日期追加：

- `database-migration-YYYYMMDD.log`
- `inference-daemon-YYYYMMDD.log`
- `backend-service-YYYYMMDD.log`
- `backend-worker-<profile>-YYYYMMDD.log`
- `runtime-state.json`

跨日写入新的日志文件，避免单文件无限增长。排障顺序见 [运维文档](../operations/README.md)。

## 边界

- 项目运行时只支持64-bit进程；当前正式发行profile为Windows x64。backend、worker、Broker、独立运行时和仓库内.NET SDK不提供32-bit兼容、容量协商或降级路径。
- backend-service 不消费后台队列。
- 源码开发由 `python -m backend.workers.supervisor` 注入 Worker Topology；不要直接运行低层 `backend.workers.main`。
- 生产由发行包 full Supervisor 管理 daemon、service 和 Worker Profile。
- 发行包不依赖系统 Python、conda、Node.js 或外网 CDN。
- `release/<profile-id>/` 是组装产物；代码修改发生在源码目录，然后重新组装。
