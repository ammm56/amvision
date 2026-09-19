# 2026-09-19 最近一周功能回归与开发环境验证

## 范围与结论

审计窗口为 2026-09-12 至 2026-09-19。提交范围 `311214ab..0b393829`，共 16 个提交、120 个文件，主要涉及文件记录与归约、图片和字段显示关联、Windows 文件替换与热重载、Preview 分支资源生命周期、服务状态接口与 .NET SDK。

发现并修复一个影响真实编辑和预览的启动顺序回归；另发现两份检测 Runtime 尚未启用新计数版本。当前开发环境的已测链路可正常完成，但不能据此宣布全部生产要求、所有模型精度或长期无人值守稳定性验收通过。本轮未发布草稿、切换 Runtime 版本、修改模型或正式生产记录。

## 已修复：状态采集器提前缓存不完整节点目录

- 来源：`0b393829` 的 `ServiceStatusCollector.__init__` 在 `create_app` 装配阶段枚举节点目录。
- 当时 `LocalNodePackLoader.refresh()` 尚未执行，`NodeCatalogRegistry` 因此缓存了只有 core nodes 的快照；后续 loader 刷新没有清除这个已合并的目录。
- 现场证据：节点目录中自定义节点数为 0；读取治具应用返回 HTTP 400，提示 `custom_opencv_perspective_transform` 引用了不存在的节点类型。两项 Runtime Preview 条码回归也因 `decode` 节点缺失失败。
- 已运行 Runtime 使用已发布快照与自己的执行器，所以仍可执行，不能从它们成功推断 HTTP 编辑目录正常。
- 修复：构造器只保存依赖；后台首次采集在服务初始化完成后读取节点定义。依赖声明变化时清空对应派生缓存，避免节点包刷新后沿用旧映射。
- 验证：加入构造阶段禁止访问目录、节点依赖声明更新的回归；原两项失败复测通过。开发服务自动重载后自定义节点恢复到 253 个，三份实际应用可正常读取，真实 Preview 成功。

修复不修改模型推理、Runtime/Trigger admission、图片 LocalBuffer 或业务文件写入路径。

## 上线配置缺口：检测 Runtime 仍是旧发布版本

| 应用 | 运行中的 Runtime | 固定版本 | Append JSONL |
| --- | --- | --- | --- |
| 3570 治具空盘检测 | `workflow-runtime-00ac97b7030b4bb5bda4c3d1e7a76fba` | `workflow-app-version-455a941efea34ee7a176ca2437c53235` | 无 |
| 3570 塑盒满盘检测 | `workflow-runtime-a7f6847a6b4d419ea6664a150032436f` | `workflow-app-version-47f5308804f045c2995ffd2dbbf80811` | 无 |

两份当前草稿已经包含 `production_append`，真实 Preview 会追加；当前 Runtime/Trigger 则只执行旧版本。成功的检测调用不会自动把草稿中的生产计数功能带入运行版本。这是发布版本选择问题，不能通过状态接口、重复调用或前端刷新解决。

上线前需发布核对后的检测草稿，切换两个 Runtime 的固定版本，重新核对 Trigger 响应契约；随后以隔离 savepath 分别执行一次，确认每次只追加一条、治具总数增加 24、塑盒总数增加 80、OK/NG 与公开结果一致。正式记录不得混入验证累计。

## 自动化验证

- 后端首次：208 通过、2 失败、1 跳过；失败明确保留并定位为上述启动顺序回归。
- 修复后同一组最终：212 通过、1 跳过，36.62 秒。跳过项是需要独立控制台条件的 Windows console reload 测试；其余 accept 错误、HTTP/WebSocket 和 reload server 测试已运行。
- 前端：72 个测试文件、266 项通过；Vue/TypeScript 类型检查通过。
- .NET Framework 4.7.2 x64 构建和契约程序通过。
- 修改 Python 文件的 Ruff 通过。

后端覆盖：状态陈旧/关闭/初始化失败/满载、节点依赖与 revision、JSONL 清空/删除/提交恢复/损坏拒绝、增量汇总/规则变化/并发检查点冲突、规则重叠与非法数值、显示关联/上下文一致性、跨进程文件读取和替换、外部独占/只读/写入失败、Preview 分支最后消费者及资源释放、Runtime Preview、daemon 生命周期和 watchdog。

前端覆盖：App Mode 显示启用边界、明确连线、普通图和大图共享数据显示、尺寸与颜色校验、参数编辑器、下拉框及多语言。

后端命令（先 `conda activate amvision`）：

```powershell
python -m pytest tests/test_service_status.py tests/test_file_summary.py tests/test_managed_jsonl.py tests/test_rule_counting.py tests/test_file_display_nodes.py tests/test_file_display_workflow.py tests/test_file_display_api.py tests/test_image_presentation.py tests/test_workflow_atomic_files.py tests/test_atomic_file_replace.py tests/test_object_store_snapshots.py tests/test_local_file_queue.py tests/test_http_reload_server.py tests/test_windows_http_accept.py tests/test_preview_service_launcher.py tests/test_workflow_preview_lifetime.py tests/test_workflow_runtime_preview_api.py tests/test_inference_daemon_runtime.py tests/test_inference_daemon_control.py tests/test_workflow_runtime_worker_watchdog.py -q
```

## 真实数据与结果

Windows 开发环境 HTTP 5600、Vue 5601；使用已部署分类模型，没有在测试中另行加载模型。检测输出全部使用隔离 savepath。两张原始 BMP 均为 59,885,622 字节：

- 治具：`data/files/developer/图片/3570/治具托盘/空盘/Image_20260721103258062.bmp`，SHA-256 `1291e7bbbb4a363f7e83f989dd6d22ab3c4cc2128acca273502ac41896af87c6`。
- 塑盒：`data/files/developer/图片/3570/吸塑盒/条码面缺料盘/Image_20260801175117494.bmp`，SHA-256 `d4322643d01f0a8c037f864f20a187a97ad7faa2ac58057ba6e400d23a3dc546`。

| 测试 | 结果 | 端到端耗时 |
| --- | --- | --- |
| 当前治具草稿 Preview | 24 OK / 0 NG，JSONL 一条，图片及结果 JSON 引用存在 | 4.500 秒 |
| 当前塑盒草稿 Preview | 72 OK / 8 NG，JSONL 一条，图片及结果 JSON 引用存在 | 2.906 秒 |
| 显示草稿读取上述文件 | 累计与记录逐项一致，盘数均为 1 | 673.571 ms |
| 两次重复显示 | 计数不变，检查点 mtime 不变 | 507.245 / 540.859 ms |
| 分别删除隔离 commit 后显示 | 元数据恢复，累计不重复 | 517.309 / 518.408 ms |
| .NET HTTP Runtime 治具，3 次 | 全部成功，24 槽 OK | 2225.03 / 2115.87 / 2456.67 ms |
| .NET ZeroMQ 塑盒，3 次 | 全部成功，80 槽、8 项问题 | 2298.03 / 1663.96 / 1593.40 ms |
| HTTP 治具与 ZeroMQ 塑盒同时调用，各 2 次 | 全部成功，结果和调用身份正确 | 治具 2891.80 / 2372.24；塑盒 1925.48 / 1488.07 ms |
| Preview 与 ZeroMQ 同时调用 | Preview 与 3 次 Trigger 均成功；Preview 增加 20 秒 Delay，先显示后结束 | 首显示 3.390 秒，结束 23.344 秒 |

共核对 13 次 .NET 真实调用的业务响应：治具为 24 槽、OK、0 项问题；塑盒为 80 槽、NG、8 项问题。它们不包含新 JSONL 编排，因为运行版本仍旧。

另以无效 BMP 内容调用实际治具 Runtime 两次，均返回正式 App Result 的 `state=failed` 和可定位的 `invalid_request`，没有写出业务文件，服务仍 ready。该接口既有契约使用 HTTP 200 承载执行失败；测试脚本最初按 HTTP 4xx 判断导致断言失败，核对正式契约后改为检查 state/error，未为此修改产品行为。第三方不能仅凭 HTTP 200 判定检测成功。随后再通过 .NET 执行 3 次有效塑盒 Trigger 均成功，合计 16 次成功的 .NET 检测调用。

Preview 脚本校验全部 JPEG/JSON 资源、完整接收确认、资源释放及重连状态；两次检测分别释放 6 和 18 个资源，20 秒延迟验证释放 6 个资源，会话全部关闭。测试后塑盒 Trigger 8 次请求全部成功，timeout/error 为 0，传输 registry active/reserved/quarantined 均为 0。该短时证据不等于长期无泄漏证明。

## 浏览器与磁盘交叉核对

内置浏览器运行实际显示 Runtime：

- 治具正式日志 4 条：总数 96、OK 87、NG 9，页面 90.63%。
- 塑盒正式日志 5 条：总数 400、OK 382、NG 18，页面 95.50%。
- 四个图片栏有结果，双击治具结果图打开 2560×2358 JPEG；大图左上角保留 NG、总数、良品、不良与良品率，纵向半透明布局正常。
- 本轮测试没有追加或删除上述正式日志。显示 Runtime 读取检查点是其正常业务行为。

## 状态接口与性能限制

更新后的 daemon 已启动，最终状态为部署 4/4、Runtime 6/6、Trigger 6/6，HTTP 200、ready=true。之前文档中“待 daemon 重启”的条件已解除。

- .NET 连续 1000 次状态请求全部 ready；中位 1.7407 ms、P99 8.1405 ms、最大 330.6578 ms（含首请求）。
- 第一轮实际 SDK 负载期间，独立 HTTP 客户端采样 175 次，全部 ready；中位 4.1416 ms，最大 1823.2801 ms。
- Preview + Trigger + 20 秒 Delay 期间采样 246 次，全部 ready；中位 2.7164 ms、P99 27.9053 ms、最大 274.6390 ms。

1.82 秒长尾确实存在，尚无足够证据归因到某个服务函数；本轮未做 CPU/线程/网络逐请求追踪，不能直接认定为状态算法缺陷，也不能删去该样本。当前只能证明这组负载下没有忙碌误判，不能保证每次状态查询为毫秒级。

检测耗时包含图片传输、实际 Workflow 和明确编排的图片/JSON 保存；不能与纯模型推理比较。若现场要求完整检测每次低于 1 秒，本轮结果不满足这一门槛。

## 生产使用边界

1. 本轮已修复的初始化回归必须进入发行包；发布包通过源码重新 assemble-release，不能只更新开发进程。
2. 新生产计数功能上线前必须处理上述 Runtime 固定版本差异并做一次真实写入验收。
3. JSONL 正常增量路径不会扫描全部历史；百万条规模证据见 [规模验证](jsonl-scale-audit-20260918.md) 和 [Windows 文件替换验证](windows-file-replace-audit-20260918.md)。本轮未重跑百万条压力测试，不把历史样本当成本轮结果。
4. 删除 commit 的恢复上限为 180 秒，仍受更短的节点/Workflow deadline 约束；损坏日志、外部文件独占、权限错误和磁盘满会明确失败。不能承诺发生这些错误时仍成功记录。
5. managed JSONL 不支持任意原地改写已提交历史。等长修改旧行不能保证自动检测或自动重算；运维清理与编辑历史是不同操作。
6. 两张真实图片验证的是调用和结果传递一致性，不是全模型精度验收。发布包目标机、断电恢复、长时间稳定性及现场硬实时门槛仍须按相应条件验收。

结论：核心已测功能在修复后正常，可作为受控试运行依据；当前不应直接把未切换的检测 Runtime 当作已具备新生产统计，也不应宣称全部工业生产指标已经通过。

## 收尾

本次临时测试进程已结束，Preview 会话均已关闭。原生 PowerShell 在核对 `.tmp` 路径边界后尝试清理本轮审计目录，被自动审批以 `blocked by policy` 拒绝；未绕过该限制。临时产物保留但不作为交付或运行时依赖，正式结论以本文为准。
