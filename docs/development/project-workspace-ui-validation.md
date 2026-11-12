# 项目工作区与公共界面验证

日期：2026-11-04。范围为前端落地计划首批公共组件和项目分类；基线提交 `9b125107`。本记录不代表数据集、模型等后续页面已经按设计实施，也不代表整个平台长期生产验收。

**收尾更新：** 本记录保存首批实现的历史事实。[完整性复核](project-workspace-ui-completeness-review.md)后来发现的删除恢复、离页草稿、权限、概览与 SDK 缺口已完成修复；当前实现及新增测试结果以[收尾验收记录](project-workspace-completion-validation.md)为准，不能用下文旧覆盖范围替代当前状态。

## 实现范围

| 部分 | 实现与边界 |
| --- | --- |
| 公共主题 | 复用品牌绿、白色主按钮标记、中性 hover/focus；亮暗纯色背景，未改变导航结构、图编辑工具栏或执行协议 |
| 覆盖容器 | 抽屉覆盖整屏遮罩、不挤压背景；项目抽屉 520 CSS px；模态层统一滚动锁、背景 inert、Tab 限制、Esc 和焦点归还；嵌套确认只激活顶层 |
| 项目列表 | 全可见范围搜索、分页、当前项目、查看与更多操作；保留其他分页之外已选项目；权限变化撤销旧请求显示 |
| 项目概览 | 四类资源入口、有限最近更新、当前任务/服务和继续工作；资源类型图标、状态/时间列；长列表独立滚动 |
| 元数据 | 新建、只读信息、编辑；UUID 创建请求身份、名称/说明校验、版本冲突核对、未保存草稿保护、复制 ID/路径 |
| SDK | 默认全部资源；范围搜索不清空隐藏选择；Trigger 关联 Runtime；手动选择与依赖选择分开；预览 revision 校验、真实下载和空选择保护 |
| 删除 | 默认/配置项目保护、活动资源预检、非空影响、严格 ID 确认、项目移除与磁盘清理分开、授权回执查询、失败恢复 |

后端新增能力仍在 v1 内，无数据库 schema 迁移。删除回执位于项目目录之外，避免文件删除同时销毁核对依据。公开接口见[项目 API](../api/projects.md)、[SDK 配置包](../api/sdk-config-packages.md)。

## 检查中修复的问题

1. 提交按钮进入 disabled 后焦点可能落到 body，导致下载完成后 Esc 无效：公共确认框完成忙碌切换时将焦点恢复到活动容器。
2. 信息转编辑与 SDK 选择视图切换会移除当前焦点：明确聚焦新输入，关闭后归还原入口。
3. SDK 模型文件名含生成时间，使同一配置跨秒产生不同 revision：改为稳定 `Config/config_model_deployments.json`，测试跨秒预览、下载及 ETag 304。
4. 同一模型部署的 sync/async 运行项使用相同前端 key：接口返回 `runtime_mode`，展示和标识分开；停止中的服务也保留。
5. 清理回执读取异常可能覆盖原文件清理错误：读取和写入均纳入 best-effort 回执处理，保留原异常与恢复目录。
6. 长服务列表挤出后续操作、信息抽屉标签和值分离、SDK 范围页重复摘要：修正有界滚动、双列信息和范围视图层级。

## 自动检查

后端累计覆盖 33 个不同用例：第一轮 32 项通过；补充部署模式用例后，项目工作区 4 项及 SDK 9 项重新通过。不是最终版本全套 33 项单次重跑。

```powershell
conda activate amvision
python -m pytest tests/test_project_resources_api.py tests/test_project_summary_api.py tests/test_project_workspace_api.py tests/test_sdk_config_packages_api.py
python -m ruff check <本次变更的 Python 文件>
```

覆盖创建身份重试、元数据冲突、项目授权、搜索/分页、删除阻止、文件占用/恢复、既有公开文件、摘要聚合、WebSocket、SDK 选择依赖及稳定配置摘要。Ruff 与 `git diff --check` 通过。

前端公共 UI、项目 store 和项目操作组件 8 个测试文件、27 项通过。`vue-tsc --noEmit` 和 Vite 生产构建通过。当前机器 npm 全局启动脚本缺失，因此直接运行仓库已安装工具，无依赖或锁文件变更：

```powershell
# frontend/web-ui/
node node_modules/vitest/vitest.mjs run src/shared/ui/components src/app/stores/project.store.test.ts src/modules/projects/components/project-workspace.test.ts
node node_modules/vue-tsc/bin/vue-tsc.js --noEmit
node node_modules/vite/bin/vite.js build
```

构建仍提示 WorkflowEditor 和 CloudViewer 包超过 500 kB；本次没有改动其打包边界。后续专题处理，不能把警告写作构建失败或性能验收结果。

.NET `Amvar.Vision.ContractTests.vs2019.net472.csproj` 构建成功，0 警告、0 错误；Debug 合约程序执行通过。额外调用真实 `GetServiceStatus` 两次，均 `ready=true`。此处只验证状态/配置契约，不触发真实生产推理或改写生产记录；不以两个请求样本统计性能。

## 真实开发环境

- 使用现有 Vite 5601；本任务自行启动 HTTP 5600 与 inference daemon，后端关闭自动重载，避免验证期间进程更新。
- 使用实际默认项目：5 个数据集、20 个模型、17 个应用、6 个部署，未使用设计图中的假计数。
- 独立项目 `project-37439e9b3dc3433f8f62d8d7533cdd90` 完成新建、修改、草稿保护、严格确认删除；最终回执为 `deleted`，目录列表中已不存在，原有项目保持不变。
- 实际 SDK 范围包含 37 项资源；验证过滤后隐藏选择保留、取消范围草稿恢复、下载成功、完成后 Esc 可关闭。ZIP 临时保留用于检查，任务结束清理，不提交含凭据的包。
- 真实 Chromium 页面未捕获 `pageerror`。10 个其他导航入口完成只读首屏冒烟检查，没有据此声称其全部业务已回归。
- 完整模型服务启动后 `/system/status` 为 ready，部署 6/6、Runtime 10/10、Trigger 8/8，阻止项为空。此前只启动 HTTP 时的 starting/503 是缺少 daemon 的真实状态。
- Worker Supervisor 未启动；本次没有验证训练、转换等队列任务执行，也没有启动或取消已有排队任务。

内置浏览器连接多次超时，使用独立的本机 Chromium 自动化会话完成真实页面验证；该会话结束时关闭。对原有用户浏览器标签页的最终视口恢复无法由失联工具核实，不以此替代功能或视觉检查。

## 视觉与交互

见根目录 [design-qa.md](../../design-qa.md)。证据位于 [projects-20261104](../design/frontend/verification/projects-20261104/live-checks.json)，设计图与当前截图的尺寸/SHA-256 保存在 [asset-checks.json](../design/frontend/verification/projects-20261104/asset-checks.json)。实际下载 ZIP 包含 20 个文件，其中 19 个 JSON 均可解析，CRC 检查通过。

- 1920×1080 亮暗同结构；概览另以 1672×941 与源图同尺寸核对。
- SDK 长列表、1366×768 亮暗短屏通过；1093×614、911×512 对应 1366×768 在 125%/150% 的 CSS 可用空间压力检查，属于等效视口测试，并非操作系统缩放或浏览器原生 zoom 测试。
- 抽屉宽度 520，打开前后背景资源指标 bounding box 完全相同。
- 验证 Tab/Esc、嵌套草稿确认、焦点归还、SDK 子视图焦点、固定底部动作、默认项目删除保护。
- 错误/冲突/权限等不可在真实生产资源上安全制造的情况使用受控组件/API 测试；不声称每一异常都已在真实服务人工触发。

## 收尾与下一阶段

本任务 inference daemon 与其后代共 8 个进程、HTTP launcher 与其后代共 14 个进程均正常退出，无剩余进程；HTTP 日志确认 application shutdown complete。5600 已停止监听，原有 Vite 5601 保持监听，未发现残留测试用 headless Chromium。临时文件在交付前清理。没有提交或推送 Git，也未修改既有 Runtime/Trigger 数据面、模型参数、生产 JSONL 或 .NET 调用队列。

后续先按[完整性复核](project-workspace-ui-completeness-review.md)补齐项目分类，再按[实施计划](../design/frontend/frontend-implementation-plan.md)进入任务和数据集等分类；公共组件复用时继续检查复杂表单、下拉浮层和长列表，不把本轮项目场景测试外推为全站覆盖。
