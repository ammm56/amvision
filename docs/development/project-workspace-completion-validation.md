# 项目分类修复与收尾验收

日期：2026-11-04。范围为[完整性复核](project-workspace-ui-completeness-review.md)提出的 7 项缺口，以及相关公共覆盖层和页面细节。保留既有 Vue 3、Pinia、Vue Router、v1 API 与本地部署结构；未新增前端框架、外网 CDN 或运行时数据队列。

本次约定的代码修复已完成。结论分别来自自动化故障用例、真实开发数据和浏览器操作，不以静态截图代替功能验证。此结论不代表其他分类改造、全平台回归或长期无人值守验收。

## 实现与检查顺序

| 顺序 | 实现 | 检查结果 |
| --- | --- | --- |
| 1 | 删除待确认按账号、项目保存多项；网络失败不清除身份；查询不重新 DELETE；项目移除与文件清理分层显示 | 连续故障、多项目恢复测试通过；真实隔离项目清理完成 |
| 2 | 抽屉关闭、路由离开与同路由变更统一保护草稿；刷新/关闭注册 beforeunload；未知创建保留 request_id | 重挂载仍使用原身份；真实返回/Esc 取消后草稿保留；确认放弃后可正常导航 |
| 3 | 项目入口允许任一相关资源能力；字段按 scope 与页面范围裁剪；SDK 前后端入口一致 | 受限主体 API/组件通过；权限表单复用入口规则，防止无 scope 误通过 |
| 4 | 初次失败、空数据、刷新失败分开；保留最后成功数据并标注时间；失权清空；URL 搜索分页和滚动恢复 | 故障/历史状态测试通过；禁用 sessionStorage 不阻止打开项目 |
| 5 | 最近更新全宽展开、搜索、分类、分页；增加真实版本/发布来源；可见页面 30 秒观察刷新 | 137 条真实更新跨页无重复；服务摘要有界，不伪造任务进度 |
| 6 | SDK 元数据分页、总数校验、明确容量；UI 每页 50 项；跨页选择；下载核对预览 revision | 151 项组件分页和容量测试；真实 37 项/20 文件导出，旧 revision 返回 409 |
| 7 | 复制按钮名称、资源版本详情、共享字段样式、重复错误和短屏动作区 | 亮暗、真实版本抽屉、SDK 短屏及现有数据集模态交互通过 |

接口见[项目 API](../api/projects.md)、[SDK 配置包](../api/sdk-config-packages.md)。没有数据库 schema 变更；旧 manifest 空时间仍为 null。删除回执继续保存在项目目录之外；并发编辑继续通过 expected_revision 返回 409。

## 自动化结果

| 检查 | 结果与范围 |
| --- | --- |
| 后端项目相关测试 | 35 个不同用例：首轮 33 通过，2 项旧断言缺少新增 display_name；更新预期后这 2 项复测通过。不是最终版本 35 项单次重跑 |
| 前端回归 | 最终 15 个文件、56 项全部通过；项目组件/页面/store、权限与公共 UI |
| TypeScript | 最终 vue-tsc --noEmit 通过 |
| 前端构建 | Vite 生产构建通过；WorkflowEditor/CloudViewer 既有大块提示保留 |
| Python 检查 | 本次相关文件 Ruff 通过 |
| .NET 契约 | 已有 net472 契约测试程序执行成功；本轮未修改或重新构建 .NET SDK |
| 补丁格式 | git diff --check 通过 |

关键故障覆盖：连续删除/查询失败、A/B 恢复隔离、未知创建跨组件恢复、冲突不覆盖草稿、路由与 beforeunload 保护、首次失败/过期/失权清空、部分资源读取失败、受限账号裁剪、SDK 依赖/隐藏选择/分页/容量/预览失败禁用下载。

复现命令（仓库根目录）：

```powershell
conda activate amvision
python -m pytest tests/test_project_resources_api.py tests/test_project_summary_api.py tests/test_project_workspace_api.py tests/test_sdk_config_packages_api.py
node frontend/web-ui/node_modules/vitest/vitest.mjs run --no-file-parallelism --config frontend/web-ui/vite.config.ts tests/frontend/auth frontend/web-ui/src/modules/projects frontend/web-ui/src/app/stores/project.store.test.ts frontend/web-ui/src/shared/ui/components
```

包含 tests/frontend 用例时从仓库根目录运行 Vitest。一次误从前端目录运行造成别名解析失败；另一次 Windows 沙箱临时缓存并行 rename 遇到 EPERM，测试尚未加载。最终将 TEMP/TMP 定位到仓库 `.tmp` 独立目录并关闭文件并行后通过 56 项，未为测试环境故障修改业务实现。

## 真实开发数据与操作

使用本机 5600 HTTP、推理守护进程和原有 5601 Vite。只读检查使用现有 `project-1`，写入使用新建隔离项目；现有生产 JSONL、图片、Runtime/Trigger 配置未为验收改写。

- 计数：5 个数据集、20 个模型、17 个应用、6 个部署。最近更新 137 条，按 100 + 37 两页读取，资源身份无重复。
- SDK：16 个 Runtime、15 个需调用配置的 TriggerSource、6 个部署；压缩包 20 个文件，JSON 可解析。`contains_access_token=false`、`warnings=[]`，目录监听省略为普通说明。错误 expected_revision 返回 409。
- 隔离项目 `project-4b9a0b6ecf6e42b99555882f29e46b27`：创建 201，同请求重试返回同一项目，修改 200，旧 revision 修改 409，删除 202，回执 cleanup_pending → deleted，之后查询项目 404。
- 单次读取样本：项目元数据 542.2 ms、20 条概览 145.4 ms、SDK 资源页 145.1 ms。不是平均耗时、P95 或性能上限。

结构化证据：[真实 API](../design/frontend/verification/projects-completion-20261104/live-api.json)、[隔离项目生命周期](../design/frontend/verification/projects-completion-20261104/live-project-lifecycle.json)。

## 浏览器与设计核对

简洁导航、品牌绿主操作/选择、中性 hover/focus、亮暗纯色背景保持一致。信息抽屉 520 CSS px，SDK 模态 760 CSS px；遮罩同时覆盖导航和主内容，背景不被挤压；亮暗使用相同 DOM。

| 核对 | 本次证据 |
| --- | --- |
| 同数据亮暗概览 | [亮色](../design/frontend/verification/projects-completion-20261104/overview-light.jpg)、[暗色](../design/frontend/verification/projects-completion-20261104/overview-dark.jpg)，1672×941 |
| 信息与资源版本抽屉 | [项目信息](../design/frontend/verification/projects-completion-20261104/information-light.jpg)、[数据集版本](../design/frontend/verification/projects-completion-20261104/dataset-version-light.jpg)，样本 1174、类别 3 与响应一致 |
| 草稿保护 | [放弃修改确认](../design/frontend/verification/projects-completion-20261104/draft-protection-light.jpg)；真实返回/Esc 后取消，输入未丢失 |
| SDK 短屏和范围 | [1366×768](../design/frontend/verification/projects-completion-20261104/sdk-short-dark.jpg)、[范围](../design/frontend/verification/projects-completion-20261104/sdk-range-short-dark.jpg)、[911×512](../design/frontend/verification/projects-completion-20261104/sdk-compact-dark.jpg)，正文滚动、底部动作可达 |
| 公共模态回归 | [现有数据集管理](../design/frontend/verification/projects-completion-20261104/shared-dataset-dialog.jpg)，Tab/Esc 和关闭后焦点归还，未删除数据 |

真实 SDK 页面执行了下载；搜索无匹配再清除保留 37 项选择，取消范围草稿恢复原选择。下载工具回传曾长时间阻塞，不能将工具等待当成服务端下载耗时。已移除 viewport 切换过程截图和修复前重复错误截图。

## 验证边界与清理

- 原生刷新确认框未获得可核对截图；beforeunload 通过组件测试，真实返回/Esc/确认放弃已验证。原生 125%/150% 浏览器缩放未单独验收，本轮以实际 CSS 短视口验证布局。
- 权限、连续断线和容量采用隔离 API/组件受控数据；未改变真实操作员权限注入故障，未向真实库写入万级资源。
- 未调整 Preview、Runtime、Trigger 的执行数据面、实例数、共享内存 ACK 或 .NET 调用协议。现有数据集模态回归不代表其他页面全部交互均已验收。
- HTTP 与推理守护进程通过正常停止路径退出，全部已知子进程均不存在。5600、任务临时 5602 不再监听，原有 5601 前端保持运行。
- 测试项目删除完成。有效证据保存在 docs；测试日志、Vitest 缓存和过时截图已清理。6 个 pytest 临时目录仍受 Windows ACL 限制，当前用户无法读取、删除或 takeown；普通及沙箱外清理均返回 Access denied。剩余目录为 `.tmp/project-blocker-final`、`.tmp/project-final-regression`、`.tmp/projects-completion-api`、`.tmp/projects-completion-tests`、`.tmp/projects-final-api`、`.tmp/pytest`，均无任务进程使用。此项需要系统管理员恢复这些目录的继承权限后删除，不能记作已清理完成。没有执行 Git 提交或推送。
