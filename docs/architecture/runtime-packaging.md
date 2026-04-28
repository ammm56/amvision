# 运行时与打包架构

## 文档目的

本文档用于定义开发运行时、发布运行时、启动器和发行装配之间的关系，明确“开发阶段用 conda，发布阶段用同目录 Python 运行时”的整体架构方案。

本文档回答的问题是“运行时如何组织、发布包如何构成、哪些依赖进入发布包、哪些依赖必须单独交付”。

## 适用范围

- conda 开发环境与 bundled Python 发布运行时的分工
- runtimes、launchers、packaging 三层的职责边界
- standalone、workstation、edge 三类形态的装配关系
- 发布包中的 Python、前端静态资源、插件和配置收敛方式
- 升级、回滚和兼容性管理边界

## 总体原则

- 开发环境使用 conda 管理，可复现且显式定义
- 发布与部署默认使用项目同目录 Python 运行时，不依赖目标机预装系统 Python
- 服务、worker、CLI 和维护脚本统一由 bundled Python 解释器启动
- 发布包尽量自带应用级依赖，但系统级 GPU 驱动、厂商运行时和操作系统组件单独列出
- 运行时结构应保持 standalone、workstation、edge 之间尽可能一致，仅在装配层做差异化

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

- 根据 standalone、workstation、edge 的差异，组合不同的启动器、配置模板和可选插件
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

- runtimes/python/dev-conda：开发环境定义、锁定文件和复现说明
- runtimes/python/bundled：发布运行时结构模板、嵌入式 Python 布局和依赖清单
- runtimes/launchers：统一服务、worker 和维护命令入口
- runtimes/manifests：依赖、兼容性、运行时 profile 和发布校验信息

## 启动器设计

### service launcher

- 负责启动 backend-service 服务进程
- 必须强制使用同目录 bundled Python
- 负责加载配置、校验依赖并输出最小启动日志

### worker launcher

- 负责启动训练、推理、转换和流程 worker
- 可按角色或队列 lane 派生不同 worker 配置
- 不允许隐式回退到系统 Python

### maintenance launcher

- 负责健康检查、版本显示、迁移检查、插件扫描和环境诊断
- 应作为安装后验证和升级前检查的标准入口

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
5. 按 standalone、workstation、edge 形态装配差异化内容
6. 执行最小启动验证、插件扫描和接口健康检查

## 三类形态的差异化装配

### standalone

- 面向单机本地部署
- 默认包含 backend-service、worker、本地存储和前端静态资源
- 可启用本地 ZeroMQ 作为内部 IPC 补充

### workstation

- 面向工控机或上位机部署
- 强调局域网接入、现场工作台界面和集成端点协作
- 可按现场需求附带硬件桥接或协议插件

### edge

- 面向边缘或嵌入式场景
- 需要更严格的依赖裁剪、资源限制和插件选择
- 应通过 manifest 标明硬件能力与兼容性边界

## 兼容性治理

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
- [docs/architecture/backend-service.md](backend-service.md)
- [docs/architecture/system-overview.md](system-overview.md)