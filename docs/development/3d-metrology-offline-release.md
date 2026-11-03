# A12 CPU 离线发行验收

## 范围与状态

2026-11-02，基于当前工作区，尚未提交。范围仅为 Windows x64 / WSL Ubuntu 24.04 CPU 离线发行，复用现有 assemble-release、full Supervisor、A10 搬运和 A11 工具，不改算法、质量条件、十秒门禁或显示索引容量。完整步骤见 [CPU 离线发行](../deployment/cpu-offline-release.md)。

既定 A12 CPU 发行范围已实现并完成双平台真实组合验收；不代表 A13 最终整个平台候选验收或现场计量认证。前序未提交修改仍保留，本轮结果基于工作区完整代码，不能用仅检出当前 HEAD 复现。

## 实际修复

- Ubuntu CPU profile 从预留改为完整装配目标，复制平台对应入口、FFmpeg 和原生资产。
- 三维依赖锁直接来自节点 manifest；受控 wheel/构建记录与原生库清单、摘要随包校验。Open3D 实际平面核、SciPy 索引与 trimesh 几何核参与预检。
- Ubuntu Open3D 的 libusb 缺失由受控随包库解决，保留官方包来源、SHA256 与许可；无现场 apt 安装。
- full 必需文件检查不再要求 Ubuntu 存在 Windows 长路径工具。保留统一监督、就绪和停止逻辑。
- 可移植 CPython 的 fcntl 未导出 OFD 常量。底层适配器使用 Linux UAPI 固定命令 36/37，仍执行同一 OFD 锁，不回退 lockf；覆盖 mmap owner 探测和路径写锁。发行预检增加实际 owner 独占/冲突/释放探测。
- 发行子进程不继承开发 Python 搜索路径；Shell 不再回退系统解释器。开发 `*.local.json` 不复制到现场。
- Windows 本次隔离 Python 补齐正式 requirements 的 threadpoolctl 3.6.0。构建依赖和运行依赖严格区分。
- 真实 Windows 第二轮运行复现启动后立即 invoke 被 `runtime_lifecycle` 拒绝：后台恢复扫描在显式 start 期间发现 worker 缺失，恢复线程等待生命周期锁，随后对已启动的 Runtime 重复恢复并抢占准入。修复沿原 guard 非等待获取；占用时退出，在锁内重查 worker 是否已经可用，由既有下次缺失扫描处理真正待恢复项。没有添加调用重试、等待队列或关闭自动恢复。两项受控时序回归、既有恢复/版本切换/清理组合及双平台原真实路径均通过。

## 验证方法

`tests/integration/metrology3d/offline_release.py` 使用正式资源保存/导出准备包，目标端没有 TestClient、测试注册器或假 handler；调用真实服务的导入、草稿指纹发布、Runtime 启停和 invoke。发行子进程清除 Conda/Python 源码环境，前端由发行服务静态提供，不启动 Vite。外部 HTTP 代理指向不可用端口，模型下载设为离线；本项不是操作系统防火墙审计。

输入为完整 `1-1_0.ply`，14,745,099 点、479,677,235 字节；正式工件配方 111 节点、50 项结果。原点云保存为可搬运资产，同包分别导入空 Windows / Ubuntu 存储。每次正式运行逐项对照冻结的有效性、原因、单位、值，绝对数值容差沿既有 `1e-7`，并比较落盘 Result Record。停止全栈后从原目录重启，复用持久发布和资产再运行，最后核对已记录进程身份退出。

Ubuntu 发行数据、控制文件和回归临时文件均位于原生文件系统。Windows 验收端口 5630，Ubuntu 5632；不使用业务 5600/5601 或前序 5620/5621。构建机可联网准备依赖，目标运行不下载依赖。

## 结果

- 双平台 pip check 已通过。
- 正式 Vue 类型检查与 Vite build 已通过。
- Windows 最终发行/工具/前端配置/锁/生命周期/恢复组合 **112 项通过、8 项平台跳过**。
- Ubuntu 原生目录最初组合 90 项通过、6 项跳过，2 项模拟 Windows 启动器测试因隐式解析为 Linux Python 失败。测试改为显式指定其已有模拟 Windows 解释器，不修改生产回退逻辑。最终包含这两项、恢复/锁/运行时校验的定向组合 **54 项通过、5 项跳过**；与前项重叠，不累计成新的唯一测试数量。
- Windows 和 Ubuntu 均通过实际 `validate-layout`，包括自带 Python、CPU-only torch、三维锁、原生调用、A11 文件完整性与 IPC 独占探测。
- 最后逐文件核对 Windows 3,225 / Ubuntu 3,223 个后端、节点与启动器源码/契约，以及 111 个前端构建资产，均与构建源一致；平台启动脚本差异显式保留。两平台自带解释器的 A11 invoke 帮助和正式数组配方生成成功。源码清单和安装版本保留在 `source.json`，不把开发环境安装版本当发行版本。
- **两平台各两轮完整离线发布运行通过，每轮 50 项数值、判定和落盘记录一致。** 空环境导入后停止全栈，再次启动同一目录使用持久发布与资源成功；两轮均检查整组子进程退出，未添加 invoke 重试。
- 两平台每轮同源 HTML 和 6 个入口静态资产均正常响应；Windows 实际浏览器打开随包页面并显示导入项目，不依赖 Vite/CDN。本轮不重复十八节点全部交互矩阵。

| 平台 | 第一轮 | 停止后重启轮 | 结果 |
| --- | --- | --- | --- |
| Windows x64 | 28.203 秒 | 22.031 秒 | 50 项一致，组停止通过 |
| WSL Ubuntu 24.04 | 10.288 秒 | 22.496 秒 | 50 项一致，组停止通过 |

以上时间是发行链路 invoke 至结果/落盘核对，包含资产读取；两平台验收有计算重叠，**不是受控的 A01 十秒验收**，没有以这些时间宣称新性能结论。输入为同一携资源包，SHA256 `cd42ca53137013ec343dd32bd4c700fbfe6430a6edd13c5b242d64789a8927cd`。

精简证据保存在 [Windows 结果](assets/metrology-offline/windows/report.json)、[Ubuntu 结果](assets/metrology-offline/ubuntu/report.json)；同目录包含逐轮结果、预检、启动停止记录（`.txt`）、源码摘要和实际安装分发版本。原始点云、Python 副本与临时数据库不作为 Git 资产保留。

## 复现入口

构建与安装按部署文档完成后，用仓库中的正式验收驱动准备包并验证隔离候选；不在已有生产目录运行空库验收。Windows 开发端先激活 `amvision`，Ubuntu 的报告与数据目录必须为原生文件系统。

```text
python -m tests.integration.metrology3d.offline_release --prepare <完整PLY> --root .tmp/a12-package
python -m tests.integration.metrology3d.offline_release --root <隔离发行根> --package .tmp/a12-package/workpiece.zip --report <独立报告目录> --port <独立端口>
```

发行测试驱动在构建机使用测试辅助；所有被验服务和 worker 来自目标包，清除外部 Python 搜索路径。正式现场只使用随包启动器、页面/API 和 A11 工具，不交付测试驱动作为运行依赖。

## 保留范围

本项不重复测十秒节拍、近 1 GB 显示索引、S2 历史稳定性或长稳。不改变当前工程配方适用范围，不把同云一致性当实体精度认证。Ubuntu 结论仅覆盖已验收 24.04 WSL x86_64 原生文件系统，不外推任意 Linux 或 Ubuntu NVIDIA。Windows 桌面 EXE 构建不属于本次 CPU 服务包验收；仍按既有独立文档交付。

## 收尾

Ruff 与 `git diff --check` 通过。本轮 Windows/Ubuntu full 服务、worker、Broker、daemon、Workflow 子进程均退出，5630/5632 无测试监听。临时发行 Python、测试数据库、资源包/原云副本、缓存和 WSL 隔离 venv 已清理，仓库 `.tmp/` 已空；原始工件、业务 5600/5601、已有 `release/` 和生产配置未修改。Ubuntu 已恢复任务前的停止状态，其他 WSL 发行版未停止。正式运行资产 libusb 与许可保留在既定本地 runtime 资产目录，不属于测试缓存。

本轮没有自动 Git 提交，也没有把隔离验证包覆盖到已有生产发行。发布人员按源目录重新装配；后续 A13 再固定全部前序修改的提交身份和组合范围。
