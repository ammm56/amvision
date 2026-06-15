# 当前阶段总结与下一步路线

## 文档目的

本文档用于把当前主干的阶段判断、已完成能力和下一阶段主线任务收敛成一份稳定说明，作为 `current-implementation-status.md` 的补充。

本文档重点回答两个问题：

- 当前项目已经从“功能打样”推进到了什么阶段
- 接下来应优先把时间投入到哪些收口项

## 适用范围

- 当前阶段整体判断
- 已经落地的能力范围
- 本轮已经收口的发布与运行时改动
- 下一阶段的五条主线
- 当前固定开发环境与最小回归入口

## 当前阶段判断

当前项目已经明显越过“平台骨架搭建阶段”，进入“第一版平台闭环已经成型，下一步转向交付硬化和平台化泛化”的阶段。

当前最重要的事实不是“目录很多”，而是下面这些能力已经同时成立：

- backend-service、独立 worker、workflow runtime、deployment supervisor、custom node、浏览器工作台和 SDK 已经形成完整平台骨架
- 以 YOLOX 为中心的训练、人工验证、评估、转换、部署、同步推理和异步推理闭环已经打通
- REST、WebSocket、workflow preview-runs、app-runtimes、runs、trigger-sources、node pack 管理等公开资源面已经成型
- 前端工作台已经具备项目、任务、数据集、模型、部署、推理、workflow、节点和设置等主要模块

因此，下一阶段不应继续以“补单个 YOLOX 功能”为主，而应转向下面三类目标：

- 把已经可用的能力变成可稳定交付的完整发布包
- 把当前回归路径收口成固定入口，减少对个人机器状态的依赖
- 把 YOLOX 当前实现继续抽象成平台接口，而不是长期保留为唯一实现

## 当前已完成范围

### 平台主干

- `backend/service/` 已承担统一 REST / WebSocket 控制面、workflow runtime manager、deployment supervisor 和公开资源路由
- `backend/workers/` 已拆成 dataset-import、dataset-export、training、conversion、evaluation、inference 六类消费者
- `backend/nodes/` 与 `custom_nodes/` 已形成 core nodes + node pack 的双层节点体系
- `frontend/web-ui/` 已具备工作台骨架、模块路由、workflow editor 和基础业务页面

### 模型与运行时

- YOLOX 训练、验证、评估、转换、部署和推理链路已经全部落地
- 已支持 PyTorch、ONNX Runtime、OpenVINO、TensorRT 多种运行时组合
- DatasetExport 已经成为训练与评估的正式输入边界

### workflow 与扩展

- workflow 资源面已经拆成 templates、applications、execution-policies、preview-runs、app-runtimes、runs、trigger-sources
- LocalBufferBroker、PublishedInferenceGateway、deployment runtime 与 workflow runtime 的边界已经形成
- node pack 已经具备 manifest、依赖检查、启停、catalog 汇总和 loader 状态观察能力

## 本轮已收口的事项

本轮对“发布闭环”和“固定入口”先做了第一批实改，不再只停留在文档建议层。

### release 组装

- `backend/maintenance/release_assembly.py` 已从“只创建空 frontend / python 目录”改为：
  - 复制 `frontend/web-ui/dist/` 到 `release/<profile_id>/frontend/`
  - 缺少 `runtime-config.json` 时自动从运行时配置文件或模板生成
  - 覆盖发布时保留并回迁现有 `release/<profile_id>/python/`
  - 发布中途失败时恢复原有 `python/` 目录，避免 bundled Python 丢失

### maintenance 入口

- `backend/maintenance/main.py` 当前会把 maintenance 配置里的前端 dist 来源传给 `assemble-release`，并继续支持显式指定 bundled Python 来源目录
- `validate-layout` 在 release 目录下会额外检查：
  - `app/backend`
  - `app/requirements.txt`
  - `custom_nodes`
  - `frontend/index.html`
  - `frontend/runtime-config.json`
  - `python/python.exe` 或等价 Python 入口

### 前端发布访问

- `backend/service/api/app.py` 当前在检测到前端构建产物时，会直接托管浏览器端静态资源，并为单页路由提供 `index.html` 回退
- 这使 `release/full/frontend/` 不再只是“被复制进去的文件夹”，而成为 backend-service 可以直接对外提供的正式发布资产

## 当前固定开发环境与最小入口

### 当前标准开发环境

- conda 环境名：`amvision`
- 当前 Windows 目标开发机默认 Python：`D:\software\anaconda3\envs\amvision\python.exe`
- 手动终端调试可以先 `conda activate amvision` 后使用 `python`
- 自动化回归、Codex 执行命令和需要避免环境串错的调试命令优先使用显式解释器路径
- pytest 默认临时目录已经固定为仓库根目录 `.tmp/pytest`，常规测试不需要再手写 `--basetemp`

### 当前最小开发入口

- backend-service：
  - `python -m uvicorn backend.service.api.app:app --host 127.0.0.1 --port 8000 --reload`
- backend-worker：
  - `python -m backend.workers.main`
- maintenance：
  - `python -m backend.maintenance.main validate-layout --output text`
  - `python -m backend.maintenance.main assemble-release --profile-id full --release-root ./release --force --output text`

### 当前最小回归入口

- release 组装与 maintenance 基线：
  - `python -m pytest tests/test_release_assembly.py tests/test_bootstrap_chains.py tests/test_api_dependency_chain.py::test_create_app_mounts_frontend_static_files_with_spa_fallback`
- 后端测试收集：
  - `python -m pytest --collect-only -q`
- 前端单测：
  - `cd frontend/web-ui`
  - `npm run test`
- 前端构建：
  - `cd frontend/web-ui`
  - `npm run build`

更细的开发命令和部署顺序继续放在 `docs/deployment/`，本文档只保留阶段级入口。

## 下一阶段五条主线

### 1. 完成完整发布闭环

目标不是“能生成 release 目录”，而是“release/full/ 可以直接作为可交付目录”。

下一步应继续补齐：

- clean machine 上的完整发布验证
- `release/full/frontend/` 与 backend-service 静态托管的联调验收
- `runtime-config.json` 的现场生成、覆盖和回滚规则
- `python/`、`frontend/`、`custom_nodes/`、`config/` 的版本一致性检查

### 2. 固化标准运行环境和回归入口

下一步要把当前运行依赖从“知道怎么跑的人能跑”收口成“固定命令能跑”。

优先事项：

- 把 conda 开发环境、同目录 Python 运行时、依赖安装和最小 smoke test 收口成稳定文档与脚本入口
- 把后端回归、发布回归、前端构建、前端单测、最小端到端验收整理成固定顺序
- 让 `validate-layout`、`assemble-release`、`health`、最小任务 smoke test 成为统一验收链

### 3. 补齐运行时回归矩阵

当前运行时组合已经不少，但还缺统一回归基线。

下一步应建设：

- PyTorch / ONNX Runtime / OpenVINO / TensorRT 的 smoke test
- 训练、转换、部署的精度回归数据
- 时延、吞吐、warmup、restart 和 keep_warm 的 benchmark 视图
- Conversion report、evaluation report、deployment benchmark 的统一结构

### 4. 提升前端自动化测试深度

当前前端功能面已基本够用，但自动化验证仍偏浅。

下一步优先覆盖：

- 自动进入、退出后登录、403、离线和权限裁剪
- 任务列表与详情
- 部署启动、停止、warmup、health
- workflow preview-run、app-runtime、run 的主链路
- 登录、任务详情、部署控制、workflow 主流程的 Playwright 端到端回归

### 5. 从 YOLOX 实现走向平台接口

YOLOX 当前已经是完整样板，下一步要把样板继续抽象成平台。

重点包括：

- 继续收稳 `ModelRuntime`
- 继续抽象 `TrainingBackend`
- 继续抽象 `ConversionBackend`
- 收口 workflow service node 与任务系统的边界
- 强化 node pack 的权限、依赖、版本、禁用、回滚和兼容性规则

目标是让 YOLOX 成为第一套完整实现，而不是唯一实现。

## 下一阶段执行顺序建议

建议按下面顺序推进，避免同时铺太多战线：

1. 先完成发布闭环验收和固定命令收口
2. 再补运行时 smoke test、benchmark 和回归报告
3. 再补前端 E2E 和发布后的浏览器端验收
4. 最后进入多模型平台抽象和更强的 node pack 约束

这个顺序的核心理由是：先把已有能力稳定交付，再继续抽象平台，会比一边缺交付闭环一边扩新抽象更稳。
