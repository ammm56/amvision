# Runtime、Trigger 与 Preview 并发核对（2026-09-10）

本轮结论：在已验证范围内，正式协议、业务结果、并发容量保护和资源回收符合现有契约，未发现资源泄漏、生命周期或未清理错误。两个推理实例均占用时明确返回满载、同 Runtime 忙时明确拒绝，均为正常行为，不属于实现缺陷或本轮验收阻塞项。保持当前高性能链路，不增加队列、等待、自动重试或优先级调度。

## 环境与范围

- 源码基点：`24c6dac5`。本轮未修改 SDK 生产代码、Runtime/Trigger 数据面、模型算法或现场部署配置。
- 应用：`workflow-app-20260831130620`；正式 Runtime：`workflow-runtime-1691960999904278a9bad29cee6487aa`。
- 发布 revision：`workflow-runtime-revision-1282e33c39e344a59dd60c354df8e804`。Preview 使用当前编辑快照，未保存或发布应用；两条链分别重复固定自己的快照，不能冒充完全相同图的性能对照。
- 模型：现有 YOLO11 分类部署，OpenVINO CPU FP32，2 个推理实例，每实例配置 8 个推理线程，`overflow_policy=reject`。
- 真实输入：3570 空盘 BMP，5472×3648，59,885,622 字节。BGR24 数据来自同图直接解码，不缩小图片、不替换模型、不关闭流程保存节点。
- 现有环境列出 4 个 ZeroMQ Trigger 和 2 个目录监听 Trigger。ZeroMQ 图片进入 LocalBuffer；没有启用纯 `local-shared-memory` TriggerSource。本轮实测主要针对上述 3570 Runtime，其余 Runtime 只读核对，目录监听未注入业务事件。

完整数据见 [验证记录](validation/2026-09-10-runtime-preview-coexistence.json)。

## 实测结果

耗时从 .NET SDK 调用开始到同步业务响应返回，包含通信和整图处理；不包含图片首次从磁盘读入测试进程，不等于模型单次推理耗时。HTTP 使用 BMP multipart，ZeroMQ 分别使用 BMP bytes 和原尺寸 BGR24。预热样本单独保留并排除统计。

| 场景 | 计时样本 | 中位数 | 最大值 |
| --- | ---: | ---: | ---: |
| HTTP Runtime 单独调用 | 8 | 3.85 s | 4.38 s |
| ZeroMQ BMP 单独调用 | 12 | 2.10 s | 2.70 s |
| ZeroMQ BMP 与 Preview 同时运行 | 12 | 2.62 s | 3.56 s |
| 并发结束后 ZeroMQ BMP | 6 | 1.86 s | 2.27 s |
| ZeroMQ BGR24 单独调用 | 5 | 1.30 s | 1.40 s |
| HTTP Runtime 与 Preview，后半轮整机高负载 | 5 | 9.32 s | 19.57 s |
| ZeroMQ BGR24 与 Preview，后半轮整机高负载 | 6 | 5.47 s | 7.59 s |

所有 54 个计时成功调用及 5 个预热调用均校验业务输出，结果保持 24 个空槽、判定通过；Trigger 的事件、来源和 Run 身份一致，未发现重复 Run。7 次 Preview 中 6 次完成，各完成 40 个显示/值资源的接收和释放验证；1 次在 Classification Batch 因模型实例满载明确失败，符合容量拒绝策略。

前半轮同时向同一个 Runtime 发 HTTP 与 Trigger 请求时，HTTP 被 409 拒绝，没有计入成功样本。原始拒绝记录保留，区分请求是否完成与并发契约是否正确：明确拒绝超出容量的请求是正确行为，不要求所有并发请求都成功执行。

后半轮观察到整机 CPU 100%、内存占用 86.1%，同时有 Explorer、多个 dotnet、Visual Studio 服务和 Defender 活跃。因此后半轮数据保留为压力现场证据，不能将全部延迟归因于 Preview，也不能用于证明某次提交的性能回归比例。样本太少，不发布有统计意义的 P99；既有共享内存 P99 门禁失败结论保持不变。

## 已确认的执行边界

### 1. 同 Runtime 的 HTTP/Trigger 并发受已有执行权约束

`worker/manager.py` 的 `acquire_execution_token` 对 `acquisition_mode=reject` 使用非阻塞执行锁，已有请求占用时返回 `WorkflowRuntimeBusyError`。Git blame 指向 2026-08-25 的 `d9766ea1f`，不是本轮预览修改引入。

Preview 独立执行自己的内存快照，不占用该 Runtime 的执行锁。正式调用方仍需按照单 Runtime 执行权契约提交，不能假设 HTTP 和 Trigger 会自动排队。SDK 不应自动重试所有失败，以免对包含保存或外部副作用的流程重复执行。

### 2. Preview 与正式调用共同遵守模型实例容量

真实容量拒绝：`171af43cd64a42878f03f2c5c9fca415`，节点 `core_model_classification_batch_1`，错误“当前 deployment 推理实例已满载”，`instance_count=2`。

部署池 `_acquire_instance` 在两个实例均占用时明确拒绝；网关保留 `deployment_inference_busy` / 409 语义。该流程自身存在两条并行 Classification Batch，Preview 与正式执行同时调用相同部署时，需求可能超过两个实例。Preview Worker 当前把该容量拒绝直接转为运行失败。

两个实例最多同时处理两个推理调用，Preview 与正式调用均遵守该边界。若 Preview 先取得实例，后来的正式推理同样可能收到满载拒绝，这也符合当前契约。无需为 Preview 增加等待或特殊优先级，更不应改变正式数据面的容量保护。此次实际观察到 Preview 被拒绝，没有观察到正式推理满载。

### 3. 计算资源共享不等于实时性能隔离

Preview 的上传/显示 SharedMemory 和图片生命周期独立；模型调用通过既有部署网关与正式链路共用模型实例、CPU 和部分 LocalBuffer 数据通道。WebSocket 不启用压缩只能减少显示交付开销，无法消除 OpenCV、JPEG 编码和模型计算的竞争。

因此“没有改动正式数据面”不能推导出“Preview 对正式耗时没有影响”。纯粹增加实例数也可能使 CPU 线程竞争更严重。

### 4. LocalBuffer 未观察到生命周期泄漏

前后均为 2 GiB 空闲，已分配容量、活动租约、借用、隔离容量和待路由响应归零；分配失败计数均为 0，活动客户端通道数保持 9。75 次采样未出现健康请求错误，采样到的峰值分配约 88 MiB。采样峰值不是连续观测的绝对最大值。

失败 Preview 最后也删除了自身会话，最终 Broker 再次回到空闲。上述证据不能代替长期内存稳定性验收。

## .NET SDK 核对

- SDK、契约测试程序和 Console 均通过 x64 Release 构建，警告视为错误；SDK 契约测试通过。
- 真实调用使用本轮重新构建的 net472 SDK，验证 HTTP multipart、ZeroMQ BMP、BGR24 和附带 JSON；生产 SDK 无需为 Preview WebSocket 更新协议。
- SDK 测试进程峰值工作集约 97–492 MiB。此处不是 Visual Studio 下 Console 的完整调试内存测量，不能据此宣布历史 3 GiB 现象已解决或认定泄漏。
- Console 样例仍启用了纯共享内存调用，但当前导出的 3570 Config 只有 ZeroMQ source，没有样例常量所指的共享内存 source。直接运行整份样例会有配置不匹配风险，尤其 `CreateTriggerInputs` 在调用包装器外解析配置。应选择已配置的测试调用，或实际创建并导出对应 source；不要把未配置的入口算作 SDK 协议错误。
- 本轮没有运行会执行 start、warmup、enable 等操作的整份 Console 样例，也没有改写本地 Config。纯共享内存真实调用未验收。

## 验证工具与结论修正

新增测试入口 `Amvar.Vision.ContractTests.exe --workflow-coexistence <config.json> <report.json>`，只调用已有资源，复用 client，逐次记录结果、身份和耗时。配置使用 `mode=runtime|zeromq`、`image`、`iterations`、`warmup`、`runtime_id`、`source_id`、`endpoint`、`payload`；原始图片另设 `input_mode=bgr24`、`width`、`height`。`expected` 是结果 JSONPath 到期望值的映射。HTTP 登录 token 通过子进程环境变量 `AMVISION_AUDIT_TOKEN` 传入，不写入配置或报告。

部署调用网关、Preview 生命周期、模型边界、Trigger 输出回收及执行锁生命周期的 28 项定向 pytest 通过。较大的进程测试集为限制验证时间主动中止，不计为通过。Preview 实测继续使用仓库内 WebSocket 探针，本轮也补齐其重连连接的 `compression=None`；未进行浏览器 UI 验收。

此前将模型满载列为待修复缺口，并建议有界等待和优先级调度，误将“所有请求都应完成”作为验收标准。该判断已撤回，对应实现建议已删除。

当前验收标准为：容量内请求正常执行并返回正确结果；超出容量时明确拒绝；成功、拒绝、异常路径均按各自所有权释放资源，不发生串结果、泄漏或残留占用。本轮已观察到的执行与回收符合该标准，未发现需要据此修改 Runtime、Trigger 或 SDK 生产代码的问题。

原始记录中的 `passed=false` 或运行 `failed` 表示当次请求未完成，不等同于容量契约验证失败。原始状态和耗时保持不变；短样本、整机负载、未覆盖入口和长期运行验证的范围限制也保留，不将本轮结果外推为所有模型和所有环境的全面验收。
