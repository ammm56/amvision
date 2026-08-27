# Inference LocalMessage Mailbox v1

## 目标与边界

Inference Mailbox Channel 是 backend-service 与独立 inference daemon 之间的同机低延迟结构化数据面。阶段 3 已把原独立 mmap 实现原子迁移到 [ADR-0009](../../decisions/ADR-0009-local-message-channel.md) 定义的通用 `MailboxChannel.v1` engine；不存在旧布局双读或自动回退。

该 Channel 承载：

- detection、classification、segmentation、pose、OBB 同步推理请求和结构化结果；
- `ping`、`status`、`health` 只读请求；
- process config、阈值、`BufferRef`、`FrameRef` 和结果图片引用。

该 Channel 不承载图片 bytes、Base64、持久任务和变更控制。输入或结果图片使用 [LocalBufferBroker](local-buffer-broker.md)；`start`、`stop`、`warmup`、`reset` 继续使用持久化控制队列。

Inference 拥有独立文件、daemon owner、epoch、descriptor/page 容量和故障边界，不与 Workflow Trigger 或 Training EventRing 共用 mailbox、page pool 或 allocator lock。正式路径为：

```text
data/buffers/local-message/inference/mailbox.mmap
```

## 应用契约与分层

应用层只依赖 `InferenceMessageClient` 和不可变 `bytes` wire envelope：

```text
inference-daemon.request.v1
inference-daemon.response.v1
```

业务 payload 和现有 `{ok, result}` / `{ok, error}` 结果形状保持不变。应用层不读取 mmap offset、descriptor、page 或 guard；文件布局、CRC、压缩、deadline、ACK、owner fence 和资源回收只存在于 `infrastructure/ipc/local_message/`。

请求一旦发布后不自动重试。owner 关闭或 epoch 变化时，当前调用返回可重试的取消错误；只有调用方发起的下一次独立请求才重新打开新 epoch，避免模型被静默执行两次。

## 冻结 profile

普通部署配置只保留 `inference_daemon.mmap_mailbox.enabled`。传输几何由代码中的 `inference-mailbox.v1` profile 固定并写入 header：

| 项目 | 固定值 |
| --- | ---: |
| descriptor 数 | 128 |
| 请求 inline 容量 | 64 KiB |
| 响应 inline 容量 | 256 KiB |
| overflow page 数 | 512 |
| 单 page 正文 | 256 KiB |
| 单响应 page 上限 | 129 |
| 单请求上限 | 64 KiB |
| 单响应业务正文上限 | 32 MiB |
| 单响应原始 wire 上限 | 32 MiB + 64 KiB envelope reserve |
| 压缩尝试阈值 | 256 KiB |
| poll 间隔 | 1 ms |

`inference_daemon.max_concurrent_inference_requests` 默认 16，只控制业务 handler admission，不属于 transport profile。descriptor 容量、模型实例并发和 deployment runtime 限流仍是相互独立的边界。

文件逻辑大小约 168 MiB。mmap 文件不等于同等物理内存常驻量，但目标磁盘必须提供对应逻辑容量。

## 状态、发布和容量

通用 Mailbox 状态机为：

```text
FREE -> WRITING_REQUEST -> REQUEST -> PROCESSING -> RESPONSE -> FREE
                                      |              ^
                                      +-- cancel ----+
```

请求或响应都先写 body 和 metadata，最后发布 state。身份由 `owner_epoch + descriptor_index + generation + owner_token + deadline_ns` 共同确定；任一字段不匹配都不能读取、ACK 或回收另一个请求。

响应达到压缩阈值时尝试 zlib；只有至少节省 12.5% 才采用压缩。压缩后不超过 inline 容量则保留 inline，否则一次申请完整 page-chain。page 不要求物理连续，每页和完整原始正文均校验 CRC。

page pool 满载或单响应 page 数超限时发布稳定 capacity error。handler 不重跑、不等待、不改走控制队列；inline transport error 仍可发布。响应超过 32 MiB 时，Inference adapter 返回现有 `mmap_response_capacity_exhausted` 业务错误 envelope。

## deadline、停止和恢复

- client deadline 到期后发布取消，迟到 handler 结果不能覆盖终态；
- daemon 停止时先发布 closed fence 并在 descriptor guard 下回收旧 epoch，再等待已进入 handler 的任务退出；client 不等待整个 handler；
- daemon 重启生成新 owner epoch，旧 client 的当前请求失败且不会自动重放；
- ACK、取消、超时、client 退出和 owner 重启后，descriptor 与 page 都必须恢复到冻结容量；
- page CRC、chain、generation、owner 或 epoch 损坏时拒绝结果，不按不可信链释放其他请求的 page。

## 图片链路

```text
HTTP / Workflow / Trigger image
  -> LocalBuffer BufferRef / FrameRef
  -> Inference Mailbox 只传引用和结构化参数
  -> deployment worker 读取或写入 LocalBuffer
  -> 调用方继续消费引用
```

同步 HTTP 明确要求 Base64 时，只能在最终 HTTP 响应边界读取 LocalBuffer 并编码。Inference Mailbox 不生成或传输 `input_image_bytes_base64` 或 `preview_image_bytes_base64`。

## 健康指标

`ping.mailbox` 公开当前 owner epoch、descriptor 各状态数量、活动 handler、handler admission、inline/page 容量、page 使用量和高水位。`response_metrics` 记录当前 epoch 的响应数、page-chain 响应数、压缩响应数、容量拒绝数，以及最近 4096 个响应整体和按 task type 分类的原始 wire P50/P95/P99/最大值。

这些指标用于现场容量判断，不暴露 mmap 路径和 payload 内容，也不能把合成载荷统计当成生产模型分布。

## 阶段 3 验证结果

专项门禁覆盖：

- 256 KiB 新 inline 边界、512 KiB 旧边界和 1/8/16/32 MiB 无损响应；
- 16 路 inline/page-chain 混合并发且 handler 各执行一次；
- page pool 满载仍返回 capacity error，inline 响应继续可用；
- deadline、停止、owner 重启、不自动重试、CRC、generation、ACK 和资源恢复；
- detection/segmentation 真实业务 DTO 经 dispatcher 往返，其他模型链由全量 runtime 测试继续覆盖；
- 图片只使用 LocalBuffer 引用，不进入结构化 Channel。

同机 5 轮、每轮预热 10 次后采样 30 次的小响应基准如下：

| 指标 | 阶段 0 | 阶段 3 | 允许上限 | 结果 |
| --- | ---: | ---: | ---: | --- |
| P95 | 17.552205 ms | 4.344305 ms | 19.307426 ms | 通过 |
| P99 | 17.956461 ms | 4.830960 ms | 19.752107 ms | 通过 |

原始报告位于 `.tmp/local-message-channel-stage3/inference-benchmark.json`，SHA-256 为 `1161d657183fb128c7f605847406bbfa4df4a88ade142444660237e3bf44974e`。该结果只约束当前开发机和固定基准拓扑，不写成跨机器性能保证。

既有真实 YOLO11n segmentation 样本得到 9 个 instance、1776 个 polygon 数值，传输前后逐字段一致。该结果证明结构化传输不改变该样本的值，不替代目标数据集的模型精度验证。
