# 部署指南

本目录覆盖开发启动、发行包组装、bundled Python、首次部署和生产启动。当前正式发行目标为 Windows x64 CPU 和 Windows x64 NVIDIA。

## 选择入口

| 场景 | 文档 |
| --- | --- |
| 开发态 API/UI 或完整链路启动 | [开发环境启动](development-environment.md) |
| backend-service 参数与健康检查 | [backend-service 启动](backend-service-startup.md) |
| Worker Profile 与 Topology | [backend-worker Topology](backend-worker-startup.md) |
| inference daemon | [独立 inference daemon](inference-daemon.md) |
| maintenance 与数据库迁移 | [维护命令](backend-maintenance.md) |
| 发行包组装与生产启动 | [生产环境](production-environment.md) |
| 硬件 profile 和目录结构 | [发布 profile](runtime-profiles.md) |
| 同目录 Python | [bundled Python](bundled-python-deployment.md) |
| 新机器首次验收 | [首次部署清单](full-first-deploy-checklist.md) |

## 当前标准流程

### 开发

```text
conda 环境 → Alembic → backend-service/Vite 快速调试
                         或
前端 build → assemble-release → full Supervisor 完整链路
```

### 生产

```text
assemble-release
  → 准备 release/<profile-id>/python
  → validate-layout
  → start-amvision-full.bat
  → health / OpenAPI / 前端 / 业务 smoke
  → stop-amvision-full.bat
```

full Supervisor 是生产进程拓扑的唯一入口。它先迁移数据库，再启动 inference daemon、backend-service 和 release manifest 中的六个 Worker Profile。单个 Profile 退出时只恢复该 Profile。

## 日志

默认日志目录为 `logs/full-stack/`：

- `database-migration-YYYYMMDD.log`
- `inference-daemon-YYYYMMDD.log`
- `backend-service-YYYYMMDD.log`
- `backend-worker-<profile>-YYYYMMDD.log`
- `runtime-state.json`

日志按本地日期追加；跨日自动切换到新文件。现场排障见 [运维文档](../operations/README.md)。

## 边界

- `backend-service` 不包含队列消费者。
- Worker 低层 Python launcher 只供 full Supervisor 使用。
- 发布包不依赖系统 Python 或系统 Node.js；`python/` 与前端静态资源随发行目录管理。
- NVIDIA driver 和无法随包交付的系统依赖必须单独核对。
- `release/<profile-id>/` 是组装结果，源代码修改必须发生在仓库源目录，再重新组装。
