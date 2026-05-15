# release/full/ 首次部署检查清单

## 文档目的

本文档用于把 `release/full/` 的首次部署验收步骤收敛到一页，按顺序覆盖 layout、service、worker、health、OpenAPI 文档和最小任务 smoke test。

## 适用范围

- 已通过 `assemble-release` 生成 `release/full/`
- 已手工准备 `python/` 目录
- 需要在一台新机器或新目录上完成首次可运行验证

## 执行前提

- 当前工作目录切到 `release/full/`
- `python/` 下已经存在可执行 Python，并已安装 `app/requirements.txt` 中的依赖
- `config/backend-service.json`、`config/backend-worker.json` 已按现场路径和端口要求检查过一遍
- 准备一个体积较小的 zip 数据集样本，用于 DatasetImport smoke test

## 0. 目录快照检查

先确认下面这些路径已经存在：

- `app/backend`
- `app/requirements.txt`
- `config/backend-service.json`
- `config/backend-worker.json`
- `launchers/maintenance/invoke-backend-maintenance.bat`
- `start-amvision-full.bat`
- `start_amvision_full.py`
- `stop-amvision-full.bat`
- `stop_amvision_full.py`
- `manifests/release-profiles/full.json`
- `manifests/worker-profiles/dataset-import.json`
- `python/python.exe`

如果目录结构不完整，先停止后续步骤，回到 release 组装阶段排查。

## 1. 先跑 layout 校验

```powershell
.\launchers\maintenance\invoke-backend-maintenance.bat -- validate-layout --output text
```

通过标准：

- `config`、`data`、`launchers`、`manifests/release-profiles`、`manifests/worker-profiles` 都能被识别
- 不出现缺目录、缺 manifest 或 Python 入口找不到的报错

如果这一步失败，优先检查：

- 当前终端工作目录是否就是 `release/full/`
- `python/` 是否已经放到正确位置
- `launchers/`、`manifests/` 是否来自同一次 `assemble-release`

## 2. 启动 backend-service

默认推荐直接执行 full 根目录一键启动，而不是手工分开起 service 和 worker。

在第一个终端执行：

```powershell
.\start-amvision-full.bat
```

通过标准：

- 根启动脚本保持常驻，不立即退出
- 控制台先输出 backend-service 和多个 worker 的 pid 与日志路径
- `logs/full-stack/` 下出现 `service.log` 和各 worker log

当前 service 只承担控制面，不消费任务队列；一键启动脚本会把 full profile 里的 worker 一起拉起。

## 3. 检查 health

在第二个终端执行：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/v1/system/health
```

预期结果示例：

```json
{
  "status": "ok",
  "request_id": "..."
}
```

如果 health 不通，先只排查 service：

- 端口是否被占用
- `config/backend-service.json` 是否指向了无权限路径
- SQLite 文件和 `data/` 目录是否可写

## 4. 检查 OpenAPI 文档

在浏览器打开：

- `http://127.0.0.1:8000/docs`
- `http://127.0.0.1:8000/openapi.json`

通过标准：

- Swagger UI 能正常打开
- OpenAPI JSON 能返回 200
- `POST /api/v1/datasets/imports`
- `GET /api/v1/tasks/{task_id}`
- `GET /api/v1/tasks/{task_id}/events`

都已经出现在文档里。

## 5. 确认 worker 已经被一键启动脚本拉起

当前 full 根目录脚本会默认拉起 release manifest 中声明的全部 worker。

通过标准：

- `logs/full-stack/worker-dataset-import.log` 已经生成
- `logs/full-stack/worker-inference.log` 等其他目标 worker log 已经生成
- 根启动脚本控制台没有出现 worker profile 缺失、队列目录不可写或配置解析错误

如果需要定位某一个 worker 的问题，再临时拆回独立启动方式，例如：

```powershell
.\launchers\worker\start-dataset-import-worker.bat
```

## 6. 执行最小任务 smoke test

推荐先做 DatasetImport，因为它同时覆盖文件上传、正式 TaskRecord 建立、队列落盘和 worker 消费。

如果当前数据库为空，服务首次启动会自动初始化默认本地用户；初始化数据由启动期默认用户初始化器写入数据库，不在 backend-service.json 中配置。执行 smoke test 时应填写当前环境实际 Bearer token。

### 方案 A：直接用 Swagger UI

在 `http://127.0.0.1:8000/docs` 中调用 `POST /api/v1/datasets/imports`，至少填写：

- header：`Authorization=Bearer <token>`
- form：`project_id=project-1`
- form：`dataset_id=dataset-1`
- form：`task_type=detection`
- form：`package=<一个 zip 文件>`

### 方案 B：直接用 curl

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/datasets/imports" \
  -H "Authorization: Bearer <token>" \
  -F "project_id=project-1" \
  -F "dataset_id=dataset-1" \
  -F "task_type=detection" \
  -F "package=@sample.zip"
```

通过标准：

- 返回 `202 Accepted`
- 响应里能拿到 `dataset_import_id`
- 响应里能拿到 `task_id`
- `processing_state=queued`

## 7. 跟踪任务状态

拿到上一步返回的 `task_id` 后，继续查询：

- `GET /api/v1/tasks/{task_id}`
- `GET /api/v1/tasks/{task_id}/events`
- `GET /api/v1/datasets/imports/{dataset_import_id}`

建议检查顺序：

1. 先看 `GET /api/v1/tasks/{task_id}`，确认任务是否从 `queued` 进入 `running` 或 `succeeded`
2. 再看 `GET /api/v1/tasks/{task_id}/events`，确认 worker 已经写入事件流
3. 最后看 `GET /api/v1/datasets/imports/{dataset_import_id}`，确认导入状态不再停留在 `received`

通过标准：

- 任务状态至少能从 `queued` 推进到 `running`
- 正常情况下最终进入 `succeeded`，DatasetImport 进入 `completed`

如果任务一直停在 `queued`，优先检查：

- `start-amvision-full.bat` 所在终端是否仍在运行
- `logs/full-stack/worker-dataset-import.log` 是否出现启动异常
- `data/queue` 是否在 service 与 worker 之间共用同一目录
- `config/backend-worker.json` 是否被本地覆盖文件改掉了队列路径

## 8. 首次验收通过标准

下面五项同时满足时，可认为 `release/full/` 首次部署通过最小验收：

1. `validate-layout` 通过
2. `start-amvision-full.bat` 常驻运行且 health 返回 `status=ok`
3. `/docs` 和 `/openapi.json` 正常可访问
4. full profile 中需要的目标 worker 已由根启动脚本拉起
5. 至少一个 DatasetImport 任务成功经历提交、入队、消费和状态推进

## 9. 停止整套进程

验收完成后，如果需要从另一个终端回收整套进程，执行：

```powershell
.\stop-amvision-full.bat
```

通过标准：

- stop 命令执行后，`start-amvision-full.bat` 所在终端退出
- `logs/full-stack/runtime-state.json` 被清理
- backend-service 和各 worker 不再继续写入对应日志文件

## 后续文档入口

- service 启动细节：`backend-service-startup.md`
- worker 启动细节：`backend-worker-startup.md`
- maintenance 命令：`backend-maintenance.md`
- full 发布目录结构：`runtime-profiles.md`
- DatasetImport 接口字段：`../api/datasets-imports.md`