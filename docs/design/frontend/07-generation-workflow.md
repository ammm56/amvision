# 生成、筛选与交付流程

## 1. 目标

本流程用于把架构事实转为一致的视觉方向、结构化页面和可实施的前端设计。最终交付不以“生成了多少张图”为标准，而以页面覆盖、业务准确、组件一致和可实现性为标准。

## 2. 工具分工

| 工具 | 主要用途 | 不应承担 |
| --- | --- | --- |
| OpenAI Image 2 | 视觉方向、构图、密度、关键页高保真截图、状态变体 | 精确可编辑组件、完整交互原型、最终文字校对 |
| Google Stitch | 页面结构、组件层级、批量页面、交互关系、响应式方案 | 替代后端契约、自动决定产品边界 |
| 设计评审 | 筛选、统一、修正业务语义、补状态 | 只按“好看”选择方案 |
| Vue 3 实现 | 落地组件、数据流、路由、可访问性、性能 | 逐像素复制无法实现的生成装饰 |

## 3. 阶段一：建立视觉基线

### 3.1 生成页面

先使用 OpenAI Image 2 生成：

1. G01 浅色工作台外壳。
2. G02 深色沉浸工作台外壳。
3. D01 数据集工作台。
4. M03 训练详情。
5. I01 推理实验室。
6. W03 流程编辑器。

这些页面覆盖导航、表格、图表、图像画布和节点画布，足以判断设计方向是否能支撑整个产品。

### 3.2 筛选标准

- 信息密度是否适合工作站长期使用。
- 左侧导航、顶部栏和页面标题是否清楚而稳定。
- 品牌绿是否克制且有清楚语义。
- 浅色和深色工作区是否属于同一产品。
- 表格、图表、画布和检查器是否能真实实现。
- 是否避免了营销后台、赛博朋克和通用 AI 产品风格。

### 3.3 固定参考

选定一张浅色和一张深色参考图。后续 Image 2 页面都基于参考图生成，并明确“保持外壳、颜色、字体、间距和组件风格不变”。

## 4. 阶段二：在 Stitch 建立设计系统

1. 输入 [项目级主提示](06-google-stitch-prompts.md#2-项目级主提示)。
2. 先生成 AppShell、PageHeader、StatusBadge、FilterBar、DataTable、RightInspector。
3. 提供已选 Image 2 参考图，要求只吸收视觉语言，不改变信息架构和资源命名。
4. 生成 P01、T01、D01、M01 四个列表型页面，检查组件复用。
5. 如果页面风格分叉，立即使用“组件复用补充提示”收敛，不继续扩页。

## 5. 阶段三：按业务域生成页面

### 5.1 数据域

顺序：D01 → D02 → D03 → D04 → D05 → D06。

检查点：

- Dataset、DatasetImport、DatasetVersion、DatasetExport 是否分开。
- classification/detection/segmentation/pose/obb 的格式选择是否正确。
- 校验报告是否包含 error、warning 和下一步。
- DatasetExport 是否被明确标为训练输入。

### 5.2 模型域

顺序：M01 → M02 → M03 → M04 → M05 → M06 → M07 → M08。

检查点：

- 模型任务组合是否符合支持矩阵。
- warm start 与 resume 是否分开。
- train、val、test 是否遵守各自用途。
- best 与 latest checkpoint 是否分开。
- 转换目标是否只包含当前已实现能力。

### 5.3 运行域

顺序：R01 → R02 → I01。

检查点：

- DeploymentInstance 是否被表现为长期服务。
- sync 与 async 是否清楚。
- runtime、device、precision 是否动态兼容。
- 推理画布是否按五类任务正确显示结果。

### 5.4 自动化域

顺序：W01 → W02 → W03 → X01 → N01。

检查点：

- GraphTemplate、Application、AppRuntime、Run 是否分层。
- workflow 内模型推理是否选择已部署实例。
- TriggerSource 是否绑定指定 runtime。
- custom node 是否展示 manifest、权限、隔离和版本。

### 5.5 系统域

顺序：C01 → S01 → S02 → S03。

检查点：

- conda 开发环境与 bundled Python 发布环境是否能被中性表达。
- CPU、CUDA、OpenVINO GPU/NPU、TensorRT 是否有真实可用性状态。
- 离线与重连是否允许保留只读信息。

## 6. 阶段四：补齐状态

每个资源列表至少补以下状态：

- 首次空状态。
- 有数据的标准状态。
- 加载状态。
- 筛选无结果。
- 后端重连。

重复的列表状态以 [G03 资源列表状态参考](generated/00-foundation/G03_resource-list-states_light_reference_v01.png) 作为共享实现基线，并在 P01、T01、D01、M01、M04、R01、W01、X01、N01 的标准页面中复用。页面特有的首次空状态仍单独生成或在逐页规格中明确。

首次空状态的领域参考已覆盖：

- [T01 任务中心](generated/01-projects-tasks/T01_task-center_light_empty_v01.png)：不提供通用新建任务，明确有限任务与长期 runtime 边界。
- [M04 验证与评估](generated/03-models/M04_evaluation-center_light_empty_v01.png)：缺少模型版本或评估数据时禁用创建与比较。
- [X01 触发源](generated/05-workflows-integrations/X01_trigger-source_light_empty-no-runtime_v01.png)：没有 healthy runtime 时禁用模板、映射、测试和保存。
- [N01 自定义节点目录](generated/05-workflows-integrations/N01_custom-node-catalog_light_empty_v01.png)：本地目录为空时引导扫描并展示 NodePack 合同要求。

每个任务详情至少补以下状态：

- queued。
- running。
- succeeded。
- failed。
- cancelled。

任务状态以 [G04 有限任务生命周期参考](generated/00-foundation/G04_finite-task-lifecycle_light_reference_v01.png) 作为共享状态机基线。T02、M03、M08 只需额外生成页面结构或领域数据明显变化的状态，不能通过复用旧 task ID 表达重试。

每个长期实例至少补以下状态：

- stopped。
- starting。
- healthy。
- degraded。
- failed。

长期实例状态以 [G05 长期实例生命周期参考](generated/00-foundation/G05_long-runtime-lifecycle_light_reference_v01.png) 作为共享运行状态基线，并在 R02、W02 中复用。页面可以使用领域专属字段，但不得把长期资源表现为 `succeeded` 或 `cancelled` 的有限任务。

关键危险操作补确认框：删除 DatasetImport/Export、删除训练/转换任务、停止有 workflow 引用的部署、删除 runtime、禁用高权限节点包。

危险操作以 [G06 危险操作确认参考](generated/00-foundation/G06_danger-confirmations_light_reference_v01.png) 作为共享交互基线，并映射到 D03、D06、M03、M08、R02、W02、N01。实现时必须以 REST 预检为最终依据；输入不匹配或存在 blocker 时，不得启用危险按钮。

## 7. 阶段五：窄桌面与工业环境检查

使用 `1366 × 768` 检查：

- 左侧导航折叠后仍可识别当前模块。
- 页面标题、状态和主操作不被隐藏。
- 表格隐藏的是次要列，不是名称、状态或主要关系。
- 右侧检查器可覆盖打开和关闭。
- 图像画布仍保留主要结果区域。
- 流程编辑器可在节点库与检查器之间切换。
- 关键操作点击区域不小于约 `40px`。

## 8. 文件和画板命名

### 8.1 目录建议

```text
design-output/
├─ 00-foundation/
├─ 01-projects-tasks/
├─ 02-datasets/
├─ 03-models/
├─ 04-deployments-inference/
├─ 05-workflows-integrations/
├─ 06-settings-system/
└─ 90-archive/
```

### 8.2 文件名

```text
<page-code>_<page-name>_<theme>_<state>_v<revision>.<ext>
```

示例：

```text
D01_dataset-workbench_light_populated_v03.png
M03_training-detail_light_running_v02.png
W03_workflow-editor_dark_preview-success_v04.png
R02_deployment-detail_light_failed_v01.png
```

### 8.3 画板名

画板标题保留页面编号、路由和状态：

```text
M03 · /models/detection/training-tasks/:id · running · 1920×1200
```

## 9. 设计决策记录

每次确定重要方向时记录：

- 决策：例如“主工作台默认浅色，流程编辑器默认深色”。
- 原因：例如“表格阅读和长时间工作更适合浅色，节点画布需要更强对比”。
- 影响页面：列出页面编号。
- 被放弃方案：只写关键差异。
- 参考图或 Stitch 页面版本。

不要把临时生成提示和正式产品边界混为一份文档。产品边界发生变化时，先更新架构文档，再同步设计提示。

## 10. 单页评审清单

### 10.1 业务

- 页面对象和状态是否正确。
- 主操作是否符合当前资源下一步。
- 来源关系、版本和 Project 是否可见。
- 不支持能力是否被隐藏或说明。
- 错误和恢复动作是否真实。

### 10.2 结构

- 五秒内能否识别页面目的、当前状态和主操作。
- 首屏是否先展示决策信息，再展示日志和 JSON。
- 是否过度卡片化。
- 表格和检查器是否承担了合适的信息。
- 关键画布是否获得足够空间。

### 10.3 视觉

- 是否符合人工、洁净、未来感。
- 色彩是否克制且语义统一。
- 字号、行高、对比度是否适合长时间工作。
- 深浅主题是否保持同一品牌语言。
- 是否存在生成式乱码、重复控件或不可实现装饰。

### 10.4 实现

- 是否能映射到 Vue 3 组件。
- 是否能使用现有 REST、WebSocket 和 schema 数据实现。
- 是否需要后端尚不存在的数据；如果需要，必须标记为规划依赖。
- 是否包含 loading、empty、error 和 permission 状态。
- 是否在 `1366 × 768` 仍可用。

## 11. 交付清单

完整设计交付至少包括：

- 浅色和深色 design tokens。
- AppShell、导航、顶部栏和页面标题规范。
- 表格、筛选、表单、向导、状态徽标、确认框和空状态组件。
- 图表、图像画布、视觉叠加和日志查看器。
- Workflow 节点、端口、连线、节点组、检查器和运行面板。
- [逐页设计规格](04-page-specifications.md) 中全部页面的标准状态。
- 六个关键页面的运行中或选中状态。
- 任务失败、runtime 失败、离线和无权限状态。
- `1920 × 1200` 与 `1366 × 768` 两种桌面宽度。
- 页面到 Vue 路由、组件和后端资源的映射表。

## 12. 与前端实现交接

交接时按页面提供以下内容：

1. 页面编号、名称、路由和状态。
2. 标准画板和关键状态画板。
3. 使用的共享组件和页面专用组件。
4. 字段、操作、权限和数据来源。
5. 响应式行为。
6. 动效说明。
7. 当前后端已支持与规划依赖的分界。
8. 验收截图或交互说明。

设计稿进入实现前，应再与 [模型支持清单](../../architecture/model-support-matrix.md)、[模型数据集格式规范](../../architecture/model-dataset-format-contract.md) 和实际前端路由核对一次。
