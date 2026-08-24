# 源码开发

本目录保存可重复执行的开发、检查和迁移门禁。系统设计见 [架构](../architecture/README.md)，完整启动顺序见 [开发环境](../deployment/development-environment.md)。

## 当前实施基线

- [任务执行与运行时可靠性实施基线](task-runtime-reliability-implementation.md)：阶段 1 至阶段 7 已完成，源码真实业务链路与发行基础设施已分别通过验收。该文档是 Task/Attempt、Training Resume、Conversion、完整前端 Task 状态和 Node Pack timeout 的唯一详细实施记录。

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
