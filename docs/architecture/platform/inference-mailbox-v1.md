# Inference mmap mailbox v1

## 目标与边界

Inference mailbox 是 backend-service 与独立 inference daemon 之间的同机低延迟结构化数据面。当前协议只有 v1，不存在并行维护的旧布局或 v2 兼容层。daemon 启动时按当前配置重新初始化固定大小文件；布局不匹配时 client 直接拒绝连接。

本文描述当前已运行实现。[ADR-0009](../../decisions/ADR-0009-local-message-channel.md) 已接受将底层 header、descriptor、page、CRC、deadline、回收和 health 收敛到公共 `RpcMailboxChannel.v1` engine，但代码迁移尚未发生。迁移后 Inference 仍有独立物理文件、daemon owner、epoch、descriptor/page 容量和故障边界，不与 Workflow Trigger 共用 mailbox 或 allocator。

mailbox 承载：

- detection、classification、segmentation、pose、OBB 同步推理请求和结构化结果；
- `ping`、`status`、`health` 只读请求；
- process config、阈值、`BufferRef`、`FrameRef` 和结果图片引用。

mailbox 不承载图片 bytes、Base64、持久任务和变更控制。输入或结果图片使用 [LocalBufferBroker](local-buffer-broker.md)；需要跨重启保存的异步结果在持久化边界复制到 ObjectStore。`start`、`stop`、`warmup`、`reset` 使用持久化控制队列。

## 固定布局

文件由 64-byte file header、固定 descriptor 区和固定 overflow page pool 组成。启动后不扩文件。

默认配置：

| 项目 | 默认值 |
| --- | ---: |
| descriptor 数 | 128 |
| 单 descriptor 请求 inline 区 | 512 KiB |
| 单 descriptor 响应 inline 区 | 512 KiB |
| overflow page 数 | 256 |
| 单 page 正文 | 512 KiB |
| 单响应 page 上限 | 64 |
| 单响应原始 JSON 上限 | 32 MiB |
| mailbox 执行并发 | 16 |

默认 descriptor inline 区约 128 MiB，overflow pool 约 128 MiB；加上 header 后，文件逻辑大小约 256 MiB。文件容量固定、可计算，与图片分辨率无关。

### File header

File header 记录：

- magic `AMVMBX1` 和 protocol version `1`；
- descriptor count、inline capacity、descriptor stride；
- page count、page capacity、page stride；
- 单响应 page 上限；
- 当前 daemon `server_epoch`。

Client 打开文件时必须同时校验 magic、版本、所有 stride、总文件大小和页数边界。只校验版本号不足以证明布局一致。

### Descriptor header

每个 descriptor 独立代表一个请求，header 记录：

- `state`、编码 flags；
- `request_size`、`request_crc`；
- `response_size`、`response_raw_size`、`response_crc`；
- `first_page_index`、`page_count`；
- `generation`、`owner_token`、`deadline_ns`、`server_epoch`。

Descriptor 后面紧跟固定请求 inline 区和固定响应 inline 区。小响应不申请 overflow page。

状态机固定为：

```text
FREE -> REQUEST -> PROCESSING -> RESPONSE -> ACKED -> FREE
                     |              |
                     +-> CANCELLED <-+
                              |
                              +-> FREE
```

Header 和 body 写完后才单独发布 state。状态发布是最后一步，reader 不把其他 header 字段当作就绪信号。

### Overflow page header

每个 page header 记录：

- `state`；
- `next_page_index`；
- `used_size`、`page_crc`；
- `descriptor_index`、`descriptor_generation`、`owner_token`。

Daemon 是唯一 page allocator 和回收者。分配时先寻找连续区间；连续页不足但总空闲页足够时，使用非连续 page chain。Daemon 内存中的 allocation map 与 page header 必须同时表明 page 空闲后才能重新分配，损坏的 `FREE` header 不会覆盖仍登记在途的响应。Client 从 descriptor 的 `first_page_index` 开始沿 `next_page_index` 读取，不扫描整个 page pool，也不依赖物理连续或 ordinal 重排。

## 请求与响应发布

Client 发布请求：

1. 取得 descriptor guard 和独占 owner 锁文件；
2. 校验 `FREE`、`server_epoch` 和 owner；
3. 写入紧凑 UTF-8 JSON、长度、CRC、generation、deadline；
4. 最后发布 `REQUEST`。

Daemon 发布响应：

1. 请求只通过项目既有的 `pydantic-core` 序列化一次为紧凑 UTF-8 JSON；
2. 原始 JSON 超过单响应上限时改写为 inline 容量错误；
3. 达到压缩阈值时尝试 zlib level 1；只有压缩后不超过原始大小的 87.5% 才采用；
4. 编码结果不超过 512 KiB 时写 descriptor inline response；
5. 大响应一次性申请完整 page chain，写完每页正文、长度和 CRC 后发布 page `READY`；
6. 写 descriptor 的 codec、长度、CRC、first page 和 page count；
7. 最后发布 `RESPONSE`。

推理 handler 只执行一次。页池不足时不重新推理、不等待、不重试、不改走控制队列，返回 `mmap_response_capacity_exhausted`（HTTP 语义 503）。错误 envelope 始终使用 descriptor inline response，不依赖 overflow page。

Client 看到 `RESPONSE` 后校验 descriptor identity、page chain 循环/越界/长度、每页 CRC 和整体 CRC，再透明解压并校验原始长度。成功解码或确认协议错误后发布 `ACKED`，daemon 统一回收。

## 所有权、超时与恢复

一次请求的身份由下列字段共同确定：

```text
server_epoch + descriptor_index + generation + owner_token + deadline_ns
```

任何 generation、owner 或 epoch 不匹配都终止当前读取或状态修改，不能回收另一个请求的资源。

回收规则：

- 正常 ACK：daemon 立即释放 page chain 和 descriptor；
- client timeout：client 发布 `CANCELLED`，daemon 在 handler 退出后回收；
- client 在请求发布前退出：daemon 扫描已过 deadline 的 owner 锁并恢复 `FREE` descriptor；
- client 在读取或 ACK 前退出：daemon 在 response deadline 加 ACK grace 后回收；
- daemon 在 page 写入中退出：新 daemon 发布新 epoch，并在开放请求前清空全部 descriptor、page 和旧 owner 锁；
- page loop、越界、重复 identity 或 CRC 错误：client 拒绝结果；daemon 依据本进程 allocator 记录回收该响应的实际页，避免损坏 header 造成泄漏或误释放。

页分配表只存在于 daemon 内存，由 page pool lock 保护。跨进程同步只发生在 descriptor guard；不会为每个 page 创建锁文件。

## 图片链路

同步输入和结果图片：

```text
HTTP / Workflow / Trigger image
  -> LocalBuffer BufferRef / FrameRef
  -> mmap JSON 只传引用
  -> deployment worker 读取或写入 LocalBuffer
  -> Workflow 后续节点继续使用引用
```

同步 HTTP 明确要求 Base64 时，只能在最终 HTTP 响应边界读取 LocalBuffer 并编码。Inference daemon IPC 不生成或传输 `preview_image_bytes_base64`。

持久异步结果：

```text
LocalBuffer
  -> async 持久化边界复制到 ObjectStore
  -> TaskRecord / gateway message 保存 ImageRef 或 object key
  -> 释放 LocalBuffer
```

## 容量与健康指标

`ping` 的 mailbox 摘要公开当前 epoch、descriptor 各状态数量、活动执行数、执行并发上限、inline 容量、page 总数/空闲数/使用数、高水位和单响应上限。`response_metrics` 记录当前 epoch 的响应总数、分页数、压缩数、容量拒绝数，以及最近 4096 个响应整体和按 task type 分类的原始 JSON P50/P95/P99/最大值。容量规划优先依据真实 segmentation 分布调整 page 数与单响应页上限，不能运行时扩容文件。

仓库当前未保存可作为生产统计样本的真实 segmentation 响应记录，因此不能把合成边界载荷误写为 P50/P95/P99。现场或真实模型 soak 必须记录紧凑 JSON 的 P50、P95、P99 和最大值，再决定是否偏离默认 256 pages / 64 pages-per-response。

## 验证门禁

实现变更至少覆盖：

- 512 KiB 前后以及 1、8、16、32 MiB 无损响应；
- 16 路 inline / page-chain 混合并发；
- 连续优先和碎片化非连续 chain；
- 压缩采用与拒绝边界；
- pool 满载时明确容量错误，inline 请求仍成功；
- request、processing、response、read、ACK 各阶段 timeout/退出；
- daemon 在多页写入过程中退出并由新 epoch 恢复；
- CRC、chain loop、owner、generation 和 epoch 不匹配；
- 四个 client 进程共 2000 请求无 ownership 失效、重复释放和 page 泄漏；
- detection、classification、segmentation、pose、OBB 路由不进入控制队列；
- preview/result image 只通过 LocalBuffer 引用；
- 真实 segmentation 模型结果在传输前后结构和值完全一致；
- Workflow 双并行分支和 Trigger 长时 soak 后 descriptor/page 回到基线。

性能对比必须使用同一机器、同一 Python 环境、同一 JSON 载荷和相同次数，分别记录 1 MiB 与 8 MiB 的中位数/P95。性能结论属于目标硬件 benchmark，不写成跨机器保证；小响应不得因 page-chain 支持产生明显回退。

2026-08-21 在当前 Windows 开发机、当前 conda 环境中，以相同的高重复 segmentation 风格 JSON、5 次预热后采样中位数，对照原持久化文件控制队列完整请求/响应轮询链路，结果为：

| 原始响应大小 | mmap v1 中位数 | 文件控制队列中位数 | 加速比 |
| --- | ---: | ---: | ---: |
| 1 MiB | 15.63 ms | 50.42 ms | 3.23× |
| 8 MiB | 58.63 ms | 201.89 ms | 3.44× |

该记录只证明当前环境和该载荷通过 3× 门禁。真实目标设备仍须用真实 segmentation 响应重新采集 P50/P95/P99 和最大值，不能直接沿用开发机数字。

同日使用本地预训练 YOLO11n segmentation checkpoint 和仓库开发测试图片执行真实 PyTorch 推理，得到 9 个 instance、1776 个 polygon 数值；序列化结果经过 mmap v1 后逐字段比较完全相同。该结果证明传输不改变当前样本的结构和值，不替代目标数据集的模型精度验证。
