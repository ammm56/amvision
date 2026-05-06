# 部署文档目录

## 文档目的

本目录用于存放开发环境、运行时、安装、打包、发布和排障相关文档。

## 当前文档

### 开发环境

- [docs/deployment/development-environment.md](development-environment.md)：开发环境的目录、启动顺序和建议阅读路径
- [docs/deployment/backend-service-startup.md](backend-service-startup.md)：backend-service 的开发态启动、健康检查、schema 初始化和当前限制
- [docs/deployment/backend-worker-startup.md](backend-worker-startup.md)：独立 backend-worker 的启动、consumer lane 配置和最小验收方式
- [docs/deployment/backend-maintenance.md](backend-maintenance.md)：backend-maintenance CLI 入口、命令和 launcher 调用方式

### 生产环境

- [docs/deployment/production-environment.md](production-environment.md)：生产环境的 release 组装、目录职责、根目录一键启动和排障入口
- [docs/deployment/runtime-profiles.md](runtime-profiles.md)：当前 `full` 发布目录、launcher 和默认 worker 拓扑
- [docs/deployment/bundled-python-deployment.md](bundled-python-deployment.md)：同目录 Python 运行时的安装、升级、回滚和验收方案
- [docs/deployment/full-first-deploy-checklist.md](full-first-deploy-checklist.md)：`release/full/` 首次部署时的 layout、health、docs 和 smoke test 顺序

## 建议内容

- 先区分开发环境与生产环境，再进入细分专题
- 开发环境优先说明 conda、仓库根目录启动和调试入口
- 生产环境优先说明 release 组装、bundled Python、根目录一键启动和首次验收
- 安装检查、升级、回滚和排障说明保持在生产环境分组下

## 存放规则

- 部署步骤与架构背景分开书写
- 能执行的命令、目录和验证步骤优先直接放入本目录
- 额外系统依赖必须单独列出用途、版本边界和验证方法