# 三维固定资产操作与资源观测

## 范围与当前位置

2026-11-04，沿[剩余清单](3d-metrology-remaining.md)第 7 节顺序 2 完成 A08 固定资产页面链路及 A09 逐进程观测。基点 `01587765`，保留前序未提交的有界索引、Preview、参数生命周期和结果显示修改。本轮没有新节点、算法、质量限值、配方数值、生产容量、协议版本、等待队列或启动超时变更。

十八节点及 111 节点/317 边、50 项必检配方仍可用。本轮为固定资产读取/保存/导出的定向验收，不把这条资产图说成重新验证了五十项测量或十秒节拍。既有精确 1 GB、索引和 S2 历史诊断没有重跑。

## 已修复问题

| 问题 | 实际原因 | 修改与边界 |
| --- | --- | --- |
| 来源/保存控件溢出节点，后续端口位置不一致 | 画布按普通单行字段计算高度，三维来源和保存控件实际有多行 | `cloud-resource-fields.ts` 为两种现有 widget 提供共享高度；控件与画布几何使用同一值，不另建布局系统 |
| 长资源 ID 换行挤压版本；资产来源仍显示 File Options null | 资源按钮无单行约束；字段列表未消费已有 `x-asset-clears` 互斥声明 | 按钮前置版本、单行省略，title/无障碍标签保留全 ID；只隐藏当前资产来源声明的互斥字段，不改已保存参数，切回文件恢复显示 |
| 保存冲突难以找到原因 | Preview 只展示有界 JSON 摘录，错误字段可能落在截断区域外 | 在现有结果面板增加现有 InlineMessage，单独展示节点、错误码和原因；切换 Run 自动更新/清除，不改变后端错误分类或重试行为 |
| Ubuntu 新验收命令的 spawn 启动门超时 | 入口顶层导入整套测试服务，子进程重读主模块耗时约 31.72 秒，超过原有 30 秒门 | 仅将新验收脚本的重依赖导入移到使用位置/主入口；保留生产启动门、归属和停止机制。新增独立子解释器回归，确保 `__mp_main__` 不加载 API、NumPy 或发布测试容器 |

生产代码影响仅为 Vue 参数显示/几何和 Preview 错误提示。既有资源选择、乐观版本冲突、保存原子提交、发布准入、worker 与 Broker 直接复用。资源采样扩展只在 `tests/integration/runtime_resource_gate.py`，`include_processes` 默认关闭；开启时输出同一采样内的 PID、创建时间、父 PID、RSS、私有内存、线程和句柄/FD，不增加运行时常驻监视器。

## 真实样本与发布链路

输入为完整 `1-1_0.ply`：14,745,099 点，479,677,235 B，XYZ float32，原文件 SHA-256 `ff2b9e0ef2d6c45af02c4bf8d474cd82f77f86ad92bd371a4c0f71b1b90d116b`。原文件和手工报告未修改。

双平台使用同一 [asset_operations.py](../../tests/integration/metrology3d/asset_operations.py)，沿正式 REST 草稿/发布、WorkflowAppRuntime、独立 worker 和现有节点执行：

1. 原样本保存为固定资产 v1；发布读取 v1、保存下一版本的图，运行生成 v2。
2. 对旧基版本再次调用，必须返回 `resource_conflict`、节点 `save`。版本数量及完整资源文件集合不变，不生成半成品或覆盖新版本。
3. 停止、显式选择 v2 为保存基版、重新发布并启动，成功生成 v3。
4. 现有 Export Cloud 导出 binary little-endian PLY，再通过正式读取入口重读。分块逐行比较全部 XYZ 位值、dtype 和原始行号，不用预览点数代替精度检查。
5. 切换只读显示发布版本并调用；每次调用核对 Broker 租约、运行准入归还，局部 Scope 关闭后预算归零，结束停止全部本轮子进程。

Windows 与 Ubuntu 最终资源内容摘要一致：`c9566ae231f30a4b55226673d8644346eb6a58d8bafb66130784596c2da345ed`。报告见 [Windows](assets/metrology-asset-operations/windows.json)、[Ubuntu](assets/metrology-asset-operations/ubuntu.json)。本样本只有 XYZ，不由此宣称所有附加字段格式均重新验收；多字段/生成点/边界资产继续由既有单元与集成覆盖。

## 页面验收

隔离 5620/5621 使用真实后端及完整样本资产，不访问业务库。完成以下操作：

- 资源选择器查看 v1/v2/v3、字段、单位和摘要；固定读 v1，保存草稿并重开后仍是 v1，不隐式选最新。
- 下载 v3 资产 ZIP，176,942,710 B；`data.bin` 的 SHA-256 与清单一致，为 `956927f058ba4a0170b1c1b93b1411b613fbe21fcbfc278ad0a7fc3cf621a1c6`。ZIP SHA-256 为 `ee8a2b1a967bc5b8eb9297067ed837d1a0c08586bb7d4640376352f84c9579d8`。
- 加载旧基版保存图，Preview 正确失败并直接展示 Save Cloud 的冲突原因；显式改为基版 v3 后 Preview 成功生成资产 v4。
- 改为保存基版 v4，从图编辑页面发布 AppVersion v5；页面停止 Runtime、选择 v5、启动及同步 invoke 成功，生成资产 v5。运行 ID 为 `workflow-run-d3b112f788d349f6b23470004d0af5c8`，返回完整工件概览，最后页面停止状态为 stopped。
- 中文亮色桌面与英文暗色 960×720 资源选择操作；完成后恢复语言、主题和视口。不涉及系统显示缩放。
- 页面捕获的 error/warn 日志为空。显示为 100,000 点有界概览，输入仍为完整 14,745,099 点，不把概览称为整云同时驻留显存。

证据：[完整云](assets/metrology-asset-operations/full-cloud.jpg)、[版本冲突](assets/metrology-asset-operations/version-conflict.jpg)、[恢复保存](assets/metrology-asset-operations/save-recovered.jpg)、[英文暗色窄屏](assets/metrology-asset-operations/assets-narrow-dark.jpg)、[发布输出](assets/metrology-asset-operations/published-success.jpg)。页面只在 Windows 浏览器验收；Ubuntu 覆盖后端真实发布链路，不冒称 Ubuntu 桌面浏览器已测。

## 验证结果

| 验证 | 结果与范围 |
| --- | --- |
| Windows 后端 | 资产、资源 API、数据节点、ResourceGate 组合 63 项通过；最终发布/入口回归 2 项通过，共 65 个不同用例 |
| WSL Ubuntu 后端 | 原组合含发布回归 64 项通过；入口调整后的两个定向用例通过，去重后覆盖 65 项，不相加为 66 |
| Windows / WSL 完整样本 | 两端最终命令正常退出；保存冲突、显式恢复、导出重读、租约和预算释放均通过 |
| 前端 | 8 文件、35 项通过；含导出晚返回、关闭/切项目/切引用/禁用/卸载取消、Blob URL 回收、控件高度/端口位置、切回文件、错误截断与跨 Run 清除、纯文本防注入 |
| 静态检查 | Vue 类型检查、变更 Python Ruff、`git diff --check` 通过 |

Ubuntu 首次完整命令的超时被保留为失败事实，没有增加生产超时让测试通过；入口修正后使用新的空数据目录完成同一原链路。组合测试启动较慢时的 faulthandler 堆栈不当作算法错误或无泄漏结论。

复现入口使用开发环境 `conda activate amvision` 后的 Python，或隔离 Ubuntu venv；Ubuntu 运行数据必须位于原生文件系统。示例：

```powershell
python -m tests.integration.metrology3d.asset_operations --root .tmp/asset-acceptance --sample <完整PLY路径>
python -m pytest tests/integration/metrology3d/test_asset_operations.py tests/test_runtime_resource_gate.py
```

`--root` 必须不存在；可选 `--serve 5620` 用于页面验收，由目录内 `stop` 文件正常退出。命令拒绝占用 5600/5601；不直接写数据库或替换 handler。

## 资源观测与限制

最终轻量验收入口的资源采样如下；每次调用为真实 worker，主进程同时承载测试客户端和 API，二者不能拆成独立进程数值。

| 平台 | 有效样本 | 进程树 RSS 采样峰值 | API/测试调用方峰值 | Broker 峰值 | 单 worker 最大采样峰值 |
| --- | --- | --- | --- | --- | --- |
| Windows | 203 | 1,034.17 MiB | 747.20 MiB | 38.77 MiB | 538.07 MiB |
| WSL Ubuntu | 558 | 1,228.71 MiB | 874.75 MiB | 34.12 MiB | 605.84 MiB |

两端采样错误均为 0；退出竞态中的不完整采样仍整条丢弃，不将部分进程缺失算成零。分 PID 创建时间与峰值已入报告。每个 PID 的独立峰值发生时间不同，不能相加作为同时峰值。Linux 现有 `private_bytes` 口径回退到 RSS，不能当 USS；共享映射可能被各进程 RSS 重复计算，不能据此确定最低整机 RAM。

状态明确为 `observed`，未设置资源增长门禁，也没有稳定负载时长；启动、文件解析、保存、导出、校验和结束均在观测窗口内，不用启动前后增长推断长期泄漏。浏览器、GPU 显存和独立外部调用进程未纳入该树。没有执行新的长稳或十秒验收。

[Windows 页面观测](assets/metrology-asset-operations/windows-page.json) 包含较长页面操作、前版驱动的重导入及初次显示索引，峰值 2,274.46 MiB；它不是最终同口径资源对照。轻量入口消除了测试程序对子进程的额外加载，不声称本轮优化了生产 Broker 算法。

## 剩余与下一步

| 项目 | 本轮后真正剩余 | 后续处理 |
| --- | --- | --- |
| A08 | 十八节点账本中未覆盖方法的代表操作；索引损坏/删除及 WebGL context 丢失页面、浏览器连续切换回收观测 | 不重做 viewer，不重复固定资产整链路；独立几何覆盖非工件方法 |
| A09 | 浏览器/可观测图形资源、独立外部客户端等角色矩阵；不能把本轮完整样本资源值外推到所有 1 GB 布局 | 与相关页面/容量批次合并补证；已通过的精确 1 GB 主链路和有界索引不重新列为缺实现 |
| A01 | 当前正式图受控十秒结论与有收益的串行优化 | 按既定一次热点诊断、等价验证、局部收益、整图计时顺序，不因未达标阻塞 B 组 |
| A12/A13 | 本批 UI 与前序索引未重新装配到 CPU 离线包 | 下次实际交付同批装配，不在每项源码测试后重装全包 |
| B01–B23 | 仍按固定功能组实施，当前没有新增通用算法 | 下一能力组为去噪、重采样、法向，包含 UI/来源/保存/发布而非只补函数 |
| A04 | 独立实体参考及重复采集证据 | 只限制计量认证声明，不阻塞当前工程使用 |

候选文件身份见 [candidate.json](assets/metrology-asset-operations/candidate.json)。本轮未自动提交 Git。验收临时数据不是交付资产，已归档有界报告和截图；通过与初次失败记录分别见 [Ubuntu 组合](assets/metrology-asset-operations/ubuntu-combination.txt)、[最终定向](assets/metrology-asset-operations/ubuntu-final-tests.txt)、[初次启动门失败](assets/metrology-asset-operations/ubuntu-initial-spawn-failure.txt)。

完成后已正常停止本轮 Runtime、后端及 Vite，5620/5621 无监听，测试调用方/Broker/worker 均退出；仓库 `.tmp/` 清空，浏览器下载的单个测试 ZIP 按归档 SHA-256 核对后删除。Ubuntu 本轮隔离依赖及运行数据目录已删除，发行版恢复 Stopped；其他 WSL 发行版未停止。业务 5600/5601、原始样本和已有发行包保持不变。
