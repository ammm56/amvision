# 项目分类补齐验证

日期：2026-11-04。基线：`10ceea55`。对应[再次复核](project-workspace-followup-review.md)，在其基础上完成本轮缺口修复，没有重做项目整体布局。

## 修复结果

| 范围 | 当前行为 |
| --- | --- |
| 创建结果未知 | 保留原请求身份，可核对、按原内容重试或保留记录另建；多个待确认创建分别显示，成功只清除对应记录。查询 404 不当作取消成功 |
| 编辑结果未知 | 保存失败先读回；相同内容视为已保存，原版本未变时允许手动保存，其他修改进入比较。核对也失败时保留账号/项目隔离的待确认内容，重开继续核对，不自动重复 PATCH |
| 并发修改 | 读取服务器内容不立即更新提交基线；明确选择“保留我的修改”后才使用新 revision。采用服务器内容需要确认。清空说明后的 null 恢复为空，不退回旧说明 |
| 错误与等待 | 概览 403/404 保留返回列表与刷新；SDK 读取/生成可关闭，取消本地请求订阅，迟到响应不会下载，不宣称取消服务器生成。删除确认默认忙碌保护不变 |
| 列表 | 名称支持键盘选择，查看独立；筛选隐藏当前项目时可定位；创建成功留在列表并定位，提供查看入口；同页重名显示 ID；已知默认/配置项目的删除菜单禁用并说明 |
| 精确定位 | `GET /api/v1/projects?q=<完整ID>` 将完整 ID 匹配排在前缀匹配前，其他匹配保留原更新时间顺序。权限过滤、分页、响应结构不变 |
| SDK 与信息 | 空配置按权限提供应用/部署入口；ID/路径复制分别短暂反馈；保持已有依赖联动和预览 revision 校验 |
| 抽屉与短屏 | 抽屉移除/禁用焦点按钮后接回焦点，不抢内层确认或外部有效弹出控件焦点；窄列表减少说明/日期等次要列，继续保留操作 |

无数据库 schema、API 字段或 SDK 数据格式变更。仅项目列表搜索排序作上述补充，不涉及 Runtime/Trigger 执行数据面、模型推理、队列或重试策略。Vue 3 主栈、离线分发、原品牌与主题继续沿用。

## 自动化验证

- 前端 16 个文件、69 个测试通过：项目列表/概览/创建/编辑/删除/SDK、共享模态层、认证权限、项目 Store。
- 回归覆盖创建断线且查询 404 后另建、保存已成功但响应丢失、保存和核对均断线后重开、空说明恢复、并发选择和替换确认、403/404 返回、SDK 读取/生成时关闭、迟到下载保护、键盘选择和创建落点。
- 2 个后端接口用例通过：既有分页行为；完整 ID 优先于前缀匹配并继续按权限裁剪。
- `vue-tsc --noEmit`、生产构建、修改 Python 文件的 Ruff、`git diff --check` 通过。构建仍提示既有 WorkflowEditor/CloudViewer 大块体积警告，本轮未改变其功能。
- 新抽屉焦点用例首次复现了仅使用组件更新钩子不能覆盖插槽内容移除的问题；改为跟踪抽屉内相关 DOM 变化后，模态层测试和完整前端回归重新通过。

可复现命令（先激活 conda amvision；前端命令从仓库根目录执行）：

```powershell
conda activate amvision
python -m pytest tests/test_project_resources_api.py -k 'project_list_supports or exact_id_search' --basetemp=.tmp/project-query-check -q
node frontend/web-ui/node_modules/vitest/vitest.mjs run --no-file-parallelism --config frontend/web-ui/vite.config.ts frontend/web-ui/src/modules/projects frontend/web-ui/src/shared/ui/components tests/frontend/auth frontend/web-ui/src/app/stores/project.store.test.ts
npm --prefix frontend/web-ui run build
```

## 真实开发环境验证

使用现有数据库和资源，仅新增一个明确命名的隔离验收项目。没有修改既有项目配方、发布版本、模型或触发配置。

- 页面创建后留在列表，选中新项目并可进入概览；空项目四项计数为零。
- 空 SDK 配置禁用生成，显示应用/部署入口。
- 实际 GET/PATCH 制造并发修改：保存返回 409；本地草稿保留；读取最新内容后明确保留本地，再保存成功。
- 修复后实测读取/比较按钮消失时焦点仍在抽屉；Esc 打开放弃确认，取消后草稿保留，保存完成焦点返回原入口。
- 默认项目键盘选择不会进入详情；筛选隐藏当前项目后出现名称和定位；保护菜单中删除禁用。
- 现有项目：5 个数据集、20 个模型、17 个应用、6 个部署；最近更新 137 条，20 条分页读取正常。
- SDK 真正生成 ZIP，20 个文件可读取，JSON 可解析；覆盖 16 个 Runtime、15 个 Trigger、6 个部署；本次下载不包含访问凭据。旧预览 revision 请求返回 409。
- 服务状态实测 ready，自动启动汇总为部署 6/6、Runtime 10/10、Trigger 8/8。此处是控制面健康核对，不代替本轮未执行的长期推理压测。
- 隔离项目删除预检无业务资源，只有 1 个项目生命周期标记；DELETE 返回 202，操作回执最终 deleted，详情返回 404。失效链接页面可返回项目列表。
- 最后以最新 HTTP 源码重新启动，核对项目搜索与真实资源数后停止，见[接口证据](../design/frontend/verification/projects-followup-20261104/live-api.json)。

## 视觉核对和验收边界

在 1672×941 下将已确认列表和编辑亮暗设计图与实际截图并列检查；沿用规范规定的 520 CSS px 抽屉、220 px 导航与工作站文字密度，不照搬生成图中的放大字体和示例数据。

- [最终列表](../design/frontend/verification/projects-followup-20261104/list-final-light.jpg)：品牌选中、中性背景、真实资源数，无独立顶栏。
- [编辑亮色](../design/frontend/verification/projects-followup-20261104/edit-light.jpg) / [编辑暗色](../design/frontend/verification/projects-followup-20261104/edit-dark.jpg)：同一布局，纯色背景，导航与正文统一遮罩，抽屉覆盖而非挤压背景。
- [冲突比较](../design/frontend/verification/projects-followup-20261104/edit-conflict-light.jpg)、[SDK 空态](../design/frontend/verification/projects-followup-20261104/sdk-empty-light.jpg)、[失效项目](../design/frontend/verification/projects-followup-20261104/missing-project-light.jpg)均为本轮实况。
- 核对 1366×768、1093×614 和 911×512 CSS 视口；[短屏 SDK](../design/frontend/verification/projects-followup-20261104/sdk-short-dark.jpg)与[资源列表](../design/frontend/verification/projects-followup-20261104/sdk-resources-short-dark.jpg)标题/动作可达，正文独立滚动。最终宽屏无横向溢出。
- 内置浏览器不响应原生缩放快捷键，已恢复缩放并检查相应可用 CSS 空间；不将此声明为真实 125%/150% 浏览器缩放验收。
- 最后页面错误日志查询为空；403、网络响应丢失等故障通过受控组件测试验证，没有对已有账号或正在运行资源做破坏性故障注入。

本轮已确认缺口完成，未发现阻止项目分类交付的新问题。其他分类完整业务、原生浏览器缩放与长期生产稳定性仍不在该结论范围内。

## 环境收尾

本轮自行启动的 HTTP、Inference Daemon、Worker Supervisor 及受管子进程停止。保留任务开始前已经运行的 Vite。隔离项目和本轮临时脚本/缓存清理，保留上面的实际截图及结构化证据；历史 6 个 ACL 受限 pytest 目录属于此前已记录的清理问题。

## 追加：成功反馈与原生缩放（2026-11-04）

- 编辑成功复用全局轻提示“项目已更新”；覆盖直接编辑与信息抽屉转编辑。等待、失败、取消不会提前发出成功反馈，新建仍使用原有创建反馈。
- SDK 下载触发后显示“已开始下载”，不表示文件已经保存。生成失败、浏览器触发失败及关闭后的迟到响应不显示成功；下载 URL 在触发失败时也会释放。
- 两项文案包含中文、英文、日文、韩文，复用现有主题与 `role=status` 轻提示组件。
- 针对成功、等待、失败、取消和迟到响应新增 6 项回归，项目操作组件测试合计 19 项通过。
- 项目、模态组件、全局轻提示和权限相关回归合计 17 个文件、78 项通过；修正测试中 bootstrap 返回值类型后，19 项反馈用例复测与 `vue-tsc --noEmit`、`git diff --check` 通过。保存成功后后台 bootstrap 刷新失败也不丢失成功反馈。
- 原生缩放最初待验收：Edge 操作曾被电脑工具中止；该项后续按用户最新要求从验收范围移除，见下方收尾说明。
- 本轮启动的 HTTP、Inference Daemon、Worker Supervisor 已受管停止，5600 监听消失；保留原有 5601 Vite。没有修改既有项目、模型或工作流配置。
- 本轮 `.tmp/projects-feedback-zoom` 临时脚本与日志已在服务停止后删除。

项目分类完成状态以约定功能、实际页面操作及已有布局回归为准。浏览器原生缩放已按用户最新要求移出验收门槛。

### 内置浏览器实页补验（同日）

- 自行启动 HTTP、Inference Daemon、Worker Supervisor；状态接口返回 ready，部署 6/6、Runtime 10/10、Trigger 8/8。
- 内置浏览器重新加载后正常显示真实项目数据；使用单独创建的空项目进行实际 PATCH，亮暗外观均在保存成功后关闭抽屉、更新内容并显示“项目已更新”。见[亮色反馈](../design/frontend/verification/projects-feedback-iab-20261104/edit-feedback-light.png)、[暗色反馈](../design/frontend/verification/projects-feedback-iab-20261104/edit-feedback-dark.png)。
- 默认项目 SDK 真实生成并触发下载，本次关闭“包含当前访问凭据”；页面显示“已开始下载”，未声明文件已保存。见[下载反馈](../design/frontend/verification/projects-feedback-iab-20261104/sdk-feedback-light.png)。
- 内置浏览器未设置视口覆盖。1236×1036 CSS px 下无页面横向溢出；实际 DPR 为 1.5，不能据此声称浏览器已缩放至 150%。`Control_L+plus` 与 `Control_L+equal` 均未改变视口、DPR 或 visualViewport.scale。当前自动化接口仅提供尺寸覆盖，不提供原生缩放控制；已请求由用户操作内置浏览器的页面缩放入口后继续核对。

### 最终范围调整与结论

- 用户明确取消浏览器原生缩放验收，不再将 125%/150% 作为项目分类完成门槛。未改变产品代码中的缩放行为，也未继续扩展该项测试。
- 取消前已观察到用户设置的 125%：DPR 从 1.5 变为 1.875，CSS 视口为 989×829；列表、编辑抽屉无页面横向溢出，Tab 可进入说明字段，实际保存成功并显示反馈。此处只记录已执行的局部核对，不声明完成全部缩放矩阵；150% 未执行。
- 编辑保存、SDK 下载两项反馈的组件回归与真实亮暗页面核对完成。SDK ZIP 包含 20 个文件、19 个可解析 JSON 文件，压缩包完整性检查通过，未包含访问凭据。
- 本次约定的项目分类缺口已完成，当前核对范围内未发现新增阻断问题。该结论不等同于全部分类或长期生产稳定性验收。
- 本轮专用空项目 `project-0a6b7c6195224691bf9ae51f89700b2b` 已经由正式删除接口清理，回执为 `deleted`。清理脚本首次缺少 confirmation 字段返回 422，补齐请求后正常完成；未更改产品删除逻辑。
- 本轮 HTTP、Inference Daemon、Worker Supervisor 及临时清理 HTTP 均已停止，5600 无监听；保留原有 5601 Vite。`.tmp/projects-iab-zoom` 和本轮 SDK 测试 ZIP 已删除，真实反馈截图保留在验证目录。

## 追加：分类入口悬停与列表细节（2026-11-04）

### 问题与修复

- 真实页面复现顶部分类按钮圆角为 0，悬停背景贴到容器边缘，分隔线还在按钮自身边框上。改为容器内缩、6 px 圆角、独立分隔线；沿用主题中性灰悬停色和 120 ms 颜色过渡，数字保留品牌色。
- 底部“继续工作”使用同一悬停规则、字体和键盘焦点规则；禁用入口不触发悬停高亮。窄窗口双列时，分隔线仅保留在同一行两项之间。
- 最近更新、“查看全部”和当前运行去除逐行横线，保留表头、卡片边界、行间距和列对齐。
- 查看箭头及文字入口补齐圆角悬停区域和键盘焦点；标题说明和资源名称补齐长文本收缩/换行边界。
- 本轮产品代码修改仅限项目样式文件，不改 API、项目持久化或 Runtime/Trigger 执行逻辑；保留此前未提交的修改。

### 验证结果

- 内置浏览器使用当前数据库：默认项目 5 个数据集、20 个模型、17 个应用、6 个部署；最近更新共 137 条，第二页实际读取 21–40 条。
- 亮暗悬停均实测：顶部/底部入口圆角为 6 px；亮色背景 `#f0f1f3`，暗色背景 `#303030`。最近更新单元格和当前运行项的行边框均为 0。
- 700 CSS px 窗口下分类入口切换双列，页面宽度没有溢出，分隔线位置正确。检查完成恢复原窗口及亮色外观；没有执行浏览器缩放验收。
- 实际操作覆盖列表菜单及默认项目删除保护、新建空表单、信息转编辑、未保存草稿放弃确认、全部记录搜索空态/分页、SDK 预览与资源搜索，以及数据集入口跳转后仍使用 `project-1`。
- 本轮未提交数据修改，也未删除既有项目。权限、删除恢复、草稿冲突、SDK 迟到响应等异常分支通过既有自动化测试检查。
- 16 个测试文件、75 项相关测试通过；`npm --prefix frontend/web-ui run build` 包含类型检查并通过，仅有既有大体积 chunk 提示。首次测试因沙箱缓存 rename 的 EPERM 未启动，改在正常开发环境重跑后通过。
- 页面错误日志查询为空；本轮核对范围内没有发现新的功能阻断问题，不将此结论扩大为全部未来状态或长期运行保证。
- 本任务 HTTP、Inference Daemon、Worker Supervisor 已停止，5600 无监听；保留原有 5601 Vite。

证据：[顶部亮色悬停](../design/frontend/verification/projects-ui-audit-20261104/overview-hover-light.png)、[顶部暗色悬停](../design/frontend/verification/projects-ui-audit-20261104/overview-hover-dark.png)、[继续工作亮色](../design/frontend/verification/projects-ui-audit-20261104/shortcuts-hover-light.png)、[继续工作暗色](../design/frontend/verification/projects-ui-audit-20261104/shortcuts-hover-dark.png)、[全部记录](../design/frontend/verification/projects-ui-audit-20261104/all-records-light.png)、[最终概览](../design/frontend/verification/projects-ui-audit-20261104/overview-final-light.png)、[实际样式](../design/frontend/verification/projects-ui-audit-20261104/computed-styles.json)。
