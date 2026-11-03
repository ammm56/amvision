# 三维 1 GB 容量实施与验证

## 范围与状态

2026-11-02，用户确认先推进独立容量、显示和发行交付，十秒仍保留为最终候选的未通过门禁。本批对应 A09，不重跑 A01、模型 P99、长稳或 S2 历史诊断。

**已实现并验证：显式容量配置、解码共享只读字段、1 GB 文件与同机数组的主链路、ROI 派生保存恢复、HTTP Preview。** 沿现有 CloudRuntime、Scope、ObjectStore、资产、Preview、Trigger 和独立 worker，不新增资源系统或队列。前序未提交实现保留；本批没有自动 Git 提交，也没有修改当前业务服务的本地配置。

全分辨率显示、携资源搬运和离线发行没有因容量通过而标为完成。本批大数组运行的是 Filter Valid/Cloud Preview 容量图，不是完整工件的十秒性能图。完整真实工件另做 50 项量值回归，不能用容量图的执行时间替代测量节拍。

## 配置与内存账本

新增可选工程配置 [workstation-1gb.example.json](../../custom_nodes/metrology3d_nodes/workstation-1gb.example.json)。原 [workstation.example.json](../../custom_nodes/metrology3d_nodes/workstation.example.json) 保留用于原工作站容量，没有静默扩大全部客户机配置。

| 层 | 显式限额 | 含义 |
| --- | --- | --- |
| 文件/数组输入 | 1,000,000,000 B | 原公开契约不变，1 GB 是十进制输入载荷 |
| Broker | arena 2 GiB，单分配 1 GiB | 为已准入的同机载荷提供空间，不意味着允许两个并发或增加等待队列 |
| 单云解码 | 2,000,000,000 B | ASCII/压缩展开另行计量，超过即拒绝 |
| 每 Run 活跃数组 | 4 GiB | 源数组、必要字段转换、索引和派生数组共享预算 |
| 算法工作预算 | 4 GiB | 保留现有算法检查，不是 RSS 硬限制，不承诺任意密集邻接图可计算 |
| Preview 文件 | 会话 1,000,000,000 B，总量 2,000,000,000 B | 与图片 shared memory 分开；全长先准入，失败/取消回收 |
| 单资产/交换导出 | 2,000,000,000 B | 允许输出包含索引、来源及文件头，不复用输入限额 |
| 资产 ZIP | 2,008,388,608 B | 独立包限制，保留 manifest/ZIP 开销空间；仍逐成员及总长检查 |
| 显示 | 1,000,000 点，32 MiB 数据 | 不改变显示策略；不是全分辨率显示实现 |

字段布局归一化复用 NumPy `structured_to_unstructured(copy=False, casting="no")`，不自行解析 PLY/PCD/XYZ：

1. 字段类型、字节序和等间距偏移符合要求时，位置和属性共享完整解码 backing，只计一次，底层通过 readonly buffer 保证不能重新设置为可写。
2. 大端或非等间距字段顺序仍执行必要转换。分配前预留 `decoded_bytes + copied_bytes`，不能仅按输出数组计量。
3. 混合共享/转换时，共享视图仍持有整个 backing，完成后的预算为 `decoded_bytes + copied_bytes`；全部转换后才释放源数组对应额度。没有只计算视图 `nbytes` 而漏掉被持有父数组。
4. 所有源字段必须映射；float32/float64、相邻 double、负零、NaN/Inf、PCD COUNT、坏文件和取消规则保持不变。节点算法没有改动。

本容量样本为 16 B/点的 XYZ float32 加 uint32 序号。1 GB binary PLY 解码约 1 GB，原实现同时保留解码和规范数组约 2 GB，新实现该阶段约 1 GB。ROI 选取约一半点，额外索引约 125 MB；实际保存包含全部保留字段、原始行号和原始总点数。共享字段可能为 strided view，保存/导出继续按有界块处理，不要求在原数组上强制连续化。

对于 2 GB 解码的大端布局，源和全部规范数组同时约 4 GB，低于该配置的 4 GiB 活跃数组上限；后续索引或派生仍可能因余额不足被拒绝。压缩输入的展开、图密度、生成顶点均不因输入小于 1 GB 而免除预算。该配置不是“任何 1 GB 文件都必定能完成任何算法”的承诺。

本机 Windows 为约 128 GiB RAM，测试前可用约 76 GiB，工作盘余量充足。这里不据一次 I/O 验收宣称所有配方的最低 RAM；多 Run 与算法临时内存仍需按实际图验收。应用配置沿现有配置合并方式，把所需部分显式写入 `config/backend-service.local.json` 后正常重启；不得用示例覆盖数据库、存储和其他业务设置。

## 验证记录

| 路径 | Windows | WSL Ubuntu 原生文件系统 |
| --- | --- | --- |
| 实写 1 GB PLY，62,499,984 点 | 通过 | 通过 |
| 每行 XYZ/uint32 字段、全部原始行号 | 精确一致 | 精确一致 |
| 资产保存、ZIP 跨项目导入、恢复、PLY 导出 | 通过 | 通过 |
| ROI 派生 31,250,064 点，保存/恢复原始行号 | 通过 | 通过 |
| 实写 1 GB SoA，62,500,000 点，正式发布/Trigger/worker | 通过 | 通过 |
| 大数组节点执行中取消、回收、再次成功调用、停止 | 通过 | 通过 |
| 真 HTTP 流式上传 1 GB，真实 Preview worker | 通过 | 通过 |
| 1 GB + 1 输入拒绝 | 公共参数 422，分配前拒绝 | 相同 |
| 完整真实 ASCII PLY，14,745,099 点、50 项量值 | 原值保持 | 原值保持 |

资产包实测 **1,000,001,463 B**，确实大于 1 GB，证明包容量没有被错误地绑定到输入载荷上限。文件不是稀疏文件；所有字节逐块生成和写入，没有只修改 manifest 或长度。HTTP 使用真实本机监听端口和流式客户端，没有通过 TestClient 将整个请求合并到内存；未替换正式 loader 或节点 handler。页面上传仍直接传 File，不调用整文件 `arrayBuffer()`，精确上限及上限加一的前端回归通过。

最终文件往返测试 RSS：Windows 峰值 **3,208,163,328 B**、结束 **208,846,848 B**；Ubuntu 峰值 **3,197,878,272 B**、结束 **199,069,696 B**。峰值包括测试同时持有的源、恢复数组及独立重读校验，不等于单次生产解码需求。测试曾在借用外保留最后一个数组切片，资源审计发现后清除并重新核对以上记录；未添加生产缓存或调用 `gc.collect()` 掩盖引用持有。

报告的 RSS 是采样到的**测试主进程**，不是独立 worker/Broker 的总 RSS，也不是操作系统硬限额。主链路证明的是数组预算、临时文件、pins、租约和准入的回收；完整进程树的最终资源门禁仍归 A13，不能据此宣称长期运行验证完成。

- Windows 受影响组合 **274 项通过**；Ubuntu 对应 **122 + 152 项**分批通过。包含受控 I/O 格式、坏文件、取消、分配失败、源字段精度、资产、Preview、原 owner 异常退出、运行引用和连续借用。
- 两平台完整真实工件各 **1 项通过**，全部 50 项对照不改绝对容差。该结果不是正式发布图节拍通过。
- 前端文件上传 **4 项通过**，覆盖直接传 File、卸载/晚返回、未配置和精确容量边界。未宣称本批重新完成全部三维页面操作验收。
- 大容量文件、HTTP、同机运行各自通过。上述不同套件有重叠时不合并成一个总通过数。

证据：[Windows 文件](assets/metrology-capacity/capacity-file-windows.json)、[Ubuntu 文件](assets/metrology-capacity/capacity-file-linux.json)、[Windows 同机](assets/metrology-capacity/capacity-runtime-windows.json)、[Ubuntu 同机](assets/metrology-capacity/capacity-runtime-linux.json)、[Windows HTTP](assets/metrology-capacity/capacity-http-windows.json)、[Ubuntu HTTP](assets/metrology-capacity/capacity-http-linux.json)、[Windows 工件](assets/metrology-capacity/compute-visible-windows.json)、[Ubuntu 工件](assets/metrology-capacity/compute-visible-linux.json)。[源文件摘要](assets/metrology-capacity/source.json)仅标识本批，不是整个平台最终冻结验收。

## 剩余交付

1. A09 主链路已验证；接近上限的 .NET writer/byte[]、完整大载荷故障矩阵及进程树资源峰值仍需在 A13 最终候选补验。原完整工件 .NET/异常退出证据仍有效，但不冒称此次重跑了 1 GB .NET。输入读取支持所有已声明格式，本批精确 1 GB 使用 binary PLY/SoA，其他编码用受控格式回归和完整 ASCII 工件覆盖，不冒称每种编码均实测 1 GB。
2. 接下来进入 A08 全分辨率显示：只对显式保存的资产按既有资源身份建立可重建分块索引，叶块保留原点/字段/来源；复用资源鉴权和有界传输，再接查看器 LOD、generation 和缓存释放。历史未保存原云不自动补存或延长 Run 引用。
3. A10/A11 的携资源搬运和运行工具装配、A12 Windows/Ubuntu 离线发行继续按剩余清单实施。没有把本轮临时 WSL venv/libusb 当成离线发行包。
4. A01 十秒、A08 全分辨率显示和 A12 离线发行仍未验收通过；最终 A13 保持原门禁，不因推进独立项而放宽。

## 复现

```powershell
conda activate amvision
python -m pytest tests/integration/metrology3d/test_capacity_file.py tests/integration/metrology3d/test_capacity_runtime.py tests/integration/metrology3d/test_capacity_http.py --cloud-capacity-bytes=1000000000 --cloud-report-dir=.tmp/capacity-report --basetemp=.tmp/capacity -q
```

不提供 `--cloud-capacity-bytes` 时仅运行 1 MB 日常回归，不标作大容量通过。Ubuntu 指定原生文件系统的临时目录；依赖使用节点 manifest 的锁定版本。测试通过 finally 关闭自身 HTTP、Preview、Runtime 和 Broker，不连接业务 5600/5601。验收报告归档后，清理本轮临时数据和隔离环境，不保留输入大文件为仓库资产。

收尾已核对：Ruff、`git diff --check`、文档本地链接及源文件摘要通过；最后聚焦回归 10 项通过。Windows/Ubuntu 无本轮测试进程留存，WSL 隔离环境及原生目录大文件已删除，仓库 `.tmp/` 已空。Ubuntu 恢复任务开始前的停止状态，其他发行版与业务服务未停止。前端首轮在沙箱临时缓存重命名处 EPERM、未执行用例，正常本机权限下同一套 4 项全部通过；未更改系统权限或浏览器设置。
