# 3D Metrology M1 I/O 实施与验证

日期：2026-10-22。对应[实施基线 11.2.8](3d-metrology.md#1128-最终确认的严格-io-修复路线)。

本文保留受控依赖阶段的实现与验收记录；后续内部文件/数组适配及最新 M1 状态见[输入适配实施记录](3d-metrology-m1-input.md)。

后续资产阶段将 pypcd4 固定为 `1.5.1+amvision.2`，修正不可压缩数据的输出容量，当前 wheel 与双平台保存/导出证据见[资产实施记录](3d-metrology-m1-assets.md)。本页 `+amvision.1` 结果保留为历史证据，不代表当前安装身份。

## 当前结论

M1 已开始，trimesh PLY 和 pypcd4 PCD 的受控修复、普通 wheel 构建和双平台 I/O 验证已落地。
不是完整 M1 交付：六个节点、同机数组接入、共享三维显示、持久资源和发布 profile 尚未启用。
现有后端、模型链路、LocalBuffer、Workflow 及前端没有改动，不注册空节点。
Open3D 几何与 XYZ/NumPy 路线不变；本阶段不需要安装 Open3D。

## 已复现的问题

在未修改的 trimesh 5.1.1 / pypcd4 1.5.1 隔离环境实测：

- PLY 声明一行 XYZ，正文含第四列和第二行，原版只返回首行 XYZ，未报告额外字段/记录。
- PCD binary 声明两点、正文只有一条完整记录，原版 metadata.points 为 2，数组长度为 1，仍返回对象。
- 源码核对还发现 PCD 固定 `%.10f`、压缩失败改成 binary、COUNT 展平列直接分组，以及 PLY 通用几何 writer 固定坐标 f4。相应严格接口已用独立数值/字节夹具覆盖，不把源码问题一概写成已做原版动态复现。

PCD compressed 按原 FIELDS 分组，COUNT 分量在每点内连续。
依据为 [PCL 格式说明](https://pointclouds.org/documentation/tutorials/pcd_file_format.html)；测试使用手工排列的字段字节，不用被测 writer 生成全部期望。
标量文本仍由 [NumPy loadtxt](https://numpy.org/doc/2.4/reference/generated/numpy.loadtxt.html) 解析；项目增加边界检查，不另写数值语法解析器。

## 实现与边界

| 位置 | 实现 |
| --- | --- |
| `runtimes/python_patches/trimesh/` | 原 PLY 头部 parser 严格化；公开冻结布局；严格点云类型化分块读写；明确拒绝不能表示的元素/list |
| `runtimes/python_patches/pypcd4/` | 原 MetaData/PointCloud I/O 严格化；记录与 EOF、COUNT 分组、LZF 长度、组织/姿态、精确写出 |
| `runtimes/python_patches/shared/` | NumPy 有界记录检查、取消回调和短写检查；构建进两个独立 wheel，不是新格式解析包 |
| `scripts/build_controlled_python.py` | 固定归档和原文件 SHA 校验、覆盖修改文件、正常构建、检查 wheel 内容及身份 |
| `tests/integration/controlled_io/` | 坏文件、所有标量 dtype、端序/元数据、取消、写失败、进程退出、wheel 身份和坏来源拒绝 |
| `scripts/verify_metrology_io_sample.py` | 原样本文件 SHA、完整读取、六种编码写后与源数组逐字段比对、资源观测 |

接口和复现命令见[构建材料说明](../../runtimes/python_patches/README.md)。
PLY 严格点云路径不调用 Trimesh 几何构造，不用 `_ply_raw`，不把上游通用 mesh API 当作严格入口或备用入口。
PCD header 的 COUNT/VIEWPOINT 省略值来自格式定义；重复、未知、无效或乱序指令失败，没有宽松重读。
字段类型先检查，整数始终按原类型读取；浮点特殊结果单独检查，区分合法 NaN/Inf 与溢出/下溢。
ASCII writer 使用 f32 的 9 位、f64 的 17 位有效数字，整数不先转 double。二进制保持声明字段精度。
不承诺 ASCII 保留 NaN payload 位模式；原始文件和平台无损资产的语义不变。

## 双平台验证

| 平台 | Python | 格式/生命周期集成回归 | 完整原始样本 |
| --- | --- | --- | --- |
| Windows 11 x64 | 3.12.13，独立 venv 继承已确认开发环境基础包 | 108 项通过，4.96 s | 全量读取及六编码往返通过 |
| WSL Ubuntu x64，glibc 2.39 | 3.12.3，独立 venv | 108 项通过，6.37 s | 全量读取及六编码往返通过 |

测试使用 NumPy 2.4.4、Pydantic 2.13.4、python-neo-lzf 0.3.5。
修复 wheel 的运行要求明确为 Python 3.12+，不沿用上游旧 Python 的兼容声明。
正式调用仍需使用应用指定解释器，不依赖系统 Python。

原始文件：479,677,235 字节，14,745,099 点，仅 XYZ，源属性声明 float。

原始验证记录：[Windows](evidence/metrology3d-m1-io/sample-windows.json)、[WSL Ubuntu](evidence/metrology3d-m1-io/sample-wsl.json)。记录不包含原始点云数据。

```text
源文件 SHA-256:
ff2b9e0ef2d6c45af02c4bf8d474cd82f77f86ad92bd371a4c0f71b1b90d116b
两平台完整 float32 XYZ 数组 SHA-256:
956927f058ba4a0170b1c1b93b1411b613fbe21fcbfc278ad0a7fc3cf621a1c6
```

完整原始 ASCII 输入没有被截取或预转 binary。输出覆盖 PLY ASCII/LE/BE 与 PCD ASCII/binary/binary_compressed，
每份输出都关闭后重读，再与导出前的整个源数组比较，不仅检查文件存在或同库自循环 hash。
独立小夹具另行验证 uint64 最大值、int64 最小值、double 邻接值、float32 小值、极值、最小次正规值、COUNT 和 RGBA。

| 观测 | Windows | WSL Ubuntu |
| --- | ---: | ---: |
| 全量原始 ASCII 读取 | 41.15 s | 23.52 s |
| PLY ASCII 写出、重读、比较 | 107.08 s | 91.10 s |
| PCD ASCII 写出、重读、比较 | 108.91 s | 90.22 s |
| 进程初始 RSS | 101.29 MiB | 49.96 MiB |
| 20 ms 采样观察到的 RSS 峰值 | 696.27 MiB | 647.27 MiB |
| 数组释放后 RSS | 106.96 MiB | 57.64 MiB |

这些是本机观测，不是工业节拍门禁、原生分配的精确峰值或 1 GB 全算法容量承诺。
ASCII 文本转换明显比二进制慢，不以格式降级掩盖耗时。
Windows 验收结束线程数 45，WSL 为 20，分别与独立仅 import 两个包的进程相同。
本轮没有给线程/RSS 设置未经确认的生产默认值，也没有跑 P99 或长稳测试。

完整样本运行后，审计仅补充了 PLY writer 对 big-endian float16 的拒绝及 Python 发行元数据校正；
接受的 float32/float64 读写路径未变。完整六编码运行的候选 PLY wheel 为
`d1170a3a9ce308b4dafb935860aaaa91fa53857461d2503048b62b054608aa1f`，
PCD wheel 为 `944ace706150862f9872cd65e3e01faa799c6fe499b74945f644e7d24d892a02`。
最终 wheel 内容身份和补充拒绝规则由最终双平台集成回归核对，不冒充重新跑过整套大样本。

## 交付身份

最终正常 wheel、构建身份和归档保存在本地 `runtimes/third_party/python-io/`，不提交二进制到 git。
源码构建材料、测试和文档可提交。固定 wheel SHA 另存 [wheels.lock.json](../../runtimes/python_patches/wheels.lock.json)。

| wheel | SHA-256 |
| --- | --- |
| trimesh-5.1.1+amvision.1-py3-none-any.whl | `b85fd115741ba833ea22b131b678ca8f7ab4a0b749069a6d81bd75afbcb01562` |
| pypcd4-1.5.1+amvision.1-py3-none-any.whl | `456c7b6087a8036c105561d8960ab4df54af2dd84986de0e21495f7b62e388d8` |

已核对两个受控 wheel 保留原 MIT/BSD 许可证，实际 Windows LZF wheel 包含 binding BSD-3-Clause 和 liblzf BSD 二条款/GPL 备选说明，采用 BSD 路径。
依赖完整离线镜像、Open3D 的传递依赖和 bundled release 尚未验收，不把当前 I/O 环境当作完整三维发行包。

## 审计与下一步

1. 本轮修复没有改变网络、损失、模型数值、推理运行时、Workflow 调度或现有页面。
2. 未创建解析服务、队列、常驻进程、自建 C 扩展或备用 parser；未修改系统/原 conda 环境。
3. 取消回调覆盖块边界；原生 LZF 调用不能被 Python 回调从内部抢占。叶进程终止后的文件释放已测，完整 Worker/Scope 强制停止仍在节点接入时按原框架验收。
4. writer 错误不宣称事务成功；临时对象、close、读回比较、ObjectStore 原子提交属于节点资源适配，尚未实现。
5. 完整输入最大 1 GB 约定不变。当前实测为约 480 MB 原文件；生产内存、并发和预览容量仍需显式准入，不由本次观测推导默认值。
6. 六节点实际注册之前，timeout、kill grace、解码/预览容量配置方式仍需确认；不复制其他节点的数值。资源 v2、同机数组、预览与持久引用按既有 M1 步骤接入，不重建 Workflow 或发布管理。

当前允许继续六节点的实现设计和原框架适配；不允许将未接入的三维能力在 Catalog/UI 声称可用。
M0 已收口，M1 的 I/O 基础已实现，**M1 整体仍未完成**。

收口审计：最终双平台各 108 项回归通过；修改 Python 文件 Ruff 的 E4/E7/E9/F 检查通过，
`git diff --check` 通过，4 份直接相关文档共 93 个本地链接检查通过，交付 wheel 与锁定 SHA 一致。
本轮没有启动 backend、worker、Vite 或浏览器；既有服务未停止或改动。
本轮验证进程已退出，`.tmp/m1-io/`、本轮集成测试缓存和构建检查缓存已清理；正式构建材料、wheel 和上述验证记录保留。
提交检查清理了 trimesh 构建配置的一处注释行尾空格，并为受控构建材料固定 LF。
使用相同 setuptools 后端重新构建，wheel SHA-256 与冻结产物一致；构建配置的来源摘要已同步，无需重跑数值测试。
