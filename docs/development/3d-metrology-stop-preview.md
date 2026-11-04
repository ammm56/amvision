# 3D Metrology 停止与完整 Preview 验证

日期：2026-11-03。沿[剩余清单 7.5](3d-metrology-remaining.md#75-双平台离线续验后的固定计划)执行。基点 `01587765`，包含前序尚未提交的参数来源生命周期、数值显示与容量测试；没有撤销这些修改，没有自动提交。

## 修改范围与根因

### 资源采样

前轮报告只有 `(pid=544)`，不能直接判断错误。本轮在现有 ResourceGate 中增加有界诊断：阶段、资源字段、根/目标身份、异常类型、发生时间及复查身份/状态。

真实 Ubuntu 小载荷强杀复现为：读取子进程 `num_fds` 时抛 `AccessDenied`，复查 PID/create_time 相同，但状态已为 zombie。不是活进程权限不足，也不是根进程失效。见[复现报告](assets/metrology-stop/fault-fields-linux.json)。

只对这个已证实边界丢弃整次不完整样本并计数，不用零替代资源、不忽略任意 AccessDenied。根进程、活进程、PID 复用及其他权限错误仍失败；采样间隔、覆盖率和门禁不变。新增确定性用例覆盖这些相反条件。

修复后[Windows](assets/metrology-stop/fault-windows.json) 199 个有效样本、零错误；[Ubuntu](assets/metrology-stop/fault-final-linux.json) 1,130 个有效样本、4 次已核实 zombie FD 丢弃、零错误。旧执行失败、停止、切版、旧 generation 拒绝、新版本调用和租约归零均通过。使用 16 MB 实写数据定位进程竞态，没有重复全套 1 GB 往返。

### Preview Pool 停止

实际 semaphore 路径见[停止前证据](assets/metrology-stop/before-stop-closed.json)。Preview Pool 已关闭 worker，但 app 仍引用 pool，pool 的 slots 仍引用 Event。两个 Event 的十个原生 semaphore 在 close 返回后依然存在；真实 Uvicorn SIGTERM 退出路径重新触发信号，不保证执行这些仍存活对象的 Python 退出 finalizer。

修复仅在现有 `PreviewSessionPool.close()` 成功关闭所有 slot 后清空槽位引用。关闭失败保留原槽位，供已有停止重试路径继续处理。没有增加平台分支、第二套进程管理、延迟退出、手工 unregister 或删除 `/dev/shm`。

回归覆盖引用释放、真实 Linux semaphore 名称、真实 Uvicorn SIGTERM、关闭失败后重试。修复前 Windows 两项失败、两项 Linux 专项跳过；Ubuntu 四项失败。修复后 Windows 停止/worker/采样组合 33 项通过、2 项 Linux 专项跳过；Ubuntu 停止/worker/session/采样与小载荷故障组合 46 项通过。既有 worker 测试分开等待模型依赖启动和执行窗口，未修改生产 timeout。

### 完整工件 Preview

真实完整文件页面初次执行到显示节点失败，数值节点已经得到五十项结果：

1. Runtime 的三维证据按逐项结构预算处理，但编辑器 PreviewValues 仍以整个证据集合共用普通 JSON 计数，错误拒绝合法的五十项测量证据。
2. 节点 inputs/outputs 控制事件再次携带完整嵌套内容，已有逐容器脱敏并不等于总消息有界，触发 `preview_event_capacity`。

编辑器复制前预留与 Runtime 复制现在共用同一证据分组，保留强类型校验、单项结构/深度、最多 8,192 项、总字节及复制预算。非三维 JSON 不获得豁免。大节点控制内容明确返回有界摘要，完整值仍走既有 value.updated/Blob 通道，取消/超时终态和调用身份不丢失。

收尾审计另用 128 个短控制字符字符串复现 JSON 转义后 6,144,648 B 超限。已增加先结构预检、再流式统计实际 JSON 编码字节，不拼接巨型控制串。回归先失败后通过；没有抬高 4 MiB 控制通道上限。

实际完整文件回归使用正式工件图、真实 Preview worker 与 WebSocket 准入：111 节点完成、500,000 点概览、50 项测量证据和两个圆特征。Windows/Ubuntu 各一项通过，释放后临时文件、Blob、预算和 pins 归零。报告：[Windows](assets/metrology-stop/preview-windows.json)、[Ubuntu](assets/metrology-stop/preview-linux.json)。转换/复制/显示/session 组合各 76 项通过；末尾转义保护的受影响组合各 33 项通过，数字重叠不累计。

## 实际页面

本轮只使用隔离 5620/5621；不修改业务 5600/5601。使用完整 `1-1_0.ply`，不是合成小云。

| 路径 | 实际证据 |
| --- | --- |
| 完整图编辑器 Preview | 111 节点成功，完整输入 14,745,099 点，五十项证据；见[截图](assets/metrology-stop/complete-preview.png) |
| A_top_L.H 来源切换 | pose U/V 切换为配置测量线时，缺参数/冲突接线明确显示且 Apply 禁用；切回不挪用另一来源候选，取消重开恢复原图 |
| S2 方法防错 | 显式切到连续边长方法，残差尺度为零时不能提交；取消不更改原角区方法/质量限值 |
| 台面五窗 ROI | 隐藏 D1 后参与裁剪复选框仍选中；显示与计算分开，取消不改参数 |
| 发布文件 Runtime | 页面真实上传完整文件，五十项数值和点云显示成功；见[截图](assets/metrology-stop/published-preview.png) |
| 离开与切版 | 离开编辑器关闭 Preview session；停止后切版更新 generation，显式启动；破坏性输出合同变化必须确认并填写原因，旧结果不混到新版本 |
| 原始细节取消/重入 | 复用 Read Cloud → Cloud Preview → HTTP Response 查看图，真实发布后缩放加载 690,937 个原始点；取消回到概览，重开重新加载，关闭/重入清除旧视图；见[截图](assets/metrology-stop/raw-details.png) |

显示配置边界也已实际验证：未保存派生云不能开启原始细节；1 GiB 活跃数组配置下本资产索引准备被预算拒绝。两者没有降采样冒充成功。完整资产查看的容量要求与普通概览不同，不将历史完整细节通过解释为任意配置都可用。

原始细节成功页面使用既有 `workstation-1gb.example.json` 的点云策略，活跃数组上限 4 GiB，不是临时猜测或提高节点质量门禁。资产仍为完整 14,745,099 点，概览为 100,000 点；全视野超预算明确显示概览，缩放后标明“当前视野全分辨率”。发布 `workflow-app-version-492bcb546947417091acae3c833e2e5f`、Runtime `workflow-runtime-05c8d827445843c695db3d895f14581c`。这是独立查看器链路，不冒称普通 1 GiB 工程配置的完整测量图已能同时准备原始细节，也不冒称接近 1 GB 资产索引已通过。重入后浏览器错误日志为空；没有取得浏览器精确显存/进程分项峰值。

本轮 Workflow 前端组合 43 文件、287 项通过、2 项既有跳过。前序四个 Vue 组件没有在本批再次修改。参数与显示测试不能代替全部方法页面矩阵；固定资产版本冲突/导出的完整手工路径、剩余方法及浏览器分项资源仍按 A08/A13 保留。

## 最终双平台 CPU 候选

末尾控制消息字节补强后重新执行 `assemble-release`，未手工修改发行 app 源码。两个候选各完成空库携资源导入、真实发布、运行、保存结果、全栈停止及同目录重启再次运行。每次均对照既有五十项数值、单位、valid/reason、三态和落盘记录，不以计数替代量值核验。

| 平台 | 两轮 50 项 | 全栈/IPC | 进程树观测 |
| --- | --- | --- | --- |
| Windows CPU | 全部一致 | 两轮所有受管身份退出，日志无 semaphore 警告 | 54/54 个有效样本、1 次子进程退出样本丢弃、零错误；RSS 峰值 3,068,801,024 B |
| WSL Ubuntu CPU 原生目录 | 全部一致 | 同次 boot 内 semaphore 增量零、无 tracker 警告，所有受管身份退出 | 91/95 个有效样本、零错误；RSS 峰值 3,711,737,856 B |

Windows 不使用 POSIX 命名 semaphore；报告中的原生 IPC 字段仅在 Ubuntu 有此含义。资源报告 `status=observed`、`limits={}`，是短时观测，不是正式资源门禁通过或长期无泄漏证明。进程树 RSS 可重复计入共享映射，不能据此给出最低整机 RAM；Windows private bytes 也不等于驻留物理内存。

调用到结果/落盘核验时间为 Windows 14.828/15.172 秒，Ubuntu 9.044/9.476 秒，包含资产读取、显示和核对且非独占；**不更新 A01 十秒验收结论**。没有重复 P99、S2 历史稳定性或长稳。

包 SHA256 `829f34d750801feb602e2d69c75f0d7e94b9790f5843251fbb8588abc181571d`，原云资产摘要 `c9566ae231f30a4b55226673d8644346eb6a58d8bafb66130784596c2da345ed`。源码、依赖、逐轮结果和停止日志见[Windows](assets/metrology-stop/offline-windows/report.json)、[Ubuntu](assets/metrology-stop/offline-ubuntu/report.json)及同目录 source.json。Windows/Ubuntu 分别 3,271/3,269 个后端/节点/启动器/客户端文件匹配源码，另各 116 个前端文件匹配静态产物；Shell 按既有装配规则规范换行。

## 完成边界

本轮完成采样根因、正常停止根因及修复，并修复真实完整 Preview 暴露的两处传输不一致；未改几何计算、模型精度、质量门禁、生产容量默认值、调度器或并发准入。正式工件数值与保存内容保持原值。

尚不能宣布 A13 全部完成：A08 剩余页面与浏览器分项资源、A01 正式十秒、A09 近 1 GB 索引有界构建仍有明确范围。独立实体计量认证缺外部参考；S2 当前方法保持已授权工程可用；B01–B23 没有在本轮新增实现。不新增阶段、不重开已通过的 A10/A11/A12。

收尾审计：最终四个生产文件与两包 source.json 摘要一致；Ruff、`git diff --check` 和文档本地链接核对通过。最后一轮完整 Preview 为 Windows 55.49 秒、Ubuntu 85.37 秒测试总时长，不是检测节拍。隔离页面 Runtime 已显示 stopped，5620/5621/5630/5632 无监听，本轮测试进程退出；精简证据归档后 `.tmp/` 为空，Ubuntu 本轮原生临时目录已删除并恢复 Stopped，crypto 仍 Running。业务 5600/5601、原始样本、既有 release 和系统 Python 未修改。无自动 Git 提交。
