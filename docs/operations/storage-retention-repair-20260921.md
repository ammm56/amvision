# 文件保留清理修复验证记录（2026-09-21）

## 结论与范围

已修复本次审计确认的 Windows 目录遍历、保存/删除竞争、锁错误分类和缺图显示问题。时间策略仍严格按文件 mtime 判断过期，最旧优先；一个月按自然月计算。未增加后台扫描、任务队列、调度器或生产记录重放。

功能回归与真实环境短时验证通过，不等同于长期无人值守或百万文件规模验收。模型推理、LocalBuffer、部署 IPC 和 .NET 协议未修改；本轮没有重新做模型精度验收。公共保存 helper 增加了目录保护，因此包含磁盘保存的 Workflow 有可测量的额外开销，不能宣称所有同步链路耗时完全不变。

## 实现及修正依据

1. 普通文件扫描和空目录删除使用同一个显式 DFS。进入前过滤控制目录、临时文件、symlink/junction/reparse point，祖先受目录句柄保护。根目录不删除，异常与取消关闭所有遍历句柄。
2. Windows 条件删除使用真实文件 ID、大小和时间戳。`DirEntry.stat().st_ino` 在本环境为零，不能用作身份；扫描改用 `DirEntry.inode()`。删除时打开禁止写入/替换的句柄，重检后通过同一句柄删除。空目录也使用句柄删除；非空、被保护或已消失正常跳过。
3. Save bytes、复制、自动编号、LocalDatasetStorage 写入和通用 atomic write 共用祖先/父目录保护，覆盖 mkdir 与临时文件打开之间的窗口。正常并行保存不持有全目录独占写锁。
4. 初版“三次立即重试”在真实并发中再次触发 WinError 32，未作为通过结果。最终仅目录准备的 WinError 32/33/303 使用最多 100 ms、间隔 1 ms 的有界重试；不存在目录最多三次恢复。无冲突路径不等待；权限错误直接失败。超限保留原始错误，并附 `file_io_stage=protect_directory`、路径。它不重新执行 Save 内容、推理或整个 Workflow。
5. Windows 路径锁改用 LockFileEx，保留准确 winerror。只有明确锁竞争返回 locked，权限/句柄错误不能伪装成“忙”。沿用现有锁位置与跨进程协议。
6. 扫描各目录/条目、分页以及每次删除前检查 ExecutionControl。错误附操作阶段及有界计数，中途取消不会报告全批成功。临时文件清理失败不会覆盖原始写入异常。
7. `Load Local Image` 新增可选 `missing_file_policy=error|blank`，默认 error。blank 仅处理无版本绑定的 Path 真正不存在，返回带 “Image unavailable” 的 JPEG 和明确 summary；权限、损坏、资源超限及 File 观察版本错误仍失败。现有空输入回退行为保留。
8. 尚未证明 POSIX 具有相同的空目录生命周期保护，因此非 Windows 实际清理且启用 `delete_empty_directories` 时在任何删除前拒绝；关闭该选项可保留文件清理，dry-run 可用。没有将 advisory flock 当作对外部路径操作的强制保护。

目录句柄的 Windows 打开方式与共享语义参见 [CreateFile](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilea)、[目录句柄](https://learn.microsoft.com/en-us/windows/win32/fileio/obtaining-a-handle-to-a-directory)。这些是操作系统语义依据，不能替代本项目并发测试。

## 回归验证

- conda `amvision`：最终相关测试集 134 passed、1 skipped。
- 发行目录 `full-windows-x64-nvidia/python/python.exe`，Python 3.12.13，执行仓库源码：前一轮完整测试集 133 passed、1 skipped；最终源码与新增平台边界用例的保留清理专项 37 passed、1 skipped。
- 跳过项是缺少 Windows 符号链接创建权限；单独的 junction 回归实际执行并通过。
- 覆盖日历边界、最旧顺序、删除上限、ObjectStore、版本改变、占用、跨进程锁、junction 外部空目录、控制目录后代、保存竞争、取消后继续调用、异常清理、严格缺图与恢复。
- JSONL 与 File Summary 共 35 项回归包含在上述测试集中，用于核对公共路径锁与原子写入变化。
- 4 个保存线程与 1 个清理线程并行：10 轮，每轮 160 个 8 KB 文件，文件完整；每轮 GC 后 handle 均为 204，线程均为 4。Private Memory 约 15.30 MB 至 15.86 MB，最后三轮持平。该短测不能排除长时间资源增长。

## 性能实测

Windows 本机磁盘，隔离目录，不修改现场文件时间戳。小样本仅描述观察值，不能作为 P99 或长期性能门禁结论。

| 场景 | 结果 |
| --- | --- |
| 8 KB 覆盖原子保存，旧 helper，预热后 50 次 | P50 1.358 ms，P95 1.730 ms |
| 同目录同内容，新 helper，交替测量 50 次 | P50 1.810 ms，P95 2.451 ms，最大 8.818 ms |
| 1,000 文件，按期限删除 600 个 | 866.089 ms，剩余 400 个，结果正确 |
| 10,000 文件，数量策略删除 9,000 个 | 11,514.779 ms，剩余 1,000 个，结果正确 |
| 最终文件 ID 校验实现，10,000 文件 dry-run，3 次 | 平均 1,252.192 ms，handle delta 0 |

删除和扫描都不是任意规模的一秒内操作。delete_limit 只限制删除数量，不限制全扫描成本。大规模目录仍建议显式独立维护 Workflow、外部低频调用；本次未擅自迁移实际编排。内存为有界候选 heap、分页和 DFS 栈，不收集全部文件/目录。

## 实际 Workflow 配置与浏览器验证

实际应用 `workflow-app-20260910030132` 保存时为 132 个节点、159 条连线。保持九个清理节点的目录、组、位置、连线、一个月保留策略、1000 删除上限与启用状态；清理根仅覆盖三类原图、结果图和结果 JSON，不覆盖生产统计目录。

仅以下六个业务图片读取节点增加 `missing_file_policy=blank`：

- tray_original_load、tray_result_load
- box_original_load、box_result_load
- core_io_image_load_local、core_io_image_load_local_2

保存后读取回核对模板。指纹为 `sha256:7740aede212a2f18f11e3661333bea5f538be124e477791db0998d3f332fa768`。无结果分支和检测输入未放宽。

原应用真实预览成功：首次 graph 365.143 ms、Worker 650.682 ms、浏览器完整接收 4423.900 ms；后续一次 graph 423.067 ms、Worker 648.905 ms、浏览器 2665.000 ms。首次包含 Worker 启动和前端准备，不将 graph 时间当成端到端耗时。九个清理节点成功，现场 12 张图片、6 个结果 JSON 没有过期候选，没有删除现场文件。

最终源码重载后再次验证成功：graph 351.510 ms、Worker 606.811 ms、浏览器完整接收 4469.100 ms；包括本轮冷启动，不能用该单次样本推算稳定 P99。

缺图验证使用独立模板、独立 Runtime、真实 JSONL 的隔离副本，清理节点仅 dry-run。初次构造测试副本时确认 Copy API 共享模板引用，已立即分离模板并回核实际模板；测试不依赖断开分支内路径连线。最终保持全部 159 条连接，仅将副本中的图片路径指向不存在的测试文件：

| 显示区域 | 生产总数 | OK | NG | 良品率 |
| --- | ---: | ---: | ---: | ---: |
| 治具 | 48 | 24 | 24 | 50.00% |
| 塑盒满盘 | 80 | 80 | 0 | 100.00% |
| 塑盒空盘 | 240 | 160 | 80 | 66.67% |

六张缺图均输出 640×480 JPEG 占位。节点预览、Runtime 应用模式、大图查看器均正常；图片缺失不改变统计或业务结论。把六张真实图片复制到隔离路径后，下一次同步调用恢复真实图像，治具大图为 2560×2358，叠加统计保持一致。

隔离 Runtime 恢复真实图片后 5 次同步 HTTP 调用均 succeeded：519.636、610.079、495.778、631.585、543.832 ms。这是显示 Workflow 的端到端调用，不是模型推理基准或 Trigger P99。

测试 Runtime 已停止并删除，临时应用、版本由应用删除接口清理，测试标签页关闭。原应用草稿保留。

任务测试进程结束后，`.tmp/retention-repair-20260921` 的原生 PowerShell 清理命令被自动审批策略拒绝（仅返回 blocked by policy）。该目录尚未清理，不是交付资产；未通过其他方法重试同一删除。此前审计任务被阻止清理的临时目录同样没有绕过策略删除。

## 发布边界和待验收内容

现场已有 `workflow-runtime-71bf1addb3614f24b7554eec8925b343` 实际仍绑定 **v9**，虽然应用已有 v10 发布记录。此次六个缺图参数保存在草稿，未替换既有 Runtime 的不可变快照；需要按正常发布及版本切换流程使配置进入该 Runtime。没有把“草稿已保存”当成正式 Runtime 已更新。

发行 Python 验证使用新源码，未手工修改发行目录源码，也未重新 assemble-release。正式发行仍需重新组装。开发服务检查 ready=true、无 blockers；已有正式 Runtime 未停止或切换。

未完成：跨日期长时间运行、断电/磁盘故障、外部程序恶意持续替换路径、部署规模十万/百万文件的长期并发性能门禁、正式 Runtime/Trigger 全套性能复验。操作系统阻塞调用仍不能由协作取消立即中断。已删除文件不可回滚，任意外部持续破坏路径不保证保存成功，但不能静默误报成功。
