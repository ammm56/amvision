# 运行时未关闭问题与根因核对

本文保留实施前的历史审计状态。后续修复和当前验收结果见 [IPC 与运行时修复验收结果](runtime-repair-results-20261015.md)，不以本文的历史“未修复”字样代替当前状态。

## 结论与范围

2026-10-15 对 `outer-frozen-*` 最终候选继续诊断。本轮没有修改生产源码、模型产物、默认配置、驱动时钟或验收门禁。新增文件只有诊断脚本、证据和本文；原有工作区修改未回退。正式性能状态仍是 **not_passed**，不能用独立诊断 profile 的成功退出替代。

当前清单包含三类未关闭问题：EventRing owner 探测与启动竞争、无模型小图尾延迟、默认模型尾延迟。已捕获的机制和仍未证实的归因分别如下，不把一次现象推广为全部历史失败的原因。

## EventRing 探测与启动竞争

**已受控复现的功能缺陷，未修复。**

`backend/service/infrastructure/ipc/local_message/event_ring.py` 的 `MmapEventRingReader.owner_alive()` 使用 `acquire_mmap_owner_lock()` 探测存活。该操作实际取得与 publisher 相同的独占内核锁，再立即释放。publisher 启动则在 `_initialize_files()` 中非阻塞取得同一把锁。双方没有区分“真正的 owner”与“探测者”。

固定调度顺序的复现结果：

1. 旧 publisher 的真实锁及 mapping 已释放，模拟异常退出留下未关闭 header。
2. reader 取得探测锁后暂停。
3. 新 publisher 启动被 `MmapOwnerLockBusyError` 拒绝，尽管没有旧 publisher。
4. 第二个 reader 把第一个 reader 的探测锁误判为 owner 存活。
5. 释放探测锁后，新 publisher 立即正常启动。

复现使用真实 Windows byte-range lock，控制线程调度，不替换锁函数的行为。脚本与结果为 `data/acceptance/runtime-root-cause-20261015/probe_owner_race.py`、`owner-probe-race.json`。现有 forced-owner-exit 测试仅顺序执行探测和重启，没有覆盖这次交叉调度。

实际 `span-diagnostic` 发行启动也出现 `inference-status/owner.lock` 被占用并退出。启动失败日志已保留，正式停止入口完成清理，之后没有服务进程残留。但该次失败没有记录持锁者，**不能把受控复现自动当作该次失败的完整因果证明**。

问题位于共用 IPC 探测协议，不是 Windows Job Object 或 Linux 进程组回收本身。WSL 本轮系统 Python 缺少 Pydantic，未重跑完整 EventRing 复现；此前 Ubuntu 组合回归不能替代这项新竞态的验证。

Git 追溯显示该探测函数来自 `0742833b`（2026-08-27，`feat(local-message)!: 统一本机结构化消息通道`），当前未提交差异没有改变这段函数。`service_status_channel.py` 已在 `0b393829`（2026-09-19）引入并使用 EventRing。不能把这项旧竞态归因于本轮 Windows 进程归属实现，也不能因为它存在而重做整个跨平台启动体系。

修复约束：存活观测不能占用 owner 启动所需的独占权；继续复用现有 IPC 和平台适配层，保持异常退出检测、epoch 校验和单 owner 拒绝。不能用删除锁文件、只看 PID、无限重试或忽略重复 owner 异常遮盖问题。涉及协议身份时须显式升级并同步读写双方，不增加兼容降级。

## 无模型小图尾延迟

**已定位一类同步尖峰；历史 P99 失败窗口仍未完整归因。**

`gc-diagnostic` 使用同一发行候选，只注入 Python GC callback，不关闭 GC、不修改阈值、不新增线程。捕获 backend PID 28668 一次 generation 2 自动回收，持续 **173.1996 ms**，回收 20,771 个对象。耗时在 callback 的 start/stop 时间之间记录，栈枚举与日志写入发生在 stop 时间之后。

触发线程的现有调用链为：

`ZeroMQ trigger -> WorkflowRuntimeService._admit_sync_workflow_run -> get_workflow_app_runtime_health -> Repository.get_workflow_app_runtime -> SQLAlchemy cache-key 对象构造 -> generation 2 GC`

同轮四个无模型客户端在相近请求位置分别出现 **198.6071、199.5994、197.7526、195.7534 ms** 最大延迟。后端 GC 记录包含触发 trace ID；SDK 报告没有逐请求 trace ID 和绝对时间，不能声称已做四个请求 ID 的严格一一连接。

这是共享 Python 后端上的全代回收暂停，SQLAlchemy 栈是触发分配位置，不等于已经证明 SQL 查询本身执行了 173 ms。不能归因于 GPU、模型排队或 SDK 的 Gen0 GC。增加同解释器线程不能隔离这一暂停；全局禁用 GC 或无边界冻结对象也不能作为长期运行修复。

但是，原正式失败轮小图 shared P99 **35.444 ms** 表现为四个客户端约第 21–35 次请求同时变慢，最大值约 37–45 ms，并不是单个 170–200 ms 尖峰。历史轮关闭了阶段 diagnostics，缺少该窗口的执行时间线。**173 ms GC 不能直接解释该轮 P99 失败。**

修复应针对实际分配与控制路径，保留停止、generation、fingerprint、worker epoch 和实际模型容量校验；不能简单删 ORM 校验或缓存可变状态来换取延迟。持续慢窗口在取得可关联的低扰动证据前保持未关闭，不把推测作为改动理由。

## 默认模型尾延迟

**GPU 空闲状态影响已确认；全部端到端尖峰尚未逐个归因。**

此前同一 full-core TensorRT session 的间隔对照仍有效：连续调用 P99 **8.885 ms**，18 ms 请求间隔时 P99 **27.967–34.043 ms**，观测到 GPU1 SM 时钟 **210–270 MHz**；去掉 event 计时仍有 **29.625 ms** 的 P99。CUDA Graph 没有消除该差异。独立 keep-warm 对照通过，但提高空闲负载且可能等待已提交的保温推理，未启用为默认修复。

本轮阶段诊断补充了同请求证据：

| 传输及样本 | 总延迟 ms | 模型延迟 ms | session 推理 ms | CUDA event ms |
| --- | --- | --- | --- | --- |
| shared，922 | 137.7672 | 114.233 | 112.174 | 101.485 |
| shared，923 | 118.9038 | 95.977 | 94.587 | 84.482 |
| ZeroMQ，372 | 181.2136 | 157.368 | 155.377 | 144.601 |

计时实现位于 `backend/service/application/runtime/predictors/yolo26/segmentation/tensorrt.py`，事件在同一 CUDA stream 的推理提交前后记录，随后等待 stream 完成。这些样本的主要延迟已经位于 GPU 执行时间区间，不能全部解释成 HTTP、SDK 等待或 Workflow 准入排队。

shared 的准备与回收握手也会增加调用间隔。阶段均值可见 SDK allocation 约 2.856 ms、ACK 约 1.116 ms；它们是现有所有权协议的一部分，不能直接删掉。现有证据支持“同步调用间隔与 GPU 浮动频率影响尾延迟”，但不能断言上述每个百毫秒尖峰均由降频造成。

GPU1 未安排其他计算任务，但仍运行于 Windows WDDM 桌面图形环境。NVIDIA 文档明确指出浮动时钟及 WDDM 会增加测量波动；这不是本机每次尖峰的驱动级因果证据，不能直接认定驱动有 bug，也不能据此宣称 RTX 4070 可以切换 TCC。[TensorRT 性能测量说明](https://docs.nvidia.com/deeplearning/tensorrt/latest/performance/benchmarking.html)

默认模型 P99 项继续保留失败。没有修改网络、损失、解码、精度或数值容差，也没有重新认证已投产模型准确率。

## 诊断有效性

所有本轮证据位于 `data/acceptance/runtime-root-cause-20261015/`，原正式失败记录仍保留在 `runtime-lifecycle-20261015/outer-frozen-*`。

| 运行 | 用途 | 限制 |
| --- | --- | --- |
| diagnostic | 原有阶段 timings、模型同请求耗时归因 | 开启 diagnostics，不能替代默认性能认证；模型原门禁仍失败 |
| gc-diagnostic | 只观察自动 GC | 回收后记录有额外成本；用于识别暂停，不冒充修复 |
| span-diagnostic | 指定调用耗时观测 | 启动失败；一条并发诊断日志损坏，明确排除，保留原文 |
| span-verified | 修正诊断写入串行化后重跑 | 观测显著抬高基线与候选耗时，整轮性能数值排除，不以相对门禁通过作结论 |

`diagnostic-summary.json` 明确列出损坏记录。后一个慢调用观察器保持返回、异常和业务同步语义，但日志开销显著，不足以反推历史低扰动窗口。没有将它写入生产代码。

三个完成运行的正式控制流程均执行停止与资源释放；失败启动也由正式入口清理。独立 Windows/WSL 退出检查确认无本轮服务或测试进程、无测试端口监听，不使用快照补杀。源码和发行候选摘要检查仍通过；诊断文件另行归档，不宣称它们属于清洁冻结候选的性能认证。

完成退出检查后清理 `.tmp` 的 17 个临时条目，剩余为空，无错误；见 `temporary-cleanup.json`。清理后重新验证 46,938 个冻结文件，无新增、缺失或字节变化；清单 SHA256 为 `75d9bde729a2ef75f23661ff3514225894a0ff571fb2be73081a00119642c8a7`，见 `post-cleanup-candidate-check.json`。诊断脚本和配置摘要另存于 `diagnostic-file-digests.json`。Git 差异空白检查通过，未提交 Git。

## 验收边界

此前 Windows 751 passed/13 skipped、WSL 335 passed/16 skipped 是明确范围内的回归结果，不覆盖新确认的 reader/publisher 交叉调度。两段 600 秒资源验收通过，不能替代长期稳定性认证；本轮没有重新执行完整组合回归，因为生产源码没有改动。

当前不能声明启动管理完全无误、默认尾延迟达标或达到完整工业现场验收。后续应围绕这份清单建立失败复现、修复、反向边界测试和冻结候选验证，不继续扩展为另一套进程框架，也不将未知项写成已解决。

对应的修改边界、实施顺序和关闭条件见 [运行时根因修复与验收计划](runtime-root-cause-repair-plan.md)。该计划当前为设计状态，不代表本报告中的问题已修复。
