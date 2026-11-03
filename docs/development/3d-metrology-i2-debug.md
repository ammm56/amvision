# I2 同次提取调试契约

## 1. 范围与入口

服务现有 Extract Boundary / Cloud Preview，不新增测量节点、资源系统或查询服务。`capture_debug: bool = false` 位于提取节点参数外层，与测量 `settings` 分开。只有显式开启时才捕获；方法摘要仍只对测量参数求值，算法、质量与数值不变。节点包为 `0.1.16`，提取/显示节点为 `0.1.14`；三维数据契约仍为 v1。

开启捕获的 features 沿已有 Cloud Preview `features` 输入接线；没有连线时不输出该附件。失败边界不变成有效曲线，背景使用同观测、同空间的原云或局部点云。

## 2. 字段

`BoundaryDebugReference` 为 `amvision.boundary-debug-ref.v1`。`capture_id` 随调用生成；`run_id/node_id/invocation_id/observation_id/feature_id/parameters_sha256` 共同约束来源。不能只按特征名称查找；跨 Run、旧调用、摘要不符直接拒绝。

`BoundaryDebugDisplay` 为 `amvision.boundary-debug.v1`，位于现有显示正文的 `boundary_debug` 数组。

| 字段 | 规则 |
| --- | --- |
| `identity` | 完整运行引用，核对当前边界特征、观测、方法 |
| `state/reason` | `ready/unavailable/not-executed`；未开启时无附件。不可用无二进制正文，不携上次结果 |
| `failure_field/required_bytes` | 容量不足时的字段或阶段、所需字节；不是测量质量失败原因 |
| `stage` | `input/grid/candidates/selection/complete`，只代表实际执行阶段 |
| `selection_complete` | 是否完成全部选择；提前歧义时可显示全部已生成候选，不补做后续选择 |
| `measurement_reason` | 原测量原因，与附件可用状态独立 |
| `evaluation` | 本次实际评价面、frame/unit，不从草稿或显示云重建 |
| `grid` | 原点、格距、`shape=(Nu,Nv)`、种子窗、分区方法、选中组件；U 主序/V 次序 |
| `target_ids` | 当次目标顺序；候选局部序号不是跨 Run 持久 ID |
| `data` | base64、小端二进制、SHA-256、精确字节数、最多 48 个数组描述符 |

描述符包含 `name/dtype/components/count/offset/byte_length`。类型为 float32/float64/uint8/uint64/int64，components 为 1–4；元素宽度对齐、连续且精确覆盖正文。浏览器检查字段白名单、类型、形状、长度、摘要、有限值、来源及拓扑范围，不猜布局、不截断后声称完整。

### 全格与四侧剖面

- `input_source_indices` 保留原始输入行号；`bin_rows` 对应局部输入的真实格索引，未分箱项保留既有负值语义。
- `counts/heights/spread/usable/foreground/selected` 覆盖整个有限格网；栅格分区另带 `grouped/components`。空格高度的二进制零只作占位，必须结合计数/可用掩码，不是测得零高度。
- 实际距离分区的 `metric_uv/metric_rows/metric_labels/metric_seed` 直接来自本次空间分区；通过输入行映射追溯，不从背景显示采样重新计算。
- `profile_positions/offsets/breaks/kinds/cells/weights` 对应原四侧剖面。保留来源格、插值权重、格边估计、缺邻点及阈值未夹住；按 breaks 断开。闭运算连接格不伪装为实测点，缺格不补点。

### 全部候选

- `candidate_positions/indices/offsets/closed` 保存已经形成的全部有序候选，不只保存命中部分。
- 原始候选只保留实际引用的源点。生成截线保留 `source_edges/source_weights`、实际引用的 `surface_face_ids/surface_faces` 及 `section_edges/section_face_offsets/section_faces`。局部重编号只压缩布局，原始行号通过 `input_source_indices` 保留，不复制无关源三角面。
- `selection_events` 每行为目标序号、候选序号、状态、已检查点数。状态 0 未命中、1 通过本阶段条件、2 闭合条件拒绝。提前退出后没有事件的候选明确为未评价，不再次遍历算法补图表。

## 3. 所有权与容量

`BoundaryCapture` 登记到已有 CloudRuntime `storage_scope`。算法数组仅在回调期间借用，分块冻结到该 Scope 所有的临时文件；不挤占后续测量的活跃点云数组额度。原始行号映射只在内核调用期间借用，finally 清空，不留全局 NumPy 引用。

同 Run 冻结字节复用 `CloudArrayBudget`，上限为既有 Preview `max_data_bytes`；捕获副本与编码受既有工作预算限制，没有新生产参数。容量、临时存储及额外分配失败只使附件不可用；取消继续中断执行，身份错误、正文损坏明确报错，不吞为容量不足。

Cloud Preview 先预留附件状态空间，再生成基础显示，最后附加有界正文。跨进程复用现有 Preview/runtime 大正文通道，不交付文件句柄、裸数组，不把大正文塞入控制消息。冻结后不依赖仍存活的 CloudRuntime。

浏览器对编码字符串、解码数组、短时副本和 CPU/GPU 缓冲分别计量，短时解码额度及时释放。单个格网 Mesh、少量线/点缓冲、20 行分页，不逐格创建 Vue 或 Three 对象。附件容量不足保留基础点云与测量。换 Run、目标、晚返回、关闭、取消、卸载复用原代次/AbortSignal/renderer 生命周期。

## 4. 所有读取方与保存

| 链路 | 处理 |
| --- | --- |
| 参数/Catalog/发布 | 同批生成 schema；默认关闭，仍走既有包版本/指纹准入 |
| BoundaryFeature | 可选运行引用；普通未捕获特征不输出空引用 |
| 拟线/拟圆及尺寸证据 | 排除 `debug_capture`，临时引用不进入测量证据或摘要 |
| save-cloud/read-cloud | 普通资产排除临时引用；继续保存点、来源与边界证据，不新增调试资产格式 |
| Preview/runtime 显示 | 源 Scope 结束前冻结；原大正文传输与只读显示路径承载附件 |
| 浏览器 | 核对同观测/方法后解码；格网、剖面、候选表与拾取联动，不触发后端重算 |
| Trigger/.NET 数值接口 | 数值协议不变，不增加 SDK 诊断字段 |

派生点资产不能恢复不存在的完整格网；重新捕获需要原始输入并显式执行。保存过的有界显示正文可以只读重开；`record=none` 的 App Mode 刷新后等待下次运行，不承诺自动保留每次显示或完整原云。

## 5. 验证与限制

定向测试覆盖逐格真值、原始行号、开关等价、缺格/闭运算、未选候选、提前歧义、闭合拒绝、容量/分配失败、摘要损坏、取消回收、资产排除临时引用，以及前端晚返回、候选首开、切换、拾取、分页、冻结正文重开。完整样本通过真实发布 → Runtime → Trigger → 显示/数值 → 停止回收检查；实测记录见[界面验收第 7 节](3d-metrology-ui-validation.md#7-i2-同次完整提取调试2026-10-30)。

I2 不完成 I3 ROI 显示开关、I4 单视口窄屏编辑、I5 三对象逐项参数修改/取消/发布验收。S2 删除角块稳定性与秒级检测节拍仍未通过，不调整质量门禁或显示容量。
