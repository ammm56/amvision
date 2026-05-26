# 架构决策记录目录

## 文档目的

本目录用于存放关键架构决策记录，回答“为什么采用这个方案，而不是其他方案”。

## 当前文档

- [docs/decisions/ADR-0001-modular-monolith-with-workers.md](ADR-0001-modular-monolith-with-workers.md)：固定模块化单体 + 独立 worker 的总体形态
- [docs/decisions/ADR-0002-bundled-python-runtime.md](ADR-0002-bundled-python-runtime.md)：固定开发 conda / 发布 bundled Python 的运行时策略
- [docs/decisions/ADR-0003-node-pack-extension-model.md](ADR-0003-node-pack-extension-model.md)：固定节点扩展优先和 ComfyUI 风格能力模型

## 适合存放的内容

- 是否拆分微服务与 worker 的取舍
- 是否采用本地对象存储、本地队列和本地缓存的取舍
- 前端主栈选择 Vue 3 的取舍
- 部署阶段采用同目录 Python 运行时的取舍

## 建议命名方式

- ADR-0001-brief-title.md
- ADR-0002-brief-title.md

## 建议结构

- 背景
- 决策
- 备选方案
- 影响
- 后续动作

## 存放规则

- 决策记录不替代长期参考文档
- 当某项决策已经稳定为长期约束时，应同步更新 AGENTS.md 或对应专题文档