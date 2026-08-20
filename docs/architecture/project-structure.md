# 项目结构

## 组织原则

仓库采用模块化单体与独立执行器。顶层按平台职责划分，模型内部再按模型家族与任务拆分。依赖方向保持：

```text
API -> Application -> Domain <- Infrastructure
               │
               ├─ Contracts
               ├─ QueueBackend -> Workers
               └─ Runtime manager -> independent process
```

`projectsrc/` 只用于开发期参考核对，不能成为生产 import、公开字段来源或发行包依赖。

## 顶层目录

| 目录 | 职责 |
|---|---|
| `backend/` | 后端服务、领域、任务、Worker、推理 daemon 和维护命令 |
| `frontend/web-ui/` | Vue 3 + TypeScript + Vite 前端 |
| `custom_nodes/` | 可安装 Node Pack 与自定义节点实现 |
| `config/` | 可提交的默认配置和 profile |
| `runtimes/` | 发布启动器、bundled runtime 输入和本地厂商 runtime 资产 |
| `sdks/` | 对外 SDK、schema 和契约测试 |
| `docs/` | 当前架构、API、开发、部署、运维和设计资料 |
| `tests/` | 后端、集成、迁移和 E2E 测试 |
| `data/` | 本地开发数据库和 ObjectStore 数据，不作为源码 |
| `release/` | assemble-release 生成结果，不手工维护 |
| `projectsrc/` | 第三方参考源码，仅供审计 |

`.tmp/`、cache、日志、模型权重和本地 runtime 二进制是开发/运行产物，不进入长期源码结构。

## Backend

```text
backend/
├─ alembic/           schema migration
├─ bootstrap/         进程启动前后的公共装配
├─ contracts/         版本化 payload、数据集和节点契约
├─ inference_daemon/  独立 Deployment 控制进程
├─ maintenance/       迁移、发行组装和离线检查
├─ nodes/             核心节点及执行支持
├─ queue/             QueueBackend 与本地持久队列
├─ service/           FastAPI 控制面和业务分层
└─ workers/           六类后台任务 Profile 与 Runner
```

### backend/service

```text
backend/service/
├─ api/              FastAPI app、REST、WebSocket、deps、middleware
├─ application/      用例、状态机、事务和进程控制
├─ domain/           领域记录、Repository/UoW 协议和不变量
└─ infrastructure/   SQLAlchemy、ObjectStore、文件、集成和 adapter
```

- API 只处理协议、鉴权和 contract 映射；
- Application 组织用例和事务，不依赖数据库方言；
- Domain 不依赖 FastAPI、SQLAlchemy 实体或具体文件系统；
- Infrastructure 实现 Repository、Unit of Work 和外部边界。

### backend/service/application

| 目录 | 职责 |
|---|---|
| `datasets/` | 导入、导出、版本和格式处理 |
| `models/` | 模型 core、训练、验证、导出、registry 和 catalog |
| `runtime/` | Deployment session、predictor、target 和序列化 |
| `workflows/` | Preview、App Version、Runtime、Worker 和 Trigger |
| `tasks/` | Task 状态、事件、取消和查询 |
| `local_buffers/` | LocalBufferBroker client/supervisor/process |
| `deployments/` | Deployment 应用服务 |
| `auth/` | 本地用户、token、scope 和 session |
| `events/` | service event bus |
| `sdk_config_packages/` | SDK 配置包生成 |

### 模型 core

`backend/service/application/models/` 的长期边界：

- `yolox_core/`
- `yolov8_core/`
- `yolo11_core/`
- `yolo26_core/`
- `rfdetr_core/`
- `yolo_core_common/`（仅放三个 Ultralytics YOLO 家族真正共享且不分支判断模型类型的实现）
- `training/`、`validation/`、`evaluation/`、`export/`、`inference/`（应用服务边界）
- `catalog/`、`registry/`（模型目录、版本、构建和能力查询）

模型结构、loss、matcher、checkpoint 映射和 export forward 属于对应 `*_core`。任务提交、ObjectStore、队列、ModelVersion/ModelBuild 登记属于外层应用服务和 Worker。

### Deployment Runtime

`backend/service/application/runtime/` 只处理发布后的加载和长期运行：

- `deployment/`：进程监督、事件和 runtime pool；
- `predictors/`：PyTorch、ONNXRuntime、OpenVINO、TensorRT session 包装；
- `targets/`：ModelVersion/Build 到 runtime target 的解析；
- `contracts/`、`serialization/`：执行期输入输出；
- `tasks/`：异步推理任务编排；
- `io/`、`support/`：数据面和共享支持。

predictor 不包含训练循环、loss 或模型核心结构；model core 不依赖 deployment supervisor、CUDA buffer pool 或 HTTP contract。

## Workers 与 Daemon

- `backend/workers/`：dataset-import、dataset-export、training、validation、conversion、batch-inference Profile；
- `backend/inference_daemon/`：独立 deployment 控制/推理进程入口；
- Workflow Runtime worker 位于 `backend/service/application/workflows/worker/`，由 backend-service manager 管理；
- full Supervisor 位于 `runtimes/launchers/full/start_amvision_full.py`。

Worker 只消费任务并调用 Runner，不拥有公开 API。backend-service 不消费后台队列。

## Frontend

```text
frontend/web-ui/src/
├─ app/         app bootstrap、router、全局 provider
├─ config/      navigation 和前端配置
├─ modules/     projects、tasks、datasets、models、deployment 等业务模块
├─ workflows/   Workflow 列表、详情和编辑器
├─ platform/    runtime config、i18n、auth/session 基础能力
├─ shared/      API client、生成 contract、通用 UI 和 WebSocket
├─ shells/      workbench 外壳
├─ views/       系统级页面
└─ lib/         内置第三方或底层图编辑库边界
```

新增页面优先进入对应业务模块；跨模块组件进入 `shared` 前必须确有稳定复用。前端不并行引入 React/Angular。

## Custom Nodes

`custom_nodes/<pack>/` 是最小分发单元：

```text
<pack>/
├─ manifest.json
├─ workflow/catalog.json
├─ backend/entry.py
├─ backend/nodes/
├─ backend/runtime/
└─ assets/ or docs/ (optional)
```

Node Pack 必须声明 version、capabilities、config schema、timeout 和 enabledByDefault。场景化协议、硬件桥接、行业规则和大型开放词汇/分割扩展优先放入 Node Pack，不膨胀核心平台。

## Docs

```text
docs/
├─ architecture/  当前系统结构和不变量
├─ api/           公开契约与调用示例
├─ development/   开发、测试和专项验证
├─ deployment/    发行组装和启动
├─ operations/    健康、日志和恢复
├─ nodes/         Node Pack 扩展文档
├─ decisions/     ADR
├─ design/        产品与视觉规范
├─ examples/      可复用示例
└─ legal/         第三方来源和许可证
```

已完成计划不继续作为单独文档保留；稳定结论合并到对应专题。

## 依赖硬规则

- route 不直接访问 ORM 或磁盘；
- application/domain 不写方言 SQL；
- Worker/Runtime 不 import API route；
- `projectsrc/` 不进入生产 import；
- `release/full/app/` 不作为源码修改；
- custom node 不替代 ModelVersion、DatasetVersion、Deployment 或 Runtime 等核心资源；
- 大图片跨进程使用 LocalBuffer/ObjectStore 引用，不进入通用 JSON 大对象；
- 对外 contract 只来自 `backend/contracts`、OpenAPI、Node Catalog 或 SDK schema。
