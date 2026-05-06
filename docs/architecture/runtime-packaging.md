# 运行时与打包架构

## 文档目的

本文档用于定义开发运行时、发布运行时、启动器和发行装配之间的关系，明确“开发阶段用 conda，发布阶段用同目录 Python 运行时”的整体架构方案。

本文档回答的问题是“运行时如何组织、发布包如何构成、哪些依赖进入发布包、哪些依赖必须单独交付”。

## 适用范围

- conda 开发环境与 bundled Python 发布运行时的分工
- runtimes、launchers、packaging 三层的职责边界
- 当前 `full` 发布目录的装配关系
- 发布包中的 Python、前端静态资源、插件和配置收敛方式
- 升级、回滚和兼容性管理边界

## 总体原则

- 开发环境使用 conda 管理，可复现且显式定义
- 发布与部署默认使用项目同目录 Python 运行时，不依赖目标机预装系统 Python
- 服务、worker、CLI 和维护脚本统一由 bundled Python 解释器启动
- 发布包尽量自带应用级依赖，但系统级 GPU 驱动、厂商运行时和操作系统组件单独列出
- 当前先固定一套 `full` 发布结构；后续如需推理专用目录，优先从 `full` 目录复制后手工裁剪依赖与 Python 运行时

## 三层结构

### 1. 开发运行时

- 由 conda 环境定义、锁定和复现
- 服务于本地开发、测试、类型检查和依赖迭代
- 不应直接成为最终发布包的隐式来源，而应通过显式构建流程导出发布依赖集合

### 2. 发布运行时

- 以同目录 Python 运行时为核心
- 包含 Python 解释器、应用依赖、项目代码、前端静态资源和必要插件
- 对目标机器表现为自包含应用运行时，而不是依赖系统 Python 的源码包

### 3. 装配层

- 当前只组装一个 `full` 发布目录
- 控制最终目录布局、交付形式、升级方式和验证步骤

## 运行时目录建议

```text
release/
├─ python/
├─ app/
├─ frontend/
├─ plugins/
├─ config/
├─ data/
├─ logs/
├─ manifests/
└─ launchers/
   ├─ service/
   ├─ worker/
   └─ maintenance/
```

## runtimes 目录在仓库中的职责

- 当前仓库里的 runtimes 目录主要包含 launchers 和 manifests 两部分；`python/` 目录在发行时只创建空目录，不在仓库里预置 bundled Python 内容。
- runtimes/launchers：统一服务、worker 和维护命令入口；当前仓库已经提供 Python 主逻辑 launcher，以及 bat/sh wrapper。
- runtimes/manifests：发布目录和 worker 职责拆分的清单；当前仓库已经提供 `full` release profile 与 worker profile。

## 当前真实状态

- 当前后端功能面已经可用，开发环境仍以 `python -m uvicorn backend.service.api.app:app --host 127.0.0.1 --port 8000` 这类直接启动方式为主。
- `backend.maintenance.main assemble-release` 当前会生成 `release/full/` 目录，复制完整 backend 代码、配置、launcher、manifest，并把仓库根目录的 `requirements.txt` 复制到发行目录。
- 当前 `python/` 目录只会被创建为空目录，后续 bundled Python 需要手工复制进去。
- 因此，当前 runtimes 已经具备“完整代码不裁剪、直接得到一个完整发布目录”的装配骨架，但 Python 运行时本体仍由后续手工落盘。

## 启动器设计

### service launcher

- 负责启动 backend-service 服务进程
- 必须强制使用同目录 bundled Python
- 负责补齐 `PYTHONPATH`、加载配置、校验依赖并输出最小启动日志

### worker launcher

- 负责启动训练、推理、转换和流程 worker
- 当前通过 `config/backend-worker.json` 的 `task_manager.enabled_consumer_kinds` 或 `runtimes/manifests/worker-profiles/*.json` 派生不同 worker 组合
- 不允许隐式回退到系统 Python

### maintenance launcher

- 负责健康检查、版本显示、迁移检查、插件扫描和环境诊断
- 应作为安装后验证和升级前检查的标准入口
- 当前仓库已经提供最小 `version`、`show-config`、`validate-layout` 和 `assemble-release` 命令入口

## 发布包必须包含的内容

- bundled Python 解释器与应用依赖
- backend 服务代码与 worker 代码
- frontend 构建产物
- 默认配置模板与运行时 manifest
- 可选的基础插件和插件目录结构
- 启动器与维护工具

## 发布包不默认包含的内容

- GPU 驱动程序
- 厂商推理运行时的系统级安装器
- 操作系统级通信中间件
- 现场专有证书、密钥和客户定制配置

## 打包流水线建议

1. 从 conda 开发环境导出可审核的依赖基线
2. 生成面向 bundled Python 的依赖集合和兼容性 manifest
3. 收敛 backend、frontend、plugins 和默认配置
4. 生成服务、worker 和维护脚本的统一入口
5. 通过 `assemble-release` 生成 `full` 发布目录
6. 执行最小启动验证、插件扫描和接口健康检查

## 当前装配结果

- 当前对应 manifest：`runtimes/manifests/release-profiles/full.json`
- 发布目录默认包含 backend-service、全部 worker profile、前端目录、插件目录、配置目录、数据目录、日志目录和空的 `python/` 目录
- 如果后续需要推理专用目录，建议从 `release/full/` 复制一份后再手工调整 `requirements.txt`、`python/` 和不需要的 worker launcher

## 兼容性管理

- Python 版本、关键依赖版本和目标平台兼容性必须写入 runtime manifest
- 插件兼容性、模型兼容性和运行时 profile 兼容性应统一记录
- 不同发布形态的差异应通过装配 manifest 管理，而不是靠人工记忆

## 升级与回滚原则

- 升级应以整个发布包或版本目录切换为单位进行
- bundled Python、插件版本和前端资源应随版本一起切换
- 业务配置和数据目录应尽量独立于应用目录，避免升级覆盖
- 回滚应恢复到上一个完整版本目录，而不是仅回退单个 Python 包

## 验证要求

- 服务启动必须验证使用的是 bundled Python
- worker 启动必须验证队列连接、插件目录和运行时依赖
- 发布包必须验证前端静态资源可访问、REST 健康检查可用、WebSocket 可订阅
- 如启用 ZeroMQ，还应验证本地 IPC 通道和端点权限

## 推荐后续文档

- [docs/deployment/bundled-python-deployment.md](../deployment/bundled-python-deployment.md)
- [docs/deployment/backend-worker-startup.md](../deployment/backend-worker-startup.md)
- [docs/deployment/backend-maintenance.md](../deployment/backend-maintenance.md)
- [docs/deployment/runtime-profiles.md](../deployment/runtime-profiles.md)
- [docs/architecture/backend-service.md](backend-service.md)
- [docs/architecture/system-overview.md](system-overview.md)