# Workflow Preview 显示链路审计、修复与验证（2026-09-10）

## 结论

本轮发现的图片和值不显示是提交 `f846e722` 引入的前端异步完成处理回归。执行结果已存在，节点显示刷新仍停留在旧同步调用的返回位置；不能归因于模型没有输出、图片损坏、节点被禁用或 CSS 遮挡。

已完成以下修复和分步验证，代码尚未提交、未组装新发行包。真实执行使用原运行快照的隔离副本，未保存或发布用户原应用。此前 3 分钟验证未覆盖编辑器节点显示，不能作为完整 Preview 功能验收；本轮补充了实际浏览器图片、值、原图查看器及单节点交互验证。

## 实现结果与验收记录

| 步骤 | 已实现内容 | 验证 |
| --- | --- | --- |
| 1 | 补充异步提交至显示的组合回归 | 原实现失败，修复后通过 |
| 2 | `useWorkflowPreviewSession` 统一受理、订阅、恢复和终态；按账号、应用及文档身份隔离，重复终态不重复刷新 | 前端会话、组合测试通过；真实历史结果恢复 1 图 3 值 |
| 3 | 查询错误与显示错误独立展示、允许重试；权限或记录失效停止无效订阅，不自动重放业务 | 断线恢复、404、取消、超时、旧响应晚到测试通过 |
| 4 | `PreviewResultStore` 发布版本化节点显示清单和资产；前端最多 4 项并发读取，原图打开时加载 | 41 个真实目录定义的显示端口契约测试通过；真实缩略图 1920×1280，原图 5472×3648 |
| 5 | 强制退出恢复已完成 JSONL 记录；上传图片显示引用独立归 Run 所有；单项失败保留其他显示 | 真实 spawn 取消、部分结果、文件所有权及写入失败测试通过 |
| 6 | 空闲边界同步刷新节点包、目录与 handler；版本未变继续复用，刷新失败退出所属进程 | 实际节点包 schema/版本/禁用刷新测试通过 |
| 7 | 保留查看器直到新图就绪；主动关闭后不重开；修复并行分支内单节点预览范围 | 真实 Hough 单节点成功，仅执行 7 个依赖和目标节点；主动关闭后未重开 |

真实图片来自 `data/files/developer/图片/3570/治具托盘/空盘/Image_20260721103249646.bmp`。隔离应用 `workflow-app-display-validation-20260910010205` 来源于 96 节点不可变快照，仅调整身份、测试文件保存目录、本地图片路径并启用一个 Hough 调试图；未调整模型或算法阈值。浏览器完整预览 `preview-run-9e2758c83b8042fa964f1bcb94108274` 成功生成 1 个 Image Preview、3 个 Value Preview 和 1 个 Hough 调试图，业务输出为 24 个空槽位、expected_count=24、passed=true。

增加 150 秒延时的真实预览 `preview-run-8d989b54ae28445cbd0e2a2fe8decd47` 总观察时间 **153.047 秒**：299 次 HTTP 存活检查，0 次失败，服务实例身份未改变；HTTP P50 为 2.623 ms、P99 为 5.419 ms。最终 5 项显示与业务结果正确。该指标是 HTTP 存活接口延迟，不是 Trigger、推理或共享内存性能指标。

单节点运行 `preview-run-3a1e90300a904720801411a9e1d40bc3` 验证查看器保持并更新；`preview-run-7923b95b676147d8aed39217f5fc29ab` 验证执行期间主动关闭后不重开。另一次执行因本轮修改触发开发服务器自动重载而中断，仍记为失败，后续稳定源码后重测成功。一次非法 JSON 输入在提交前被阻止，修正输入后成功，未伪计为已执行。

代码验证：前端相关 64 项测试及生产构建通过；conda 下 Preview/资源/HTTP 响应相关 73 项、图执行/并行/选择相关 43 项、正式 Runtime 显示 API 2 项通过。最终完整响应标记调整后重跑对应异步响应测试通过。发行 Python 3.12.13 下最终结果存储与并行相关 68 项通过；此前进程测试也通过。不同集合存在重复覆盖，不相加为独立测试总数。

验收截图及原始 JSON 位于 `C:/Users/tanga/.codex/visualizations/2026/09/09/01a0847b-1b57-7ef1-8e5d-2f1b4fa3fafa/preview-audit-20260910/`，包括 `02-real-preview-viewer.png`、`03-real-value-preview.png`、`04-hough-node-preview.png`、`validation-long.json`、`validation-single-node.json`。原编辑器曾有未保存修改，热更新后不能完整核对其内容；已保存 `original-run-workflow.json` 用于恢复原执行快照，不能将它称为全部未保存编辑的完整备份。

验证结束后确认隔离应用的 7 次 Preview 均已终止，经现有 API 删除这 7 条测试运行及隔离应用，并关闭测试标签页；验收证据已移出临时目录。用户原应用、原运行及正式 Runtime 保留。本轮 `.tmp/display-fix-*` 目录删除被自动审批审查以 `blocked by policy` 拒绝，临时目录仍保留，未绕过限制。

### API 与兼容边界

- 新增 `/api/v1/workflows/preview-runs/{id}/displays` 清单、`/displays/{display_id}` 单节点显示和 `/display-outputs` 完整业务输出读取；均沿用项目可见性授权。单节点资产必须存在于所属 Run 清单中，响应禁用缓存。
- 显示格式为 `amvision.workflow-preview-displays.v1`，资产通过既有 ObjectStore 原子写入，JSON 预算沿用 64 MiB/100,000 值；不把图片写入数据库，不需数据库迁移。
- 轮询显式使用 `include_response_payload=false`；旧完整查询兼容。新异步执行应有完整响应但文件缺失时明确报不可用；历史记录走显式 legacy 分支，不重新执行。
- 显示捕获只挂入编辑态 Preview。正式 Runtime/Trigger 不新增这一磁盘捕获；共享的显示图片助手调整了原图延迟加载，正式图执行只增加受单节点 Preview 范围约束的并行边界处理。
- 保留 Vue 3、异步 HTTP 和常驻 Preview worker，不增加外部服务、CDN 或系统运行时依赖。conda 与同目录 Python 分别验证；完整新启动器发行包尚未验收。

### 额外发现：并行分支内单节点预览

真实 Hough 查看器重新预览暴露上游裁剪留下 Parallel Start、删去 Parallel End 的问题。修复先校验完整图配对，仅在明确单节点 Preview 范围中允许被裁剪的起点按普通值转发；其他分支不执行。完整图仍严格校验配对。新增测试覆盖起点、分支内部及完整分支结点，不以放宽正式执行校验解决编辑态问题。

### 尚未形成的验收结论

真实 Runtime `workflow-runtime-1691960999904278a9bad29cee6487aa` 的 app-mode 与监视页已做只读浏览器检查：前者显示“当前发布版本未配置应用模式”，后者能够显示发布画布，但提示部分节点定义与发布版本不一致、使用只读回退显示，两页均等待下次执行。因此本轮只确认页面可访问和状态可见，不宣称该实例的实时图片流或完整应用模式验收通过；未改变发布版本或调用正式 Trigger。该目录与发布快照差异仍需单独核对，不能归因于本次 Preview 显示修复。

41 类测试验证显示协议，不是 475 个节点算法逐项实跑；ForEach/Selection 任意内部节点单独执行组合也未穷尽验证。真实模型证据限于现有 YOLO11 分类流程和给定图片，未证明其他模型精度或长期稳定性。此前共享内存 P99 比 ZeroMQ 高约 17.46% 的门禁失败继续保留，本轮 HTTP 数据不能替代该门禁。

下文保留原审计依据和逐步设计，描述的旧调用位置用于解释回归来源；完成状态以上述验收记录为准。

## 现场证据与步骤

| 步骤 | 检查 | 结果 |
| --- | --- | --- |
| 1 | 内置浏览器查看工作流 `workflow-app-20260831130620` | 异常：Value Preview 已启用，有耗时，但没有值；右侧运行结果为 succeeded |
| 2 | 读取此次不可变执行快照和结果 | 快照 96 个节点，执行记录 80 条；有 1 个 Image Preview 和 3 个 Value Preview 输出 |
| 3 | 通过实际 HTTP 查询完整结果 | HTTP 200，succeeded，返回 1,766,778 字节、80 条记录；4 个显示输出均存在 |
| 4 | 解码实际图片数据 | JPEG 1920×1280，解码校验通过；该尺寸为显示图，不等于原图坐标尺寸 |
| 5 | 追踪提交、订阅、完成反馈、节点显示与查看器调用 | 异常：提交返回 running 后立即刷新空记录；后续终态没有执行显示反馈 |
| 6 | 遍历节点目录与受影响接口 | 当前启用目录 475 个定义；直接显示节点 5 类，调试图节点 36 类，共 41 类经过同一编辑态显示入口 |

现场运行 ID：`preview-run-62b53d0c9aee447e986b5e5b37d73ff6`。业务结果为 24 个空槽位、expected_count=24、passed=true。它与上一轮验证的 80 槽位应用不同。

现场截图：`C:/Users/tanga/.codex/visualizations/2026/09/09/01a0847b-1b57-7ef1-8e5d-2f1b4fa3fafa/preview-audit-20260910/01-missing-value.png`。截图能够确认可见空白和状态矛盾；网络载荷、进程行为和精度结论另依赖代码及数据证据。截图未验证屏幕阅读器行为，后续需为显示加载失败提供可读状态及重试入口，避免仅靠颜色或空白表达。

## 根因与其他发现

### F1：异步终态没有进入显示反馈（P1，现场与代码共同确认）

调用链：`useWorkflowSaveRunOrchestration.runPreview` → `runWorkflowPreview` → POST 返回 running → `applyPreviewRunFeedback` → `refreshPreviewNodeDisplays`。此时 node_records 尚为空。

随后 `useWorkflowEditorActions` 的 stream.onSnapshot 只更新 lastPreviewRun、sessionStorage 和 busy 状态，没有调用完成反馈；恢复查询也相同。属性面板和耗时直接依赖 lastPreviewRun，因此正常更新；节点内容依赖单独的 previewNodeDisplays，因此保持空白。

关键位置：

- `frontend/web-ui/src/workflows/workflow-editor/actions/useWorkflowSaveRunOrchestration.ts:124`
- `frontend/web-ui/src/workflows/workflow-editor/actions/useWorkflowSaveRunFeedback.ts:32`
- `frontend/web-ui/src/workflows/workflow-editor/actions/useWorkflowEditorActions.ts:80`、`:169`
- `frontend/web-ui/src/workflows/workflow-editor/preview/useWorkflowPreviewDisplays.ts:200`

### F2：图片交互重新预览与失败定位同时失去完成回调（P1，静态确认）

查看器重新运行、圈选/ROI/掩码取参后重新运行和右键单节点预览，都经过同一 orchestration。reopenImageViewerNodeId 只传给提交返回时的反馈：空记录可能关闭当前查看器，完成后无法重开。失败节点定位、错误消息设置也位于该反馈函数，异步终态不会自动触发。

这不是单独给图片组件增加 watch 就能完整解决的问题；必须保存每次执行的界面上下文，并统一处理完成事件。

### F3：状态查询失败没有编辑器级处理（P2，静态确认）

`useWorkflowResourceStream` 捕获查询异常后只调用可选 onError；编辑器未传入该回调。因此持续查询失败时可能只保留 running/busy，没有清晰的状态确认失败提示。应区分业务仍在运行、网络无法确认、权限失效和记录不存在，不能把网络错误直接改成任务失败，也不能无限静默重试。

### F4：强制停止路径丢失已完成节点记录（P2，静态确认）

子进程正常捕获错误会用 JSONL 事件恢复已完成节点记录；父进程因不协作取消、超时或进程退出调用 `_finish_inline_preview_run_failed` 时没有传入 node_records，默认写空。应在确认退出后读取本次已提交事件和显示资产，恢复已完成部分，不能把未完成节点当成成功。

正常失败路径此前就只从脱敏事件恢复部分结果；大型 inline-base64 图片无法从摘要还原，这是既有能力限制，不全部归因于本次提交。异步完整结果文件目前仅成功时写入、GET 也仅成功时加载，不能声称所有失败/取消场景都有完整预览。

### F5：常驻节点包刷新遗漏目录缓存失效（P2，静态确认的兼容风险）

`preview_process.py` 检测 manifest 变化后刷新 loader 和 runtime registry，但未调用 NodeCatalogRegistry.invalidate_cache。registry loader 又从已缓存的目录读取定义，存在新 handler 与旧 schema/端口定义混用、旧定义残留的风险。当前现场没有发生节点包升级，不能把 F5 当成此次空白的原因。

应在空闲执行边界统一更新节点包版本、目录、handler 和模型缓存；刷新失败后该槽位不可继续使用半更新状态。进程重建应作为更新失败的恢复方式，而不是每次预览都重启进程。

### F6：结果加载缺少独立状态与资源边界（P2，设计缺口）

状态查询和完整展示数据共用 GET；完整结果缺失时会回退摘要，而界面无法明确区分“确实为空”和“完整结果不可用”。原始输出一次整体 JSON 编码、读取、传输，结果面板 12,000 字符摘录只限制显示文字，不限制下载、JSON.parse 或内存占用。后续应让状态查询保持轻量，让显示结果按版本和节点按需获取。

`useWorkflowPreviewDisplays` 已有 generation 与 AbortController，后续应复用。多图片加载当前使用 Promise.all，需限制同时解码/读取数量，单个图片失败不应阻止其他值和图片显示。此类资源边界主要是既有问题与长执行持久化后的放大风险，不是本次现场已发生内存泄漏的证据。

### F7：按名字判断显示需求不能覆盖所有自定义节点（P2，既有兼容缺口）

当前 retain_node_records 由节点 ID 后缀 `-preview`、debug_image_panel_enabled 或单节点执行推断；自定义节点可以输出合法显示 body，却没有该后缀。相反 Heatmap Preview 实际输出普通 image 和 summary。后续应通过显式显示端口声明/能力识别，在兼容期保留现有识别路径，不强行给普通节点增加显示行为。

## 影响范围与未误判的边界

| 范围 | 核对结论 |
| --- | --- |
| 图片、值、表格、图库、帧窗口预览 | 共用编辑态显示入口，F1 会阻止终态刷新 |
| Hough Circles 等调试图 | 启用调试图时共用同一入口；算法计算本身不是由该入口完成 |
| 查看器缩放/原图、ROI/圆/线/模板区域/掩码编辑 | 显示无法打开或更新时，相关交互不可用；参数回写代码未被该提交直接修改 |
| 单节点及上游依赖执行 | 执行 scope 仍传递；完成显示、失败定位和重新打开查看器受影响 |
| 页面刷新/返回应用后的运行恢复 | 记录查询存在，显示恢复仍缺失；需要同一完成流程及身份校验 |
| 属性面板业务 JSON、节点耗时 | 本次现场正常；不代表节点显示正常 |
| Runtime app-mode、Runtime 监视画布 | 使用 useRuntimePreview 与独立显示 WebSocket，并非 F1 的编辑器调用链；不可据此宣布损坏，也不可据静态核对宣布实测通过 |
| 正式 Trigger、ZeroMQ、共享内存 | 此次提交未更改数据面实现；Preview 仍与其共享 CPU/GPU/磁盘/内存，需要防止显示负载争抢 |
| 模型训练、转换、准确性算法 | 此次提交未修改相关算法。实际 24 槽位业务输出有效；不等于所有模型或精度通过 |
| 自定义节点、模型加载、文件输入输出 | 预览执行上下文迁移到常驻子进程，必须验证生命周期、缓存及文件所有权；不逐节点重写 handler |

目录遍历不等于 475 个节点逐一实跑；本轮未新增长时间测试、未执行硬件/协议节点。41 类是静态影响范围，实际现场确认的是 4 个显示节点实例。

## 修复方案与逐步验收

保留独立常驻 Preview 执行进程和异步 HTTP 接口，不退回请求线程直接执行重任务。首先补齐完整的执行会话和显示生命周期，再处理结果资源与节点包更新边界。每一步完成后核对其验收点，不以单纯 pytest 通过替代界面验收。

### 第一步：建立会失败的最小回归

构造 POST running → GET succeeded 的真实组件组合：Actions、ResourceStream、Orchestration/Feedback、Displays，断言 Image/Value 内容及查看器刷新。不得只 mock 最终显示函数后检查 busy=false。增加失败节点定位、单节点重新预览、刷新恢复和旧响应晚到场景。该测试应先在当前实现失败，明确捕获 F1/F2。

### 第二步：统一 Preview 会话和终态处理

- 会话保存 project_id、application_id、run_id、页面 generation、文档身份、execution scope、reopenImageViewerNodeId；不复制大图进 sessionStorage。
- 提交返回只代表已受理，不运行完成反馈；订阅、轮询和恢复查询统一进入 acceptSnapshot。
- 终态按 run_id 和结果版本只处理一次，再调用统一反馈，更新显示、定位错误、恢复查看器。
- 执行状态与显示加载状态分开：任务成功后图片仍可能加载中；不能将显示失败改为任务失败。
- 新运行、切换应用、退出页面取消旧图片读取和旧界面任务。旧运行可以后台继续，但不得覆盖新页面、重新打开旧窗口或修改新文档。
- 查看器重新运行期间保留明确标识的上一结果，终态新图就绪后替换；用户主动关闭后不强制重开。

验收：当前现场运行的 1 图 3 值可通过读取已有结果恢复，无需再执行原应用；随后在隔离副本中实测完整预览及单节点交互流程。

### 第三步：补齐查询异常与终态展示

接入 onError；瞬时断线保留运行身份和最后结果，显示“状态暂时无法确认”，退避重试。403/404 停止无效订阅并说明权限/记录变化；401 走既有会话恢复规则。失败、取消、超时分别显示，只有确实失败且存在 node_id 时定位节点。

验收：网络断开/恢复、记录不存在、权限变化、取消成功、超时等状态均可理解；无持续静默 busy，无自动重放业务执行。

### 第四步：建立完整结果与显示资产的可靠交付

先兼容现有 include_response_payload 查询；状态摘要保持默认脱敏，不把大图写入数据库。增加显式版本的显示结果清单/可用状态，清单包含 run/node/output 身份、类型和资产引用。完整值与图片按需加载，后续按节点拆分大结果；保持旧 v1 查询兼容并同步文档。

完整结果和资产采用临时写入后原子发布，显示可用性与执行终态区分；加载失败/结果过期明确提示并允许重试，不能静默把摘要当完整内容。已有历史运行的文件可用时直接读取，无需重跑或重新发布应用。

保留 image 的 source_image、display_image、尺寸比例、overlays 和 interaction。取参始终使用原图坐标；展示缩略图不得改变模型输入、测量坐标或业务输出。图片请求/解码采用有限并发，单项失败只影响该项，切换页面释放 Blob URL。

验收：inline-base64/storage-ref、原图/缩略图、0/false/null/空字符串/对象/长数组、表格、图库、缺图和重复完成事件；一次完成不会引起反复下载或重建全部图片。

### 第五步：恢复中断任务的有效部分结果

正常失败沿用已完成节点记录；强制退出后恢复已提交 JSONL 事件及独立显示资产，不把摘要伪装成完整图片。显示数据按节点发布，保留最后完整版本；无可恢复结果时说明“该节点结果未生成/未保存”。上传输入在执行结束后回收，供页面使用的显示资产独立归 Preview Run 生命周期管理。

验收：一个预览节点已完成、后续节点失败/取消/超时/退出，前者仍可展示；未完成节点不显示成功，回收不导致已发布图片失效。

### 第六步：核对常驻进程节点与资源生命周期

补齐目录缓存失效和一致更新；节点包升级/禁用在空闲边界生效，更新失败重建所属槽位。验证同版本模型复用、版本变更失效、跨应用 scope、文件/LocalBuffer 引用有效期、子进程停止后的模型和资源回收。保持有界进程数，避免每次执行重建模型，也避免每轮扫描/序列化全目录成为常态开销；复用平台现有版本更新机制。

验收：更新后 schema、handler、模型 provider 来自同一版本；旧节点禁用后不能继续执行；连续短预览不持续增加进程数或未释放图片引用。

### 第七步：完整界面与真实数据验收

1. 5 类显示节点及 36 类调试图节点按显示契约做参数化测试；输入数据允许使用最小合成图，仅验证显示协议，不声称模型真实精度。
2. 真实 24 槽位应用隔离副本：验证图、3 个值、原图查看、调试图、单节点预览和失败反馈；重定向文件保存位置，不改用户应用和阈值。
3. 再执行一次最长约 3 分钟的延时验证，同时检查最终图和值以及 HTTP 可用性；不做 30 分钟测试。
4. Runtime app-mode 和 Runtime 监视页使用既有真实实例做针对性回归；确认只订阅时不改变正式执行配置或 Trigger 数据面。
5. conda 与发行 Python 3.12.13 的 spawn/资源回收测试、Vue typecheck 和相关前端测试；完整启动器发行验证另列状态。

最终验收必须同时具有：任务终态正确、业务结果正确、预览显示正确、交互正确、HTTP 可用、资源所有权正确。保留此前共享内存 P99 +17.46% 门禁失败及长期稳定性未验收结论。

## 本轮提交文件核对范围

`f846e722` 的 33 个文件按职责全部纳入此次影响分析：12 个后端文件（状态契约、装配、路由/schema/线程交接、进程池与子进程、执行记录、metadata、运行服务和配置）；10 个前端文件（Actions、服务、资源流、页面接线、工具栏、Inspector、结果面板、国际化及测试）；3 个启动器实现文件；5 个 Python/启动器测试文件；3 个文档文件。相关调用方即使未在提交中改动，也一并追踪，F1 正是在未同步调整的 Orchestration/Feedback 中暴露。

后续不再用“提交中未改节点文件”推断节点功能未受影响，也不把目录级静态检查写成所有节点已实测通过。

## 41 类显示与调试节点清单

当前启用目录去重后为 475 个定义。以下清单表示共同显示链路的影响范围，未宣称逐项运行验收通过。

| 节点类型 | 显示名称 | 受影响能力 |
| --- | --- | --- |
| `core.input.box-prompt` | Box Prompt | 启用后的调试图及相关取参 |
| `core.input.mask-editor` | Mask Editor | 启用后的调试图及相关取参 |
| `core.input.point-prompt` | Point Prompt | 启用后的调试图及相关取参 |
| `core.input.polygon-prompt` | Polygon Prompt | 启用后的调试图及相关取参 |
| `core.io.frame-window-preview` | Frame Window Preview | 专用显示 |
| `core.io.image-preview` | Image Preview | 专用显示 |
| `core.io.table-preview` | Table Preview | 专用显示 |
| `core.io.value-preview` | Value Preview | 专用显示 |
| `core.vision.roi-create` | Create ROI | 启用后的调试图及相关取参 |
| `core.vision.roi-from-contour` | ROI From Contour | 启用后的调试图及相关取参 |
| `core.vision.roi-from-rotated-rect` | ROI From Rotated Rect | 启用后的调试图及相关取参 |
| `core.vision.roi-grid-create` | ROI Grid Create | 启用后的调试图及相关取参 |
| `custom.opencv.affine-transform` | Affine Transform | 启用后的调试图及相关取参 |
| `custom.opencv.bilateral-filter` | Bilateral Filter | 启用后的调试图及相关取参 |
| `custom.opencv.caliper-edge` | Caliper Edge | 启用后的调试图及相关取参 |
| `custom.opencv.canny` | Canny Edge | 启用后的调试图及相关取参 |
| `custom.opencv.circle-measure` | Circle Measure | 启用后的调试图及相关取参 |
| `custom.opencv.contour` | Contour | 启用后的调试图及相关取参 |
| `custom.opencv.contour-approx` | Contour Approx | 启用后的调试图及相关取参 |
| `custom.opencv.contour-filter` | Contour Filter | 启用后的调试图及相关取参 |
| `custom.opencv.convex-hull` | Convex Hull | 启用后的调试图及相关取参 |
| `custom.opencv.fit-ellipse` | Fit Ellipse | 启用后的调试图及相关取参 |
| `custom.opencv.fit-line` | Fit Line | 启用后的调试图及相关取参 |
| `custom.opencv.gallery-preview` | Gallery Preview | 专用显示 |
| `custom.opencv.homography-estimate` | Homography Estimate | 启用后的调试图及相关取参 |
| `custom.opencv.hough-circles` | Hough Circles | 启用后的调试图及相关取参 |
| `custom.opencv.hough-lines` | Hough Lines | 启用后的调试图及相关取参 |
| `custom.opencv.image-refs-empty-check` | Image Refs Empty Check | 启用后的调试图及相关取参 |
| `custom.opencv.image-refs-occupied-check` | Image Refs Occupied Check | 启用后的调试图及相关取参 |
| `custom.opencv.image-refs-slot-metrics` | Image Refs Slot Metrics | 启用后的调试图及相关取参 |
| `custom.opencv.min-area-rect` | Min Area Rect | 启用后的调试图及相关取参 |
| `custom.opencv.min-enclosing-circle` | Min Enclosing Circle | 启用后的调试图及相关取参 |
| `custom.opencv.orb-keypoints` | ORB Keypoints | 启用后的调试图及相关取参 |
| `custom.opencv.orb-match` | ORB Match | 启用后的调试图及相关取参 |
| `custom.opencv.perspective-transform` | Perspective Transform | 启用后的调试图及相关取参 |
| `custom.opencv.quadrilateral-from-circle-centers` | Quadrilateral From Circle Centers | 启用后的调试图及相关取参 |
| `custom.opencv.quadrilateral-from-lines` | Quadrilateral From Lines | 启用后的调试图及相关取参 |
| `custom.opencv.remap` | Remap | 启用后的调试图及相关取参 |
| `custom.opencv.rotation-correct` | Rotation Correct | 启用后的调试图及相关取参 |
| `custom.opencv.template-match` | Template Match | 启用后的调试图及相关取参 |
| `custom.opencv.undistort` | Undistort | 启用后的调试图及相关取参 |

排除误判：`custom.opencv.heatmap-preview` 输出普通 image/summary，自身不生成显示 body。其后连接 Image Preview 时，下游显示仍受 F1 影响。其余自定义节点若输出合法显示 body，也应按端口协议纳入后续兼容验证，不能仅依赖名称后缀。
