# 连接器开发图片与参考资源

状态：开发资源已准备并校验；连接器节点与专属 UI 仍按[实施基线](connector-inspection-2d.md)推进。资源用于 S00A–S03 的基础开发，不代表 S00B 实物计量证据已经齐全。

## 1. 已有资源与用途

本机资源根目录为 `data/development/connector-inspection/`。该目录受现有 `/data/` 忽略规则管理，不进入 Git、发行包或业务数据库。生成脚本、规格与来源清单保存在 `scripts/connector_assets/`，可重新下载、生成和校验。

| 资源 | 位置 | 可以验证什么 | 不能据此证明什么 |
| --- | --- | --- | --- |
| 厂商图纸、STEP、目录图 | `sources/wuerth/` | 名义尺寸、公差的来源；几何结构参考 | 某个实物的实际尺寸、现场测量准确度 |
| 两张公开实拍照片 | `sources/commons/` | 真实材质、视角、图像载入及显示交互 | 与厂商图纸是同一型号；PIN 的真实毫米尺寸 |
| 44 张连接器合成图 | `synthetic-v1/images/` | 定位、身份关联、边缘/尺寸算法、正常与异常分支 | 现场反光、光学畸变、实际零件加工偏差的完整分布 |
| 12 张标定图 | `synthetic-v1/calibration/` | 棋盘角点、已知理想内参求解、投影与坐标转换 | 真实镜头畸变与物理测量不确定度 |
| 每张图的几何真值 | `synthetic-v1/truth/`；标定 JSON 与图片同目录 | 独立于待测节点的几何期望、单位、PIN 身份、无效结果 | 独立计量仪器的实物测量报告 |
| 两个可编辑场景 | `synthetic-v1/scenes/` | 在 Blender 中检查、修改模型与渲染条件 | 已安装的 Workflow 或平台资源包 |
| 参考图与布局定义 | `synthetic-v1/references/` | 原始参考图、模板 ROI、锚点及名义 PIN 表 | 已冻结的产品公开接口；它们只是开发夹具格式 |

`synthetic-v1/gallery.html` 是离线图集，可在本地浏览器打开；每张图均链接到原始 PNG 与真值 JSON。`manifest.json` 记录图像/真值 SHA-256、生成器和规格摘要、Blender 版本及样本划分。`validation.json` 保存最近一次校验结果。

本次检索找到实拍照片和公开图纸，但没有取得“同一实物原图 + 对应图纸 + 公差 + 逐件独立参考量值”的完整公开样本包。基础开发采用尺寸受控的 Blender 参数化模型；AI 生成的视觉外观不作为毫米几何真值来源。

## 2. 网络来源和尺寸依据

### 2.1 厂商参考

Würth Elektronik **61301011121**，单排 10 PIN、2.54 mm 间距。参考[官方产品资料页](https://www.we-online.com/en/components/icref/texas-instruments/MSP432P401R-TIDA-01439-Other)中的[图纸 PDF](https://www.we-online.com/components/products/datasheet/61301011121.pdf)与 [STEP 文件](https://www.we-online.com/components/products/download/Download_STP_61301011121%20%28rev1%29.stp)。图纸版本为 003.001，日期为 2025-07-22。

以下字段按图纸第 1 页可见标注录入 `spec.json`，单位均为 mm：

| 尺寸 | 名义值 | 图纸显式公差 |
| --- | ---: | ---: |
| 相邻中心距 | 2.54 | ±0.05 |
| PIN 方形截面宽度 | 0.64 | ±0.15 |
| 壳体总长 | 25.40 | ±0.35 |
| 配合端长度 | 6.00 | ±0.20 |
| 焊接端长度 | 3.00 | ±0.20 |
| 首末 PIN 中心跨距 | 22.86 | ±0.15 |

PCB 推荐孔位图中的 22.8 不等于零件首末 PIN 的 22.86，不能混用。上述摘录不代替完整图纸中的材料、镀层、其他尺寸及技术要求。

厂商资料保留原文件供本地参考，没有认定其允许作为项目自有资产再分发。生成器不导入厂商 STEP，而是按公开名义尺寸自行建立简化几何。目录 JPEG 只有 132×132，是产品示意图，不作为相机原图使用。

### 2.2 实拍照片

| 文件 | 来源 | 公开原始分辨率 |
| --- | --- | --- |
| `commons/36-pin-header.jpg` | [36 Pin Header](https://commons.wikimedia.org/wiki/File:36_Pin_Header.jpg) | 2808×1872 |
| `commons/16-pin-header.jpg` | [16 Pin Header](https://commons.wikimedia.org/wiki/File:16_Pin_Header.jpg) | 1395×930 |

作者均为 **oomlout**，来源页面标注 [CC BY-SA 2.0](https://creativecommons.org/licenses/by-sa/2.0/)。本地下载保持原文件不变；若后续分发或改编，保留作者、来源、许可与修改说明，并按该许可处理。这里的“原始分辨率”指网站公开的原尺寸 JPEG，不是传感器 RAW。

完整 URL、文件大小、固定 SHA-256 和权利说明记录于 `scripts/connector_assets/sources.json`，下载后同步到 `sources/sources.json`。下载器对来源更新或本地文件变化明确失败，不静默覆盖已核对文件。

## 3. 合成样本规格

### 3.1 工件、相机与坐标

所有图像为 **1280×800、8-bit RGB PNG**，没有绘制文字、尺寸线或标签。测量母图使用无损格式；产品页面 JPEG 显示策略保持原有边界。

- `single10_front`：单排 10 PIN 正视图，间距 2.54、宽度 0.64、壳体长 25.4；配合端、焊接端和壳体高度采用图纸名义尺寸。宽度定义为局部 `y=5.54` 截面沿 X 的两边距离，测量平面 `z=0.32`。
- `dual08_top`：自行定义的双排、每排 8 PIN 顶视夹具，行间距和列间距均为 2.54、宽度 0.64；测量平面为 PIN 顶端 `z=6`。它不是该厂商零件的双排型号声明。
- 壳体白色方向标记是开发夹具人工加入的定位特征，不能假定真实零件也有。金属表面、倒角和壳体形状是简化模型；PIN 测量边不加倒角。
- 正交图视野宽 38 mm，比例约 33.6842 px/mm。透视图和标定图使用 50 mm 焦距、36 mm 水平传感器宽度、80 mm 相机位置；只模拟理想针孔相机，畸变系数全为零。
- 局部和世界几何单位为 mm。图像坐标以左上角像素中心为 `(0,0)`，X 向右、Y 向下。PIN 按行号、列号固定为 `R1P01` 等，缺针不移动后续编号。
- `world_from_part_mm` 显式保存工件到世界变换；`image_from_measurement_plane` 与逆矩阵仅适用于指定平面，不能直接套用到不同高度的壳体或其他表面。

`two_parts` 仅测试多工件定位歧义，工件经过统一缩放；其 `measurements_valid=false`。图中局部名义数据不能用于该样本的单工件尺寸验收。

### 3.2 样本划分与边界

每个工件族各有 22 张图，两个工件族合计 44 张；另有 12 张标定图。

| 划分 | 张数 | 用途 |
| --- | ---: | --- |
| reference | 2 | 建立模板、布局和首次测量 |
| development | 16 | 调试位置、角度、缺针、尺寸偏差、设计留空及透视 |
| validation | 26 | 保留的另一组角度、缺首/中/末针、超差、越界与歧义分支 |
| calibration | 12 | 9×6 内角点、2 mm 棋盘格、多位置和倾斜姿态 |

`validation` 是确定性工程回归集，不是随机真实分布的独立统计验收集。标定图包含倾斜与不同距离；连接器工件图只改变平面内姿态，未覆盖任意三维倾斜工件。

| 条件 | 预期 |
| --- | --- |
| `reference / translate / rotate_pos / rotate_neg` | OK，PIN 身份与局部尺寸不随位姿改变 |
| `missing_first / missing_middle / missing_last` | NG；缺失位置没有实际测量值 |
| `offset / narrow / wide` | NG；分别施加 0.25 mm 偏移、0.45 / 0.84 mm 宽度 |
| `width_inside_limit / width_on_limit / width_outside_limit` | 0.68 / 0.69 / 0.70 mm，依次 OK / OK / NG |
| `designed_empty / empty_occupied / extra_pin` | 明确设计留空 OK；留空处占用或额外 PIN 为 NG |
| `dark / bright / perspective` | 几何和规则预期 OK；用于验证成像变化下能否获得有效观测 |
| `no_part / two_parts / cropped` | invalid，不能沿用上次姿态或给出有效尺寸 |

工程判定采用宽度 `[0.59,0.69]`、相邻中心距 `[2.49,2.59]`、最大偏移 `0.10`，边界包含在内。这些规则由项目自行定义用于测试，不是厂商公差判退规则。例如 0.70 mm 在此工程规则中 NG，但不能据此认定厂商零件不合格。

`expected.state` 是几何与规则的预期；暗图等成像条件下，待开发算法能否检测成功必须实际测试。工程图片含 Cycles 采样噪声，尚未建模真实传感器噪声、畸变、失焦、运动模糊、严重反光或缺陷纹理分布。

### 3.3 真值的使用方式

每张连接器图片包含以下配套字段：

- `camera`：图像规格、像素中心约定、相机模型、比例/焦距和畸变参数。
- `pins`：固定身份、名义/实际存在状态、局部和图像坐标、宽度以及测量端点。
- `extra_observations`：名义布局之外的工件观测。
- `expected.checks`：各 PIN 存在性、有效宽度、偏移、相邻中心距以及额外目标规则的解析期望。
- 缺 PIN 的实际位置与宽度为 `null`；依赖缺失 PIN 的间距无效，不能补零；设计留空不桥接成一个名义相邻间距。

先读取图像和配方输入执行待开发节点，再将输出与真值比较。不能把真值中的实际位置作为定位输入、把实际宽度作为测量输入，或者在测试时借此绕过缺失检查。参考图中的 Layout/ROI 可以作为显式配方配置。

“独立”指真值来自建模几何，校验器另外用 NumPy 解析投影和 OpenCV 实际像素检测交叉核对，不调用未来的定位/测量节点。它不是物理量值溯源：几何边与像素强度边存在抗锯齿、光照和阈值偏差，必须分别制定算法误差阈值；不能把投影公式一致性误差当成计量精度。

## 4. 生成和校验

Blender 只用于离线开发素材生成，不进入 backend、Preview Worker、Runtime、Trigger、SDK 或发行包依赖。生成器本次使用本机 Blender 5.2.1 LTS、Cycles CPU、8 线程与每像素 8 次采样，固定随机种子。不同 Blender/渲染库版本可能产生不同像素 hash。

仓库根目录执行：

```powershell
conda activate amvision
python scripts/connector_assets/fetch_sources.py

# blender 为本机 Blender 可执行文件；不在 PATH 时改用其实际绝对路径。
# 输出目录必须为空；复现到新目录可保留已有样本。
blender --background --factory-startup --python-exit-code 1 --python scripts/connector_assets/generate_blender.py -- --output data/development/connector-inspection/synthetic-v1-rebuild

python scripts/connector_assets/validate.py data/development/connector-inspection/synthetic-v1-rebuild
python -m ruff check scripts/connector_assets
```

开发 Python 使用 conda `amvision`，校验需要当前环境已有的 OpenCV 与 NumPy；Blender 脚本由 Blender 自带 Python 执行，不需要为服务安装 `bpy`。完整重建在本机约 5 分钟，这只是离线渲染耗时，与节点推理性能无关。首次核对可加 `--smoke` 只生成一个参考样本；它不能替代完整数据集验证。

生成失败时不写完整 `manifest.json`，后续校验会失败。生成器拒绝向非空目录覆盖；下载器核对固定摘要；校验器验证路径不越界、文件摘要、PNG 解码、固定 PIN 身份、状态分支、独立投影、参考图实际边宽和棋盘求解。校验通过才更新图集和 `validation.json`，当前命令退出码才是该次校验结果，不能把上一次报告当成修改后仍然通过的证据。

## 5. 当前校验结果

本次完整资源校验通过，使用 OpenCV 4.13.0：

| 检查 | 结果与边界 |
| --- | --- |
| 56 张图片及对应 JSON | 摘要、解码、规格与预期状态通过 |
| Blender 投影与独立 NumPy/H 计算 | 最大差异约 0.000152 px；仅验证坐标一致性 |
| 两张参考图中实际金属像素截面宽度 | 最大差异约 1.4422 px；当前粗阈值检查上限 2 px，不作为亚像素精度验收 |
| 标定图角点 | 12/12 检出；对真值最大差异约 0.1912 px |
| 已知零畸变下重新求解内参 | 重投影 RMS 约 0.0476 px；焦距相对偏差最大约 0.0452%；主点偏差约 0.5335 px |

同时人工查看了厂商尺寸页、实拍照片、正常/缺针图、双排透视图及棋盘图。没有运行尚未实现的连接器节点，也没有以这些结果宣布真实工件准确度或长期生产稳定性通过。

## 6. 接下来的开发接入

1. S01 使用这些图与 JSON 固定 PIN 身份、观察/测量有效性、单位和坐标契约；保留工程夹具格式与产品公开 Schema 的区分。
2. S02 先用 `single10_front__reference`、平移、旋转和宽度变化验证通用边缘采样、拟合与测量，再接入真实照片检查成像适用范围。
3. S03 完成单排宽度/间距/缺针最小闭环；用首、中、末缺针和设计留空样本确认编号不漂移、无效值不变成 OK。
4. 标定、模板与专属 UI 开发读取明确的参考图/ROI/真值；到 S04 才按平台正式资源引用与发布机制安装，不能把这些磁盘路径硬编码进节点。
5. 进入真实产品调参和现场验收前，另补同一实际型号的原始拍摄图、测量定义、真实公差、逐件参考量值及重复上料数据。当前资源足以开始基础代码开发，不需要因此等待真实资料全部齐备。
