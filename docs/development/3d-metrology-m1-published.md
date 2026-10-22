# 3D Metrology M1 真实发布运行验收

日期：2026-10-22。承接[传输与界面](3d-metrology-m1-transports.md)，约束见[实施基线](3d-metrology.md)。

## 结论与范围

已在显式测试配置下完成真实 AppVersion 发布、WorkflowAppRuntime 启动与准入、独立 worker、LocalBuffer、Trigger 和完整样本调用的组合验收。Windows 使用正式 .NET net472 SDK 的 byte[] 与 Span writer；WSL Ubuntu 使用独立 Python 协议客户端，运行数据全部位于 Ubuntu 原生文件系统。

**生产节点仍未启用，M1 生产验收尚未完成。** 本轮不填写生产 timeout、容量或并发，不组装生产三维 profile，不新增执行器、版本系统或等待队列。Ubuntu 服务侧通过不等于 Ubuntu .NET SDK 已交付。

## 真实调用链

1. 将现有隐藏节点包源码复制到隔离测试目录，只机械调整 Python 导入前缀；由正式 builder 生成 Catalog，并写入显式测试 manifest。
2. `create_app` 正常启动真实数据库、对象存储、Broker 和 worker manager。通过授权 REST 保存草稿，取得实际草稿指纹，发布不可变版本。
3. 正式 API 创建 Runtime 并选择该版本，等待独立 worker 启动；正式 API 创建并启用 local-shared-memory TriggerSource，读取实际 route generation。
4. .NET 或独立 Python 客户端完成 PREPARE、写入 guard、REQUEST、真实 Runtime 准入与 owner 交接；正式 filter-valid、cloud-preview 节点执行并返回有界结果。
5. 用正式 Run 查询核对 AppVersion 和 worker 身份，确认私有点云 handoff 没有进入公开结果；ACK 后检查 Broker 和 Trigger 的所有权及容量。

没有替换 `WorkflowRuntimeService`、worker manager、NodePackLoader 或节点 handler。测试仅复用既有图文档构造和显式预算数据，不使用旧的 FakeRuntime/测试 Catalog 替代准入。控制面通过 FastAPI TestClient 调用正式路由及 lifespan，数据面、Broker 和 worker 是真实跨进程执行；不宣称本轮另外验收了 TCP HTTP 部署。

源目录 `_metrology3d_nodes` 仍隐藏，没有新增生产 manifest。临时 manifest 的启用只影响本轮隔离节点目录，结束后删除。

## 样本与测试配置

- 完整原始 ASCII PLY：479,677,235 字节、14,745,099 点。
- 文件 SHA256：`ff2b9e0ef2d6c45af02c4bf8d474cd82f77f86ad92bd371a4c0f71b1b90d116b`。
- 受控 trimesh 完整读取后按 float32 XYZ 生成 176,941,188 字节数组，不自行解析、不只取前缀。
- 数组 SHA256：`956927f058ba4a0170b1c1b93b1411b613fbe21fcbfc278ad0a7fc3cf621a1c6`。
- 第一个发布版本输出 1,000 个显示点，摘要为 `a49008f49e95a770005b57650f6c32cf64b0a3bd6d6a5f7efc1844f38d136005`；第二个版本明确改为 500 个显示点，两平台都验证实际选版生效。
- 单位保持未知，不解释成毫米，不把显示采样用于正式测量。

以下数值仅属于可复现的验收配置，不是生产推荐值：

| 配置 | 测试值 |
| --- | --- |
| 节点 timeout / max / kill grace | 180 / 180 / 2 秒 |
| Runtime 请求 / Trigger reply | 180 / 120 秒 |
| SDK 正常调用 / writer 故障调用 | 120,000 / 5,000 ms |
| Trigger response ACK timeout | 2 秒 |
| Broker arena / 单次分配上限 | 512 / 256 MiB |
| Broker reader guard slots / 回收宽限 | 8 / 1 秒 |
| I/O 解码 / live array 预算 | 400,000,000 / 800,000,000 字节 |
| 块行数 / 块字节数 | 65,536 / 4,194,304 |
| 测试运行记录 | 显式 `workflow_run_record_mode=full`，用于核对 Run 追溯 |

其余预算复用 `test_transport_full_sample.full_policy`。高速同步 Trigger 默认不保存 Run，本轮没有改变该生产默认策略。Broker 的 executor 最大 worker 数也不是新增业务并发数或队列。

## 发现并修复的问题

### WRITING 超时遗漏业务资源释放通知

真实 .NET 客户端持有 writer 后被强制结束，出现：底层 mailbox 槽位及 Broker 容量已回收，但 Trigger 的 `pending_request_count=1`、`active_source_permit_count=1`。继续调用可能被错误地判为繁忙。这是共享 Trigger 生命周期问题，不限于点云。

根因在两种不同超时状态被当成同一种状态处理：

- `WRITING_REQUEST` 超时：通用 mailbox 直接释放槽位，不产生后续可 ACK 响应。
- `REQUEST/PROCESSING` 超时：通用 mailbox 发布错误响应，槽位仍等待 ACK 或 ACK timeout。
- 原终态通知只有超时原因，Trigger 上层把写入超时也当成仍需等待响应终态，因此漏清 pending、source permit 和 adapter context。

修复在现有边界内完成：内部 `MailboxTerminalEvent` 增加明确的 `descriptor_released`，由真正执行槽位转换的位置填写；Trigger adapter 据此通知既有清理路径并删除对应 identity/context。仍保留 processing 错误响应的 ACK 语义和取消语义。

没有修改 mmap 文件布局、公开 JSON/SDK 协议、owner fence、reader/writer guard、回收宽限、停止或恢复算法。没有通过额外扫描、重试队列、放宽超时或复制一套清理器修复。

### 验收中修正的测试配置与断言

- Python 外部 writer 必须采用服务端同一显式 guard 布局；不能用默认 reader slots 打开本轮测试布局。
- 追溯检查显式打开 full Run 记录，否则高速同步默认策略下查询不到 Run 不是执行失败。
- Runtime 停止并不自动禁用 TriggerSource；运行中切版及 source 仍启用时切版都必须拒绝。测试按既有规则先禁用 source 再选版。
- 短任务可能落在周期心跳之间。故障触发改为只读 worker 已有、经身份校验的 `node-started` 记录，不注入慢 handler 或改变生产心跳。
- held-writer 超时后容量计入 revoking/quarantined，而非 active allocation。断言检查它不可用于再次分配，进程退出后才全部归零；不把该受保护状态误报为泄漏。

## 验证结果

[Windows 完整样本证据](evidence/metrology3d-m1-published/windows.json)、[Ubuntu 完整样本证据](evidence/metrology3d-m1-published/linux.json)包含实际 Run、版本、worker、故障调用和最终资源状态。

| 场景 | 已验证行为 |
| --- | --- |
| 完整数组正常调用 | Windows byte[] 与 writer，Ubuntu Python 协议；结果点数、摘要及版本一致 |
| 运行中切版 | 409 拒绝，不替换在用版本 |
| 停止但 source 仍启用 | 409 拒绝切版；停止状态不允许执行新的调用 |
| 停止、禁用、切版、启动 | revision generation 增加，worker 身份变化，结果变为新版本的 500 点 |
| 旧 route generation | 明确失败，容量归还，新 generation 继续可用 |
| writer 客户端异常退出 | pending、source permit、lease 及占用容量全部回收，后续调用成功 |
| writer 存活但请求超时 | 协议与准入释放；guard 仍保护 revoking/quarantined 内存；客户端退出后容量全部归还 |
| 执行中客户端异常退出 | 从实际 node-started 后强制结束客户端，服务完成收尾，后续调用成功 |
| 执行中停止 Runtime | 正式 stop 返回 stopped，原 worker 实际退出，资源归还，重启后完整样本成功 |

执行中断连不要求把已经完成的计算强行改写为失败；正式停止也允许当前短任务在正常停止期限内完成。验收重点是无残留准入、无越权复用、原进程退出及恢复可用，不能把“客户端被结束”等同于“算法已被强制杀死”。

最终组合覆盖通用 mailbox、既有图片 Trigger、点云协议、输入能力、ResourceScope 收尾、worker 资源保留和生产隐藏边界。Windows 125 项通过，1 项 held-deadline 的计数口径断言修正后单独补验通过，去重 **126 项通过**；Ubuntu 119 项通过、6 项 Windows SDK 用例跳过，同一断言修正后单独补验通过，去重 **120 项通过、6 项跳过**。完整样本用例在组合执行中已经通过，不因单项断言修正再次解析大文件。SDK 构建零警告、零错误，现有契约程序通过；修改的 Python 文件 Ruff 与 `git diff --check` 通过。本轮没有修改前端组件，不重复界面/P99/长稳验收。

## 审计与剩余条件

- 修复只作用于终态事件与资源清理，不改变节点计算、float32/float64 边界、原始行号、抽样方法或模型数值逻辑。
- 成功请求的数据面没有新增复制、hash、线程、轮询器或网络调用；不能把这一静态结论写成已完成性能门禁。
- 资源释放仍受完整 identity 和既有 guard 约束；held-writer 回归专门验证不能以“业务清理完成”为由提前复用在用内存。
- 本轮覆盖发布/运行生命周期，不替代 1 GB 容量、生产节拍、工业计量精度或长期运行验收。
- 生产 timeout/kill grace、运行/磁盘/显示预算、最低配置与目标并发仍待确认；正式节点注册及 Windows/Ubuntu 发行组装仍不能执行。
- .NET 仍限当前 Windows net472 范围；本轮 Python 客户端是内部测试程序，不是交付的独立 Python SDK。

## 复现与清理

入口为 `tests/integration/metrology3d/test_published_runtime.py`，完整样本必须显式传入 `--cloud-sample`；报告目录通过 `--cloud-report-dir` 指定。Windows 先在独立环境安装已校验的受控 wheel，并构建既有 .NET ContractTests；Ubuntu 同样采用独立环境，`--basetemp` 必须位于 Ubuntu 原生文件系统。

测试的 context manager 在失败路径也停止 Runtime 并退出应用 lifespan，外部客户端在 finally 中回收。本轮没有新建 TCP API/Vite 服务。收尾进程核对未发现本轮 Windows/Ubuntu worker、Broker、SDK 客户端或 pytest 残留。仓库 `.tmp/` 的 10 个目录已清空，Ubuntu 的 `/home/am/.cache/amvision-m1-published` 已删除并复查不存在，包括临时环境、完整数组、数据库和共享内存文件；原始样本、正式源码、构建产物与版本化证据保留。

原有 5600 后端、5601 Vite、worker supervisor 和 inference daemon 不是本轮启动，未停止或删除其运行数据；不能将本轮清理表述为整机所有开发服务已关闭。
