# 0.1.8 开发环境链路验证（2026-10-05）

## 结论与范围

在本机开发 HTTP 服务 5600、Vue 开发服务 5601 上完成真实治具与塑盒样本、已部署模型、Runtime、ZeroMQ Trigger、Preview 和 .NET SDK 的短时验证。本轮覆盖的调用和资源回收正常，未发现需要修改业务数据面的新故障。修正了整体架构及 Preview 执行文档中仍描述旧磁盘暂存、旧同步 Preview 接口的内容。

此结论不是全模型准确率、百万记录规模、受控 P99 性能对照或长期无人值守验收。发行 profile 尚待选择，本轮没有组装或启动新的完整发行包，没有覆盖已有发行目录。

## 运行资源与版本

- 验证前后 `/api/v1/system/status` 均为 `ready=true`，部署 4/4、Runtime 8/8、Trigger 8/8，无 blocker。
- 治具应用 `workflow-app-20260910030059`：活动发布版本 v3，generation 2，119 节点。
- 塑盒满盘应用 `workflow-app-20260910030110`：活动发布版本 v3，generation 2，95 节点。
- 显示应用 `workflow-app-20260910030132`：活动发布版本 v13，generation 9，132 节点。
- 上述三份草稿模板均与当前活动发布模板一致；历史审计记录中的旧版本差异不能作为本次运行结论。generation 不是应用发布版本号。
- 测试前后同一个 LocalBuffer Broker 均为 healthy；2 GiB 全部空闲，active lease、borrow、reserved writing、quarantined 均为 0。

## 真实样本与结果

样本取自 `data/files/developer/图片/3570/`，每张 BMP 为 59,885,622 字节：

| 样本 | SHA-256 | 实际结果 |
| --- | --- | --- |
| `治具托盘/空盘/Image_20260721103258062.bmp` | `1291e7bbbb4a363f7e83f989dd6d22ab3c4cc2128acca273502ac41896af87c6` | 总数 24，OK 24，NG 0，state=ok |
| `吸塑盒/条码面缺料盘/Image_20260801175117494.bmp` | `d4322643d01f0a8c037f864f20a187a97ad7faa2ac58057ba6e400d23a3dc546` | 总数 80，OK 72，NG 8，state=ng |

通过工作流已有 `request_json.value.savepath` 输入，将所有检测测试的图片、结果 JSON 和 JSONL 写到隔离目录。生产路径中的三份 JSONL 在测试前后 SHA-256 完全一致，未追加测试产量。

六组隔离执行输出共 9 条记录；每条记录引用的原图、结果图和结果 JSON 均存在。File Summary 对实际写出文件汇总后与逐行计算一致，重复调用不重复累计。该小样本首次汇总 7.12–9.56 ms，无新增记录时 5.89–6.92 ms；不能由此推导百万记录全量重建时间。

治具按常量 24、塑盒按常量 80 记录生产总数；OK/NG 由配置规则计数。塑盒 Append JSONL 的保存路径来自连线输入，参数中的未使用默认路径不决定实际写入位置。

## 实际耗时及并发

| 链路 | 本轮耗时 | 验证 |
| --- | --- | --- |
| .NET → HTTP Runtime，治具，两次 | 2330.30 / 1953.15 ms | 两次均 24/24/0 |
| .NET → ZeroMQ Trigger，塑盒，两次 | 2203.32 / 1264.28 ms | 两次均 80/72/8 |
| 与 Preview 同时执行的 ZeroMQ，塑盒，两次 | 1994.63 / 1738.00 ms | 两次均 80/72/8 |
| 治具 Preview 完整接收及解码 | 6.515 s | 图执行 2.612 s，prepare 0.405 s，6 个资源确认后释放 |
| 塑盒 Preview 完整接收及解码 | 7.219 s | 图执行 5.300 s，prepare 0.666 s，18 个资源确认后释放 |
| 治具 Preview，附加 5 s 延迟，并发调用 | 10.984 s | 5.953 s 已收到首个显示；资源释放、重连和关闭正常 |

Preview 耗时来自协议测试客户端，包含上传及完整显示接收，不是浏览器点击到绘制耗时。Runtime 与 Preview 交付范围不同，少量样本不构成性能回归对照。现有数据不能声称整图执行或完整预览在 1 秒以内。

并发阶段另经 .NET 同步状态方法查询 500 次，全部 ready；中位 3.41 ms、P99 14.03 ms、最大 684.86 ms。最大值不能省略，也不能把该统计当作纯服务端耗时。

组合实测阶段约 29.58 秒，使用 180 秒总超时；没有运行 30 分钟压力测试。当前真实触发配置覆盖 ZeroMQ 与目录监听，没有新增纯共享内存 mailbox Trigger，不能宣称已完成该协议的真实现场回归。ZeroMQ 图片调用使用现有 LocalBuffer 数据面。

## 浏览器验证

在既有显示 Runtime 的应用模式执行一次，治具显示 48/48/0、塑盒满盘 320/320/0、塑盒空盘 80/80/0，均与正式 JSONL 一致；双击治具大图仍显示同一份统计。页面控制台未采集到 error/warn。

执行前核对九个保留期清理目标目录：仅原图、结果图及结果 JSON，保留一个自然月；本轮没有过期候选。未通过删除现场数据来测试清理逻辑，异常与保留期边界使用隔离测试目录验证。

## 自动验证

- pytest：服务状态、Preview 会话及生命周期、JSONL、File Summary、保留期清理、原子文件替换、结果显示，共 121 passed、1 skipped。跳过项受 Windows 目录符号链接创建权限限制。
- Vue 类型检查及生产构建通过；Preview 和应用模式 Vitest 共 11 文件、65 项通过。
- .NET SDK net472 x64 构建及合同测试通过；真实 Runtime/Trigger/状态调用通过。
- 启动器构建 0 warning、0 error；单元测试 73 passed、4 skipped。跳过的完整发行冷启动及进程集成测试不计入通过范围。

关键复现入口：`tests/integration/workflow_preview_session_live.py`、`sdks/dotnet/tests/Amvar.Vision.ContractTests/`，使用隔离 `savepath`；不要把测试默认路径指向现场生产记录。

## 后续验收

CPU profile 的后续发行验证及本轮新发现问题的修复结果已记录于 [CPU 发行验收](release-acceptance-20261005.md)。以下为本次开发验收时确定的步骤，NVIDIA 和长稳边界仍须单独验证。

1. 确定 CPU 或 NVIDIA profile，在独立发行目录通过 `assemble-release` 生成，不修改旧发行源码目录。
2. 使用该发行包自己的 Python 执行 `validate-layout`，核对驱动、TensorRT/cuDNN 等目标依赖；开发 conda 成功不能替代发行验证。
3. 在隔离端口与数据目录完成发行启动、自动部署/Runtime/Trigger 就绪、SDK 调用、停止和重启验收。
4. 若要求完整预览低于现有 6–7 秒，应另设同输入、同输出范围的暖运行对照，逐段定位上传、执行和展示耗时，不能通过取消资源确认或修改模型输入提高表面速度。
