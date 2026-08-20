# 开发指南

本目录保存可重复执行的开发、测试和专项验证流程。开发环境启动与生产发行启动采用不同入口，不能混用。

## 1. 准备环境

从仓库根目录开始：

```powershell
conda activate amvision
python -c "import sys; print(sys.version); print(sys.executable)"
python -m pip install -r requirements.txt
```

项目基线为 Python 3.12+。开发代码不能依赖系统 Python 的隐式状态。

首次准备前端：

```powershell
Set-Location frontend/web-ui
npm ci
Set-Location ../..
```

前端要求 Node.js 24.15+，具体版本约束以 `frontend/web-ui/package.json` 为准。

## 2. 选择启动模式

### API/UI 快速调试

适用于接口、页面和不依赖后台队列消费的修改：

1. 执行 Alembic 迁移。
2. 启动 `backend-service` 热重载。
3. 启动 Vite。

完整命令见 [开发环境启动](../deployment/development-environment.md)。这种模式不包含六个 Worker Profile，不应拿来验证数据集导入导出、训练、转换、评估或异步推理的完整推进。

### 完整业务链路

适用于 Worker、Inference Daemon、Deployment、Workflow Runtime、Trigger 和端到端任务：

1. 构建前端。
2. 组装本地 Windows release。
3. 让 full Supervisor 启动迁移、daemon、service 和六个 Worker Profile。
4. 单独启动 Vite 时将其作为开发 UI；发行目录中的静态前端仍可用于生产形态验收。

当前 Worker 只能由 Supervisor 注入 Topology 身份后启动。不要直接执行 `python -m backend.workers.main`，也不要手工调用低层 Worker launcher。

## 3. 常用检查

后端快速检查：

```powershell
python -m ruff check backend custom_nodes tests
python -m pytest --collect-only -q
```

按修改范围运行定向测试，完整门禁再运行：

```powershell
python -m pytest
```

前端门禁：

```powershell
Set-Location frontend/web-ui
npm run typecheck
npm run test:unit
npm run build
npm run test:e2e
Set-Location ../..
```

pytest 默认使用 `.tmp/pytest` 和 `.tmp/pytest-cache`。并发或长链测试需要隔离时使用 `.tmp/<task-name>`；任务完成后只删除已确认不再使用的临时目录。

## 4. 数据库变更

开发态显式迁移：

```powershell
python -m alembic -c backend/alembic.ini upgrade head
python -m alembic -c backend/alembic.ini current
python -m alembic -c backend/alembic.ini check
```

也可以通过维护入口升级：

```powershell
python -m backend.maintenance.main migrate-database --output text
```

schema 变更必须带 Alembic revision，并至少验证空库升级、历史形态升级、数据保留、外键和 downgrade 边界。默认 SQLite，迁移代码必须兼容 MySQL/PostgreSQL。

## 5. 当前编辑器开发规范

- [图像交互取参](workflow-image-parameter-editor.md)：图片面板、ROI、圆、直线和模板区域取参。
- [Workflow 节点组](workflow-graph-groups.md)：分组、拖动、锁定、启用和禁用。
- [ROI 节点边界](roi-node-boundaries.md)：创建、转换、使用、绘制和判定职责。
- [Workflow App 版本迁移跨库门禁](workflow-app-version-cross-database-migrations.md)。

这些文档描述当前实现，不再保存阶段计划。

## 6. 专项验证资料

- [开发数据集审计](development-dataset-audit.md)
- [Construction-PPE 语义审计](construction-ppe-semantic-audit.md)
- [barcodeqrcode YOLO 对照验证](barcodeqrcode-yolo-benchmark.md)
- [空盘检测 Workflow App](empty-tray-detection-workflow-app.md)
- [Python 代码检查](python-code-checks.md)

专项数据记录用于复现实验，不是平台能力清单。平台能力以 [模型支持矩阵](../architecture/model-support-matrix.md) 为准。
