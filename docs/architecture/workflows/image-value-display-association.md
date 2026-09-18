# Image Preview 与 Value Display 显式关联

状态：2026-09-18 已完成代码实现、目标草稿及活动 Runtime 迁移。前文记录设计约束与改动前事实，实际验证结果见文末。

## 现场事实与问题

检查对象为 `workflow-app-20260910030132`，浏览器页面显示已保存。应用模式配置中的四个图片栏分别显式绑定了两个 Value Display：

| 图片节点 | 图片栏 | 当前 metadata.overlay 来源 |
| --- | --- | --- |
| core_io_image_preview | 治具原图 | tray_value_display.body |
| core_io_image_preview_2 | 治具结果图 | tray_value_display.body |
| core_io_image_preview_3 | 塑盒原图 | box_value_display.body |
| core_io_image_preview_4 | 塑盒结果图 | box_value_display.body |

当前并非所有图片自动关联数据。绑定保存在应用 metadata 的 `app_mode.displays[].overlay` 中，未绑定的图片本来就不会叠加。现场问题是关联没有成为图上的数据依赖，而且界面没有清楚区分三个状态：

- 节点属性的“启用节点”：控制图中节点是否参与执行。
- 应用模式行的复选框：选择是否占一个独立显示栏，不控制执行。
- 图片行的“结果显示”：引用另一个 Value Display；该 Value Display 即使没有独立栏仍可被使用。

Image Preview 现有 `presentation_context` 输入只传递来源标识，不携带 Value Display 的字段、颜色或布局；仅看到该线无法知道叠加数据来自哪个节点。Value Display 的 Body 不需要连到图片节点，应用模式前端另外查找 Body 后再组合。

已核对的实现入口：

- `backend/nodes/core_nodes/io/image/image_preview.py`：图片输出及 presentation_context。
- `backend/nodes/core_nodes/io/preview/value_display.py`：格式、颜色、Appearance 和 context。
- `backend/contracts/workflows/workflow_app_mode.py`：overlay 引用与已启用节点校验。
- `frontend/web-ui/src/workflows/workflow-editor/components/WorkflowAppModeConfigDialog.vue`：第二套绑定配置；相关文案还存在硬编码中文。
- `frontend/web-ui/src/workflows/workflow-editor/components/WorkflowAppModeDisplayGrid.vue`：watchEffect 从独立结果中匹配并修改 image.presentation。
- `frontend/web-ui/src/workflows/workflow-editor/preview/value-display.ts`：当前按 generation、sequence、snapshot_revision 核对文件汇总来源。
- `backend/service/application/workflows/execution/topology.py`：节点级执行按真实连线取祖先；metadata.overlay 不属于祖先关系。

最后一项意味着当前绑定不能自动成为“单独执行图片节点”所需的上游依赖。Grid 才附加 presentation 也使画布和应用模式的组合入口不一致；这是代码结构缺口，本轮未将所有视图逐一复现为现场故障。

现场截图保存在本机 `data/files/developer/workflow-backups/20260918-display-association/current-app-mode-bindings.png`，不作为运行时依赖。

## 单一关联规则

```text
字段提取 / 计算 / 对象组装 → Value Display.Body ─→ Image Preview.Presentation
图片加载 / 推理结果绘制 ───────────────────────→ Image Preview.Image
                                               ↓
                                   Body：图片 + 可选字段显示
                                               ↓
                                画布 / 应用模式 / 双击大图
```

1. Image Preview 新增可选 `presentation` 输入，显示名 `Presentation`。复用 `response-body.v1` 端口类型，入口严格检查正文为 `type=value-display`，不接受任意 Response Body、图片、嵌套图片或 HTML。
2. Value Display 保持 `body` 输出，不另造同内容端口。可以连接一个或多个 Image Preview，也可以独立显示。
3. 未连接 Presentation：只显示图片，不寻找同名、邻近、最近执行或全局 Value Display。
4. 已连接 Presentation：本次节点接收并输出明确的字段正文。由现有 DAG 保证上游先完成，不在前端等待另一条独立结果再配对。
5. 一个 Presentation 输入只允许一个来源，沿用普通单输入端口约束；需要多个字段时在一个 Value Display 的 Fields 中组织。
6. 移除 `app_mode.displays[].overlay` 和对应前端配对分支。禁止同时保留“连线优先、metadata 兜底”两套行为。

输出使用既有图片 Body 的可选 `presentation` 字段，内容仅包含有界的 Value Display 正文。字段、颜色、字号、半透明背景和尺寸默认值沿用已有实现。图片数据不重绘、不再次编码，也不复制到 presentation 中。HTTP API 继续使用 v1；正文契约和迁移说明同步更新。

## 启用、隐藏与异常语义

| 操作或状态 | 目标行为 |
| --- | --- |
| 不连 Presentation | 图片正常显示，没有字段面板 |
| 连接一个 Value Display | 图片携带该节点本次输出；支持一对多 |
| Value Display 不选为应用模式独立栏 | 仍可执行并供已连接图片使用 |
| Image Preview 不选为应用模式独立栏 | 不占该页面栏目，不改变节点执行语义 |
| 禁用已连接的 Value Display | 图显示失效来源，发布/执行前明确校验，不能偷偷沿用旧值；需要纯图片时解除该连接 |
| 禁用 Image Preview 或所在节点组 | 沿用统一节点/组启用规则；应用模式引用失效必须明确提示 |
| 已连接来源失败、跳过或没有有效输出 | 不伪装成“未连接”，不补旧值；沿用执行失败/分支跳过语义并给出节点定位 |
| Value Display 被删除 | 沿用图编辑器连线删除与撤销机制；关联解除后图片成为纯图片，不保留隐藏引用 |

不新增另一套 `enabled`、`preview_write` 或“全局生产数据显示”开关。节点启用、独立栏目选择、端口连线分别只承担一个职责。源节点被条件分支跳过时，应通过已有 Conditional End 合并有效值后供下游使用；图片输入的可选含义只表示允许不连接。

## 来源一致性与资源生命周期

明确连线解决“使用哪个结果”，不能证明人工连接的图片路径一定属于同一生产记录。当前应用仍须从同一 File Summary 的 latest 与 totals 取得图片和数量。

- 保留可选 Context/Presentation Context 作为额外来源检查，不把它们称为显示绑定，不要求普通实时推理流程伪造 JSONL 的 generation 等字段。
- 当前文件汇总工作流继续使用相同 generation、sequence、snapshot_revision。图片提供 Presentation Context 时，要求关联正文有有效且匹配的 context；不匹配在图片节点明确报错。
- 图片未提供 Presentation Context 时，接受显式连接的本次 Value Display，不跨节点搜索 context。Value Display 自身的 context 仍可表达“汇总未完成”等显示状态。
- 执行身份继续沿用现有 Preview/Runtime run、generation、节点和迭代标识，不以文件 context 代替调用身份。
- 共享适配器从同一个图片 Body 构造图片与 presentation。新一轮、取消、失败、断线与迟到回调沿用现有旧结果标识；禁止新图片复用旧数量。
- 图片未解码时不先显示新面板；大图持有与所展示图片对应的字段快照，不能在旧图片上更新为下一次统计。
- 不通过 App Mode Grid 修改共享图片对象来建立绑定。Object URL 和 mmap 生命周期继续归现有图片管理链路，不增加持有原图的引用。

## 编辑器与应用模式交互

Image Preview 节点显示可连接的 Presentation 端口，属性面板显示“未连接 · 仅图片”或“来自：节点标题 / Body”，可定位来源。该摘要从真实边计算，不另存一份 node_id。节点/组禁用时同时显示来源状态。

Value Display 属性面板可列出已连接图片，便于一处样式变更前判断影响范围。它没有目标图片下拉配置，连线仍是唯一事实来源。

应用模式配置的复选框明确标注为“独立显示”，只编辑显示栏、标题、尺寸和顺序。图片行用只读摘要提示“仅图片”或字段来源；修改关联返回画布定位 Presentation 端口，不在此处另存绑定。

节点标题优先展示用户设置的标题，辅以节点 ID 区分同类节点。所有新增操作、摘要和校验文案接入既有中文、English、日本語、한국어资源。使用现有 Vue 3 控件和主题，不增加新的动效或框架。

## 实现顺序与逐步门禁

| 步骤 | 修改范围 | 完成后验证 |
| --- | --- | --- |
| 1. 契约与基线 | 固定 presentation 正文边界、缺失与失效语义；备份最新草稿、布局、实际发布版本和 Runtime 绑定 | 对照当前四条绑定及节点/组状态；保留相同真实文件作为前后对照 |
| 2. 节点组合 | Image Preview 可选输入与正文检查；复用 Value Display 校验及大小上限 | 无关联、一对一、一对多、错误正文、超限、context 匹配/冲突；原图片返回方式不变 |
| 3. 图校验与执行 | 已连接但禁用/缺输出的识别；复用祖先闭包，不新建执行器 | 节点级执行包含 Value Display 祖先；分支、节点组、循环/并行、取消不读到旧值 |
| 4. 统一渲染 | useWorkflowPreviewDisplays 读取组合正文；删除 Grid 的跨节点配对；复用现有字段组件和查看器 | 画布、应用模式、Runtime 监视、大图一致；迟到解码、切换运行、解除关联无残留 |
| 5. 编辑器明确配置 | 端口/来源摘要、独立显示文案；移除 overlay 下拉与旧序列化 | 增删连线、复制节点/组、撤销重做、保存、导入导出正确；多语言即时切换 |
| 6. 迁移真实草稿 | 从旧 overlay 生成普通边；移除旧 metadata；保留颜色、Appearance、布局、Context 和既有业务输出 | v1 校验与保存后读回；四条边分别连接正确 Value Display，没有重复节点或保存图片 |
| 7. 真实短测 | 使用现有显示日志和图片执行显示图；覆盖纯图片、组合显示、独立字段栏与双击大图 | 数值与磁盘汇总一致；记录整体耗时、传输量和资源回收；不向正式生产 JSONL 追加测试记录 |

约束：正常路径只新增有界字段传递与检查；同一个 Value Display 不因连接多张图片重复执行。展示正文大小的增加需要测量，不能宣称零开销。对未使用 Presentation 的图不增加文件扫描、模型调用、阻塞等待或显示依赖。

## 迁移与发布

迁移是显式、一次性的文档转换，不是运行时兼容分支。备份后将每条旧 overlay 转为 `Value Display.body → Image Preview.presentation` 普通边；无旧 overlay 的图片保持未连接。重复执行迁移不得生成重复边；已有相同边可复用，已有不同来源必须报冲突，不能覆盖用户修改。

迁移范围先清点全部含 overlay 的草稿、导入文档及活动 Runtime 所引用版本，不能只改当前应用。保留原发布版本作为可追溯备份，不原地改写不可变版本。活动版本需由其准确快照生成迁移后的新版本，经真实验证后显式切换；不拿最新草稿覆盖现场版本。没有完成迁移的旧绑定配置必须给出明确错误或迁移提示，不能静默丢失叠加内容。

旧版本再次使用时应先转换并重新发布。部署前必须完成版本切换计划，不能先移除旧解析再让尚未迁移的 Runtime 继续运行。本次按下述验证记录迁移目标 Runtime，其他 Runtime 不切换版本。

## 验收范围

最低场景包括：纯图片、多张图片只绑定其中一张、一个 Value Display 绑定多图、两个独立统计源、字段独立显示、空日志/部分汇总、无 context 的通用显示、错误来源、节点/组禁用、分支跳过、节点级预览、重复执行、图复制/撤销、运行切版、断线及大图跨次更新。

Runtime/Trigger、.NET SDK 的业务输入输出和 IPC 不修改；显示节点自身的新增依赖按普通图执行。短测只核对行为与本机耗时，不代替长期稳定性或模型准确率验收。


## 2026-09-18 实施与验证

- Image Preview 新增可选 Presentation，正文在图片处理前校验；不重绘图片，不修改字段值或上游 Body。Value Display 共用有界正文检查，字段数量、标量、颜色、尺寸和 128 KiB 上限均覆盖。
- 图校验拒绝已连接的禁用来源；输入解析拒绝已连接但返回 null 的正文。现有 DAG、条件分支和祖先闭包继续负责执行，无额外调度器或等待队列。
- 共享图片适配器直接读取 presentation。删除 App Mode Grid 中跨节点查找与写入图片对象的逻辑、旧 overlay 契约和下拉编辑。属性面板提供来源/关联图片定位；四种界面语言均有操作文案。
- 新增一次性迁移工具 `backend/maintenance/workflow_presentation_migration.py`。转换幂等、保留原文档、重复连接不增加边，冲突拒绝覆盖；旧 overlay 不作为运行时后备路径。

现场 project-1 盘点只有当前显示草稿和一个 Runtime 使用旧绑定。草稿保留 82 个节点，连线由 102 增至 106，仅增加四条 presentation 边并删除旧 metadata 绑定；配置参数、节点布局与公开输入输出未重写。

Runtime 使用其原来准确发布快照生成新版本 `workflow-app-version-cb64fe228fd64f7b9b9b505ef201745b`，没有把当前草稿其他变化发布到现场。Runtime `workflow-runtime-71bf1addb3614f24b7554eec8925b343` 已切到该版本，revision generation 为 4，并恢复 running。选版前控制面正确阻止存在启用 Trigger 的切换；随后暂时禁用关联 Directory Trigger，完成选版和启动后恢复原启用状态。原发布快照未改写。

验证结果：

| 检查 | 结果 |
| --- | --- |
| 后端契约、图依赖、迁移、实际 Worker/API | 50 项测试通过；另通过 Parallel、资源 scope 与 Runtime 快照错误提示回归 |
| 前端关联配置、字段显示、图片/查看器生命周期、节点组回归 | 41 项测试通过，TypeScript 检查通过 |
| Python 质量 | 改动 Python 文件 Ruff 检查通过 |
| 真实显示图 | 四张图片分别携带正确字段，治具 96 / 87 / 9 / 90.63%，塑盒 400 / 382 / 18 / 95.50% |
| 混合显示候选 | 只解除治具原图的 Presentation，原图不带面板，其他三张保持关联；候选未保存到正式草稿 |
| 单个图片节点 Preview | 自动执行其 Value Display 上游，只产生目标图片，正文总数 96 |
| 浏览器 | 来源定位、画布预览、四栏应用模式及双击 2560 × 2358 JPEG 大图核对正常 |
| 实际 Runtime 同步 HTTP 调用 | 连续三次约 441、525、385 ms；含本机 HTTP 往返，不含浏览器最终绘制 |
| 浏览器完整 Preview | 首次约 4535 ms，其中 run.started 到达约 3493 ms；热态重跑约 1345 ms，graph 约 408 ms，包含图片传输和显示接收 |

这些是本机短测，不承诺所有调用低于 1 秒，也不能从没有严格对照的样本推断加速比例。新会话候选测试包含启动成本，不能与热态 Runtime 混为同一指标。没有修改模型、JSONL 写入/汇总算法、SDK、Trigger 业务协议或 IPC；测试没有追加正式生产记录。

备份、迁移候选、发布响应、运行快照、实际 Preview 事件及截图位于本机 `data/files/developer/workflow-backups/20260918-display-association/`。这些是验证材料，不参与产品运行。

## 显示边界与命名优化（已实现）

设计审阅发现：Value Display 行未勾选时，标题、尺寸和排序均灰显，且该行没有随图显示的说明，容易被理解为节点或数据显示已禁用。顶部“独立显示”说明不能替代每行的可见语义。审阅阶段保留了画布未保存修改；实施前按已有授权保存草稿，确认保存成功后更新界面。

### 确定的职责边界

- 节点/节点组启用控制执行，继续使用现有机制。
- 图中的普通连线决定图片携带哪组显示数据；不连接时为纯图片。
- 应用模式配置仅控制独立面板的选择、标题、大小和顺序。Value Display 的独立面板未选中，不影响其输出供图片节点使用。
- 不把应用模式的面板选择变成节点的全局显示开关，否则相同图片结果会因页面布局而改变，单节点预览、应用模式和大图的语义再次分裂。
- 解除某张图片的数据连线仅影响该图片；移除独立数据面板仅影响该面板。不自动增删另一类配置。

### 界面调整

1. 对话框使用“应用模式配置”，输出区使用“独立面板”。每行复选框旁显示完整操作名称，不增加顶部说明段落。
2. Image Preview 使用“显示图片面板”；Value Preview 使用“显示数据面板”；Value Display 已有随图用途时使用“另加独立面板”，无随图用途时使用“显示独立面板”。无论文案如何，持久化含义均为独立面板选择。
3. Value Display 行显示配置的 Title，避免重复的 Value Display 标题和 Node 占位文本。配置面板及节点关联摘要不显示内部节点 ID、类型或端口信息。显示由当前连线和当前面板选择实时推导的用途，例如“随图显示：治具原图、治具结果图”。
4. 连接的图片未选为独立面板时标为“已连接，图片面板未显示”，不能计入当前应用模式的可见用途。既无可见图片用途也无独立面板时显示“未在此页面显示”。
5. 图片行使用“图片内数据：治具检测”，未连接时使用“图片内数据：无”。来源采用只读文本和明确的“定位”操作，不使用类似输入框或下拉框的样式暗示可在此修改关联。
6. Value Display 行保持用途摘要正常可读，仅独立面板的标题、尺寸和排序随勾选禁用。摘要、复选框和节点标题以可访问标签关联；颜色不能作为唯一状态说明。
7. 已禁用或不存在的连线来源明确显示异常，沿用图校验，不伪装成纯图片或静默隐藏字段。

### 端口命名

- Image Preview 的 Presentation 显示名改为 **Display Data**。
- Value Display 的 Body 显示名改为 **Display Data**，使两端可直观对应；其他节点的 Body 不统一改名。
- Image Preview 的 Presentation Context 显示名改为 **Data Context**，帮助说明其可选的数据来源校验用途。
- UI 中的连线详情、来源摘要、提示和文档示例使用显示名；诊断需要时另行显示技术标识。节点端口沿用简洁英文，应用模式操作文案沿用界面语言设置。
- 本次命名优化只改 display_name，保留现有 `presentation`、`body`、`presentation_context` 端口标识和响应结构，避免为显示名称再迁移已保存连线或增加别名兼容路径。

### 实现与验证顺序

1. 调整三个端口显示名及 UI 连线详情的显示名解析，验证序列化仍使用原端口标识。
2. 从当前图和面板选择派生 Value Display 的用途列表；覆盖一对多、部分图片隐藏、未连接、来源禁用及重复标题。
3. 修改布局对话框的可见复选框标签、用途摘要、来源定位和默认标题，补齐已有四种界面语言。
4. 验证取消/应用、取消独立面板、解除单张图片连线、两者都启用等操作互不修改其他职责的数据。
5. 使用实际显示工作流核对画布、应用模式和大图；测试不追加生产日志、不切换 Runtime 版本。若前端更新可能刷新页面，先核实保存草稿授权和当前编辑内容。

设计审阅截图：`display-config-boundaries.png`、`display-config-value-rows.png`，保存在上述本机验证目录。

### 本轮实施核对

- 端口显示名及连线详情已更新，实际定义仍为 `presentation`、`presentation_context` 和 `body`；不存在字段迁移或新运行分支。
- 配置面板已实现可见勾选标签、只读来源、随图用途和定位；节点标题优先采用配置 Title，新独立面板默认使用该标题，已配置的面板标题不覆盖。按后续简化要求移除常规界面的节点 ID、类型和端口附注，定位仍通过原始节点标识执行，不以标题建立关联。
- 20 项前端测试通过，覆盖布局应用/取消、一对多、禁用来源、隐藏图片与独立面板互不干扰、四语言切换、图像结果和大图生命周期。TypeScript、Ruff 与差异检查通过。
- 实际显示草稿 Preview 成功，完整接收约 3286 ms，其中开始事件到达约 2693 ms；这是单次新会话样本，不作为性能提升或退化结论。
- 实际 Runtime 四张图片显示正常；治具 96 / 87 / 9 / 90.63%，塑盒 400 / 382 / 18 / 95.50%。双击治具结果图后，2560 × 2358 JPEG 大图仍显示对应 NG 和统计。
- 浏览器操作验证了勾选后取消独立面板仍保留随图用途，以及取消图片面板会即时变更用途提示。测试布局修改通过“取消”退出，没有持久化测试配置，也没有发布或切换 Runtime 版本。
- 实施截图 `layout-explicit-usage.png`、`layout-runtime-large.png` 保存在上述本机验证目录。本轮未修改模型、JSONL 算法、执行器、IPC 或 SDK。
