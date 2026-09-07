# 源码开发

本目录保存可重复执行的开发、检查和迁移门禁。系统设计见 [架构](../architecture/README.md)，完整启动顺序见 [开发环境](../deployment/development-environment.md)。

## 验收与基准

- [Workflow 公开错误契约实施基线](workflow-public-error-contract-implementation.md)：统一 HTTP、Runtime、Preview、Trigger、Runtime 显示和 .NET SDK 的公开错误对象，并收紧输入校验敏感信息回显；尚未实现。
- [LocalMessage 通道验收](local-message-channel-implementation.md)：三条结构化链路已迁移，本机压力与发行装配已完成；目标发行 24 小时混合 soak 待验收。
- [LocalBuffer 与 Trigger 数据面验收](shared-memory-data-plane-reliability-implementation.md)：固定 arena、guard/owner 与真实图片链路的故障、容量和持续认证。
- [LocalMessage 阶段 0 基线](local-message-channel-stage0-baseline.md)：迁移前历史测量、冻结 profile 与复测方法，不代表当前运行拓扑。
- [模型验证](model-validation.md)：真实模型、训练、转换和部署矩阵。

## 已实现能力的正式说明

已完成计划的稳定内容已整理到架构专题，不在本目录重复维护实施顺序：

- [Task 执行、暂停与终态](../architecture/platform/task-execution.md)
- [Workflow App 输入契约](../architecture/workflows/app-inputs.md)
- [Workflow 参数输入](../architecture/workflows/parameter-inputs.md)
- [Workflow 说明节点](../architecture/workflows/note-nodes.md)
- [Runtime 显示与 App Mode](../architecture/workflows/runtime-display.md)
- [目录变化 Trigger](../architecture/workflows/directory-watch-trigger.md)
- [本机共享内存 Trigger](../architecture/workflows/local-shared-memory-trigger.md)
- [工业视觉与集成节点](../architecture/workflows/industrial-nodes.md)

## 环境

```powershell
conda activate amvision
python -c "import sys; print(sys.version); print(sys.executable)"
python -m pip install -r requirements.txt

Set-Location frontend/web-ui
npm ci
Set-Location ../..
```

项目基线为 Python 3.12+；Node.js 版本以 `frontend/web-ui/package.json` 为准。源码不能依赖系统 Python 的隐式状态。

## 启动选择

- API/UI 局部调试：Alembic、Uvicorn、Vite。后台任务不会推进。
- 完整业务链路：Alembic、inference daemon、backend-service、源码 Worker Supervisor、Vite。

开发环境不组装或进入 `release/`。完整命令按顺序列在 [开发环境启动](../deployment/development-environment.md)。

## 后端检查

目录文件节点的边界和可重复执行的真实数据验证命令见 [Workflow 本地文件选择与读取](../architecture/workflows/local-file-reading.md)。

```powershell
python -m ruff check backend custom_nodes tests
python -m pytest --collect-only -q
python -m pytest
```

Python 检查边界见 [Python 代码检查](python-code-checks.md)，模型链路的分层验收见 [模型验证](model-validation.md)。

## 前端检查

```powershell
Set-Location frontend/web-ui
npm run typecheck
npm run test:unit
npm run build
npm run test:e2e
Set-Location ../..
```

## 数据库迁移

```powershell
python -m alembic -c backend/alembic.ini upgrade head
python -m alembic -c backend/alembic.ini current
python -m alembic -c backend/alembic.ini check
```

schema 变化必须带 Alembic revision，并验证空库、真实历史形态、数据保留、索引、外键和 downgrade 边界。默认 SQLite，迁移必须兼容 MySQL/PostgreSQL。Workflow App 版本迁移的跨库门禁见 [跨数据库迁移](workflow-app-version-cross-database-migrations.md)。

## 临时目录

pytest 默认使用 `.tmp/pytest` 与 `.tmp/pytest-cache`。长链或并发测试使用 `.tmp/<task-name>` 隔离；只删除已经确认没有进程使用的准确子目录，不递归清空整个 `.tmp/`。

## 维护规则

- 本目录不保存日期化测试结果、具体 task id、客户数据审计或一次性会话记录。
- 经 ADR 接受且跨越多个专题的实施基线可以暂存于本目录，但必须明确当前状态、不可变边界、阶段门禁和完成后的删除条件。
- 稳定的模型支持范围进入 [参考资料](../reference/README.md)。
- 稳定的 Workflow 编辑器边界进入 [Workflow 编辑器架构](../architecture/workflows/editor.md)。
- `projectsrc/` 对照结论可用于实现审计，但不能替代本项目契约。
