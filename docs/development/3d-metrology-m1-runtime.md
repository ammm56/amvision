# 3D Metrology M1 运行引用与资源生命周期

日期：2026-10-22。承接[输入适配记录](3d-metrology-m1-input.md)，设计仍以[实施基线](3d-metrology.md)为准。

本文保留运行生命周期阶段的验证记录。后续资源 v2、资产恢复与保存导出进度见[资产实施记录](3d-metrology-m1-assets.md)，不将本文当时未实现项误读为当前全部状态。

## 状态

**M1 尚未完成。** 本阶段实现运行内点云引用、同一 owner 的分支借用、派生索引与原件关系、资源关闭失败的进程隔离，以及单位归一和有效点过滤算法。尚无可启用的六节点 Catalog，也没有宣称 Trigger/SDK、资产 v2、保存导出或三维页面可用。

生产 timeout、运行容量、预览容量仍未填写。测试值仅用于本阶段验证。没有新增 Broker、执行器、每节点进程、等待队列或另一套发布管理。

## 复用与扩展

| 边界 | 实际实现 |
| --- | --- |
| 通用 Scope | 扩展现有 `ResourceScope`，显式声明需要先于外部文件/lease 清理的资源。默认资源仍在原有后置阶段关闭；关闭失败保存真实对象与诊断，重复 close 不返回虚假的成功 |
| Snapshot | 输入校验、准备和执行都进入同一收尾保护区。原异常的已退栈局部变量先释放，保留 traceback 位置及原因，避免异常记录长期持有 ndarray/mmap 别名 |
| 进程恢复准入 | 运行 Scope 关闭失败时，由现有 process Scope 保留，禁止再次执行 Snapshot。Runtime worker 明确发送不可复用标记；Preview 复用已有整组停止、隔离槽位和 deferred cleanup |
| Runtime 父进程 | 在请求分发前登记已知输入归属，而不是等失败响应后登记。正常、身份匹配的释放证明解除登记；未知结果或关闭失败先整组停止，再回收已知输入及未交付响应 owner |
| 停止/回收失败 | 登记留在原 handle；上层重复 cleanup 不能越过该归属提前释放。Broker/文件回收失败不丢掉登记，不开放旧 worker 恢复准入。迟到响应不能交付已经回收的输出 |
| 点云引用 | `point_cloud_runtime.py` 采用现有 Contract。`run_id/cloud_id/revision` 与完整引用快照一起核验；源字段、点数、空间、来源或 observation 被修改均拒绝 |
| 点云存储 | `CloudRuntime` 只存在于现有运行 Scope。原数组、映射、派生索引都由其子 Scope 持有；不写入 API/IPC/历史记录，不新建全局点云缓存 |
| 同机映射 | `MappedCloudArrays` 复用已经验证的 `borrow_cloud_buffer` 和真实 LocalBuffer guard，一次输入 acquire 一次；下游分支只借用同一 owner。关闭失败保留 guard，不因 generator 退出而丢失归属 |
| 解码期间 | 引用发布前的文件解码也计入活跃操作；收尾不能因 registry 尚无完整引用就提前删除源文件 |
| 派生关系 | 过滤保存严格递增的 uint32/uint64 索引。逻辑子集按显式块大小访问，不隐式复制整云；经过物化单位转换后仍保留原始行号和原件读取参数 |

上述扩展使用相同 Python 业务接口；没有增加 Windows 专用业务分支。实际进程归属和停止继续由现有跨平台适配器负责。Ubuntu 运行数据和 mmap 目录限定原生文件系统，源码和只读样本可位于 Windows 挂载盘。

当前父进程接管的是分发时已登记的输入及固定响应 owner。本阶段不宣称已经覆盖未来 Save/Export 的写入中断、节点动态创建的全部外部资产或发布依赖变更；这些必须随资源 v2 与六节点提交路径验证，不能用本阶段输入回收测试代替。

## 数据与算法

- 文件入口继续使用既有 file-ref 校验与同一受控解码器；没有新增文件解析器。读取成功后才登记运行引用，保留完整字段映射、profile、原始 spatial 和 PCD 元数据。
- 当前完整样本继续保存、传递 float32；原文件声明 float64 时保持 float64。二进制 uint64 属性不转换为 JSON number 或 float64。
- Normalize Units 只进行显式单位确认及 m/mm/um 到 mm 的换算。每个长度标量按自己的单位转换，其他属性保持。整数使用整数运算；无法保持整数、越界、有限浮点溢出或非零值下溢为零都拒绝。浮点只在有界块内使用 float64。
- Filter Valid 始终尊重 validity，positions 必须参加有限性检查。零坐标不默认无效；哨兵必须精确可表示，int64/uint64 使用规范十进制字符串。各原因计数可以重叠，不相加冒充删除数。
- 过滤先计数再精确分配索引，第二次扫描维持源顺序。空派生云为真实 ready、零点资源，不伪装成缺测。读取、转换与过滤都使用同一显式活跃数组预算，容量不足立即拒绝。
- 同一输入多个分支共享原件；没有自动保存原始点云。本阶段仍未提供持久资产引用或历史重放能力。

## 样本验证

完整输入为 479,677,235 字节、14,745,099 点的既有 ASCII PLY，不截取前缀。验证链路为：

`ObjectStore 不可变文件 -> 文件引用/摘要核对 -> 严格解码 -> 运行引用 -> Filter Valid -> 全量数据/源行号核对 -> 真实 mmap 写入/发布 -> 同机运行引用 -> Filter Valid -> Scope 收尾 -> mmap 回收`

Windows 和 Ubuntu 原生 ObjectStore/mmap 均通过。两个入口及过滤后的完整 float32 数据 SHA 均为 `956927f058ba4a0170b1c1b93b1411b613fbe21fcbfc278ad0a7fc3cf621a1c6`；全部点保留，源行号一致。样本没有已确认单位，报告仍为 null，未擅自应用 mm 换算。单位算法使用另外的独立合成真值测试。

记录：[Windows](evidence/metrology3d-m1-runtime/sample-windows.json)、[Ubuntu 原生目录](evidence/metrology3d-m1-runtime/sample-ubuntu-native.json)。两条源数组及两个索引的活跃数组记账为 471,843,168 字节；Scope 关闭后归零，mmap 从借用中的 revoking 到 released。这不是进程 RSS、主机容量或 1 GB 全算法验收结论。

复现脚本仍为 `python -m scripts.verify_metrology3d_file_input`，预算参数全部必填。本次显式测试配置：header 65,536、decoded 400,000,000、working 134,217,728、chunk_rows 65,536、chunk_bytes 4,194,304、live_array 800,000,000；array lease 300 秒、arena 最小块 4096 字节、reader slots 4、revocation grace 10 秒，arena 容量按已知数组长度计算为 268,435,456 字节。以上数值不写入生产配置。

## 回归与审计

覆盖源文件与坏文件、字段精度、同机 guard、引用篡改/跨 run、嵌套子集、物化后原始行号、原件保留、取消各阶段、借用未结束、guard 关闭失败、重复 close、并发 close、Snapshot 准备失败、异常 traceback 持有、停止失败、回收失败和 monitor/迟到响应竞态。

真实 Preview 子进程注入关闭失败，验证失败 worker 不复用、整组停止、通道关闭和 pin/预留归零。既有图片、文件、连接器和 sync/async Runtime API 一并进入组合回归。

最终记录：

| 验证 | 结果与边界 |
| --- | --- |
| Windows 最终组合 | 316 项通过，77.09 秒；包含下列全部文件/目录 |
| Ubuntu 组合 | 314 项通过，362.47 秒；原生测试数据和 Python 缓存，包含相同范围，当时尚未增加两个参数/摘要校验用例 |
| Ubuntu 最终定向回归 | 77 项通过，78.52 秒；覆盖点云运行/预处理、Scope/Snapshot、worker 归属与真实 Preview，包含两个新增用例，不与 314 相加宣称一个更大的组合 |
| 完整样本 | 两平台原文件、数组、过滤后数组和真实 mmap 入口摘要一致，Scope/reader 回收完成 |

组合范围：

```text
tests/test_point_cloud_contracts.py
tests/test_point_cloud_local_array.py
tests/test_point_cloud_runtime.py
tests/test_metrology3d_preprocess.py
tests/integration/metrology3d/
tests/integration/controlled_io/
tests/test_metrology3d_activation_boundary.py
tests/test_object_store_immutable_directory_collision.py
tests/test_workflow_resource_scope.py
tests/test_workflow_resource_finalization.py
tests/test_workflow_execution_cleanup.py
tests/test_workflow_worker_resource_retention.py
tests/test_workflow_worker_manager_cleanup.py
tests/test_connector_nodes.py
tests/test_workflow_preview_worker.py
tests/test_workflow_runtime_invoke_api.py
```

Ubuntu 留有一条 Starlette 对 AnyIO BlockingPortal 别名的 DeprecationWarning，不是用例失败。本阶段没有为消除该第三方警告修改应用逻辑。早期 Windows 沙箱内真实进程测试未完成，已终止该次运行；正式 Windows 真实进程验证在具备本机进程权限的环境完成。WSL 首次准备隔离环境时缺少依赖，补齐后重新验证，不把收集失败或环境缺失当作通过。

本阶段没有修改模型网络、权重、推理数值、产品公差规则或既有部署实例数准入，没有运行 P99 或长稳测试。共享运行时的行为变更集中在收尾顺序和异常恢复门禁，正常数据与测量算法验证不能替代工业计量准确度或长期运行认证。

## 后续顺序

1. 将已验证的运行引用与读取/归一/过滤算法接入同一六节点包内部入口和参数规格；补齐 unavailable 消费、Cloud Preview 的独立有界显示证据。不能直接发布缺少资产分支的 Read Cloud。
2. 沿现有 MeasurementResourceService 完成资源 v2、迁移/旧发布只读保护、不可变保存、幂等提交、原件及派生数组保存和受控交换导出。验证提交前后取消、磁盘满、进程强杀和引用删除保护。
3. 接入现有 App Entry、local-shared-memory Trigger 的显式点云业务格式、SDK 及有界文件接收。当前 acquire-view helper 和 mmap 测试不等于 PREPARE/REQUEST 端到端完成。
4. 在现有 Vue Workflow/Preview 扩展有界三维查看器、字段/单位/ROI 交互及持久引用入口，复用现有连接，执行真实浏览器生命周期与页面回归。
5. 使用同一完整样本完成双平台六节点端到端验收；生产 timeout、容量和显示上限确认后，才一次性注册正式包，删除内部目录阶段命名，不保留双实现或转发别名。

后三项的规格已经存在，不重新设计 Workflow、节点系统或版本管理。内部实现可以继续，生产参数待确认不构成伪造默认值或提前启用的理由。

## 环境清理

- Windows 与 WSL 进程检查未发现本轮测试、样本脚本或子进程残留；本阶段没有启动常驻 backend、worker 或 Vite 开发服务，原有非测试进程未被停止。
- `.tmp/m1-lifecycle/` 和 Ubuntu `/home/am/.cache/amvision-m1-lifecycle/` 已删除，包括隔离 venv、样本副本、arena、pytest 数据和本轮缓存。原有 `.tmp/pytest-cache/`、共享工具缓存和原始样本未删除。
- 正式证据保存在本页及 evidence 目录；受控 wheel 保留在既有运行时资产目录。没有修改原 conda 环境、生产依赖锁、运行数据、节点 manifest 或发布目录，没有创建提交。
