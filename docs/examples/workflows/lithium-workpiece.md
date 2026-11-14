# 锂电工件三维测量配方

本配方使用现有三维测量节点及平台判定/保存节点，覆盖十二钢片 H/Z/L/W 与 S1/S2 直径，共 50 项。没有专用工件算法、测试 handler、内置参考答案或额外调度器。

2026-11-14 已在本机默认项目创建并发布 `lithium-workpiece-file-full`，完整 PLY 经应用模式执行得到 50 项有效结果。入口、逐项手工报告对照和双平台覆盖见[实际工件 App 交付记录](../../development/3d-metrology-workpiece-app.md)。本机运行身份不写入通用配方，其他环境仍按下文导入与发布。

## 可直接使用的文档

冻结图为 [template](lithium_workpiece.template.json) 与 [application](lithium_workpiece.application.json)。导出工具不依赖测试目录：

```powershell
conda activate amvision
python -m scripts.metrology_workpiece data/development/metrology-workpiece/file.workflow.json
python -m scripts.metrology_workpiece data/development/metrology-workpiece/array.workflow.json --input-kind array --view numeric
```

在既有图编辑器空白画布右键选择“导入工作流”，导入生成的 `amvision.workflow-app-document.v1`，保存到当前项目，审核节点参数后发布；创建 Runtime，启动，在应用模式选择完整 PLY 并运行。页面可展开 50 项判定表、完整工件三维显示及测量证据。每次结果由 Save JSON 写入该应用的 Run 目录，返回体 `meta.saved_output` 给出 ObjectStore 引用。

正式装配后，生成器及上述配方位于发行目录 `app/`。在发行根运行 `./python/python.exe launchers/client/invoke_point_cloud.py recipe -- data/recipes/lithium.workflow.json`，无需开发源码或 `tests/`。四种文件/数组、完整显示/仅数值组合共用同一配方；完整调用路径见[同机工具说明](../../../runtimes/clients/point_cloud/README.md#发行目录调用)。该文档使用动态输入，不包含完整原始点云；已有 A10 配方携资源 ZIP 用于固定资源依赖搬运，不会自动把运行时上传文件加入包中。

文件配方默认为现有完整 ASCII PLY 样本及 float32 坐标映射。PCD/XYZ 使用同一 Read Cloud 节点，但必须显式改读入格式与字段映射后发布，不能把改后缀当格式转换。配方不包含原始点云，也不自动保存完整原云。

数组配方删去文件读取节点，将 `point-cloud-ref.v1` 直接接到 Filter Valid。创建 local-shared-memory Trigger，输入 `cloud` 映射 `payload.cloud`，输出选择 `body`。Windows .NET 使用既有点云 writer 接口；同机 Python 可使用[运行时调用工具](../../../runtimes/clients/point_cloud/README.md)。两入口使用相同 ROI、拟合及测量参数。

`--view full` 保留完整证据显示；`--view numeric` 显式去掉三维显示分支，但保留全部计算、判定、表格与保存。不是失败时自动降级，不改变点数或量值。默认调试捕获仍关闭。

## 测量定义

| 量值 | 定义 |
| --- | --- |
| H | 本次基体面到钢片顶面的同线距离，方向为台面正法向 |
| Z | 本次台面到钢片顶面的同线距离，显式有限基准延伸 |
| L/W | 已选实际距离分区的可见投影包络及稳健剖面跨度，不自动回退到严格闭合等高截线 |
| S1.D | 完整支持片段的圆模型直径 |
| S2.D | 显式部分实测圆弧估计直径，保留实测支持和缺弧证据 |

基准使用五 ROI 并集，本次 pose 与固定 U/V 查询；当前适用范围为已验证固定装夹。单位 mm。原始行号、目标归属、方法参数和运行质量门禁保持既有冻结定义。

## 本工件工程判定

用户授权开发阶段确定该工件参数后，采用以下固定名义量与对称工程限值。名义量根据手工报告的尺寸族整理；限值是本次工程配方配置，**不是图纸公差、ISO 公差表抄值或独立量具真值**。通用标准不能为未知工件凭空规定名义尺寸。后续有图纸时修改 Limits 并审核重发，不改测量算法。

| 类型 | 名义量 mm | 允许偏差 mm | 下限 / 上限 mm |
| --- | ---: | ---: | --- |
| H | 1.20 | 0.15 | 1.05 / 1.35 |
| Z | 1.65 | 0.25 | 1.40 / 1.90 |
| L | 8.00 | 0.30 | 7.70 / 8.30 |
| W | 7.00 | 0.20 | 6.80 / 7.20 |
| D | 20.00 | 0.30 | 19.70 / 20.30 |

50 项全部必检。范围端点包含在合格区间；缺项、无效、单位不符为 `invalid`，有效越限为 `ng`，全部满足为 `ok`。同次出现 NG/INVALID 时汇总 INVALID，保留每项 NG。只有 `state=ok` 放行，不能把 `passed=false` 一律解释为 NG。

S2 当前方法已获工程使用确认，原 0.03 mm 重采样诊断不再作为本配方交付或主流程实施的阻塞，不重复跑该诊断。既有测量有效性仍按真实数据计算，不覆盖 valid、reason 或任何量值。独立实体精度没有证据时不声明计量认证，不妨碍软件工程配方使用。

## 结果与运行边界

HTTP 默认 App Result 为 `results.body`；同机 Trigger 为 `response_payload.results.body`。其中 `data` 为 `amvision.result-record.v1`，包含 `state/passed`、50 项 `metrics.items`、完整 `conditions` 和工程规则来源 `metadata`；`meta.saved_output` 为已保存 JSON 的位置。显示采样不参与计算。

本机启用配置沿用活跃数组 1 GiB、算法工作预算 4 GiB、显示最多 100 万点、节点超时 180 秒、停止宽限 2 秒。示例显示 50 万点。安全超时不等于节拍承诺；文件传输/ASCII 解析、完整三维证据与数值测量应分别计时，不能将含显示整帧耗时冒充纯检测时间。

当前十秒目标仍按原正式口径，不通过把目标改宽来认定达标。本次主流程验收不重复性能试验；先前 Windows 最差 10.094 秒、Ubuntu 最差 8.110 秒的记录保留，但不是本次含显示完整图的节拍证明。

源码仓库验收记录位于 `docs/development/3d-metrology-mainflow.md`；这些开发审计记录和现场输入不随工具自动复制到发行包。
