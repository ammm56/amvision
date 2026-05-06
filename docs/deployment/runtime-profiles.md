# full 发布目录

## 文档目的

本文档用于说明当前仓库已经落地的 `full` 发布目录，包括目录结构、worker profile、launcher、release 组装命令和运维建议。

## 当前仓库落点

- profile manifest：`runtimes/manifests/release-profiles/full.json`
- worker profile：`runtimes/manifests/worker-profiles/*.json`
- service launcher：`runtimes/launchers/service/start_backend_service.py`
- worker launcher：`runtimes/launchers/worker/start_backend_worker.py`
- maintenance launcher：`runtimes/launchers/maintenance/invoke_backend_maintenance.py`
- release 组装入口：`python -m backend.maintenance.main assemble-release --profile-id full`

## 共用约定

- 当前只提供一个 `full` 发布目录，`backend-service` 不托管任何队列消费者，队列执行统一交给独立 worker profile
- `runtimes/launchers/` 和 `runtimes/manifests/` 是仓库内的模板来源；`assemble-release` 会把运行时必需内容复制到 `release/full/launchers/` 和 `release/full/manifests/`
- 发布根目录会额外生成 `start-amvision-full.*` 和 `stop-amvision-full.*`，作为生产环境默认的整套启动与停止入口
- 发布目录优先通过 bundled Python 启动 Python launcher；Windows 使用 bat wrapper，Linux 使用 sh wrapper
- 发布目录保留 maintenance launcher，用于版本输出、配置查看、布局校验和 release 组装
- 发布目录复制完整项目代码，不做源码裁剪；推理专用变体由复制 `full` 目录后手工修改 `requirements.txt` 和 `python/` 完成

## 当前默认行为

- `hosted_task_manager_enabled=false`
- worker 默认拆成 `dataset-import`、`dataset-export`、`training`、`conversion`、`evaluation`、`inference` 六个独立 profile
- 发布目录名默认为 `release/full/`
- 发行目录中的 `python/` 只创建空目录，Python 解释器与依赖由后续手工复制
- 可选启用本地 ZeroMQ 作为内部 IPC 补充

## 推荐启动顺序

1. 先执行 maintenance `validate-layout`
2. 在 `release/full/` 根目录执行 `start-amvision-full.bat` 或 `start-amvision-full.sh`
3. 检查 health、OpenAPI 文档和目标业务 smoke test
4. 如需排障，再拆回独立 service / worker launcher

完整的一页执行顺序见 [docs/deployment/full-first-deploy-checklist.md](full-first-deploy-checklist.md)。

默认的一键启动入口见 [docs/deployment/production-environment.md](production-environment.md)。

## 运维重点

- 核对 bundled Python 体积与磁盘空间
- 核对厂商 runtime、驱动和目标设备兼容性
- 核对各 worker profile 是否与现场职责匹配

## 当前建议

1. 开发联调继续可以在仓库根目录直接运行 launcher，并显式传入 conda Python 路径。
2. 发布打包时应优先通过 `assemble-release` 生成 `release/full/`，不要再手工拼接 launcher 和 manifest。
3. 如果要做推理专用变体，直接复制 `release/full/`，再手工调整 `app/requirements.txt` 与 `python/` 即可。
4. 发布验收优先跑 `launchers/maintenance/invoke_backend_maintenance.py -- validate-layout`、service health、目标 worker profile smoke test，再做业务联调。