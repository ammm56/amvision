# 参考资料

本目录保存可查询的能力表、格式和参数规则。参考文档回答“支持什么、字段如何组织”，不解释系统为什么这样分层，也不记录某次测试结果。

## 数据集

[数据格式索引](datasets/README.md)覆盖导入、导出、分类、检测、实例分割、姿态和 OBB。公开 API 调用见 [DatasetImport](../api/datasets-imports.md) 与 [DatasetExport](../api/datasets-exports.md)。

## 模型

[模型参考索引](models/README.md)覆盖支持矩阵、命名、输入尺寸、训练参数和检测规则。训练、转换、部署的模块关系见 [模型工作流边界](../architecture/models/workflow-boundaries.md)。

## 工业视觉资料

[ViSCO 二维连接器检查资料与功能核对](vision/visco-connector-inspection.md)：官方资料、可确认的配置方式及证据限制。它是外部产品参考，不表示 AMVision 已实现同等功能；本项目设计见关联提案与实施基线。

[工业二维检查资料与能力边界](vision/industrial-2d-measurement.md)：Cognex、MVTec、光学与产品规范资料，区分通用视觉、行业复用和具体产品配置。

## 维护规则

- 支持状态必须同时有注册表、实现和自动化测试证据。
- 示例路径与数据只说明结构，不代表仓库自带客户数据。
- 格式或参数变化必须同步解析器、导入导出测试和公开 API 文档。
