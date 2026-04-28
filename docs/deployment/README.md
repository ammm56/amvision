# 部署文档目录

## 文档目的

本目录用于存放开发环境、运行时、安装、打包、发布和排障相关文档。

## 当前文档

- [docs/deployment/bundled-python-deployment.md](bundled-python-deployment.md)：同目录 Python 运行时的安装、升级、回滚和验收方案

## 建议内容

- conda 开发环境定义与复现方式
- 同目录 Python 运行时结构与启动方式
- standalone、workstation、edge 三类发布结构
- 安装检查、升级、回滚和排障说明

## 存放规则

- 部署步骤与架构背景分开书写
- 能执行的命令、目录和验证步骤优先直接放入本目录
- 额外系统依赖必须单独列出用途、版本边界和验证方法