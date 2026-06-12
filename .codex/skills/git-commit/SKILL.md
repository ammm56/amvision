---
name: git-commit
description: Execute git commit with Conventional Commits analysis, intelligent staging, and message generation. Use when the user asks to commit changes, create a git commit, generate a commit message, mentions /commit, or wants staged-first diff analysis. Commit messages should prioritize Chinese while keeping proper nouns, protocol names, frameworks, and file formats in English.
---

# Git Commit

## Overview

为当前 Git 改动生成规范的 Conventional Commits 提交信息，并在需要时完成暂存与提交。

提交信息默认优先使用中文，专有名词、技术名词、框架名、协议名、文件格式名保持 English。

## 适用场景

在以下场景使用本技能：

- 用户要求提交当前改动
- 用户要求生成 commit message
- 用户要求按 Conventional Commits 规范提交
- 用户提到 `/commit`
- 用户希望先分析 diff，再决定 type、scope 和 description

## 默认规则

- 先看 staged changes；如果已有 staged，默认只围绕 staged 内容生成和提交
- 如果 staged 和 unstaged 同时存在，除非用户明确要求混合提交，否则不把 unstaged 顺手带进去
- 如果没有 staged changes，再基于 working tree diff 分析，并按主题做最小范围暂存
- 不提交 secrets、私钥、凭证或本地敏感配置
- 不把明显跨多个主题的改动硬拼成一个 commit；必要时建议拆分提交

## 输出模式

### 默认模式

输出一行 Conventional Commits 标题，空一行后再输出一段中文摘要。

- 标题：简洁说明本次提交的核心动作
- 摘要：用 2 到 4 句概括改动范围、重点和结果

### 自然摘要模式

当用户明确要求“更自然”“更像 Visual Studio 生成结果”“中文概述风格”时：

- 保留 Conventional Commits 标题
- 摘要可以更完整，但仍保持紧凑
- 适合跨目录整理、文档重构、配置收口等场景

### 精简标题模式

仅在用户明确要求“只要标题”“只要一行 commit message”时使用。

## Conventional Commits 规则

格式：

`<type>[optional scope]: <description>`

常用 type：

- `feat`：新功能
- `fix`：缺陷修复
- `docs`：仅文档变更
- `style`：格式或样式调整，不改行为
- `refactor`：重构，不新增功能也不修复缺陷
- `perf`：性能优化
- `test`：测试新增或更新
- `build`：构建系统、依赖、打包相关变更
- `ci`：CI 或自动化流程变更
- `chore`：维护性杂项变更
- `revert`：回滚提交

scope 规则：

- 优先使用仓库中真实存在的模块、目录或主题名
- 文档类优先考虑 `architecture`、`deployment`、`api`
- 前端类优先考虑 `web-ui`、`frontend`
- 后端类优先考虑 `backend-service`、`workers`、`models`
- 如果没有稳定 scope，可以省略

## 中文提交信息规则

- 标题中的 type 和 scope 保持 Conventional Commits 风格
- description 优先使用中文
- 专有名词保留英文，例如 `JSON Schema`、`FastAPI`、`OpenCV`、`TensorRT`
- 用中性、直接的描述，不写口语化表达
- description 默认尽量控制在 72 个字符以内
- 除非用户明确要求单行标题，否则默认生成“标题 + 摘要”

## 工作流程

### 1. 读取 Git 状态

优先检查：

- `git status --porcelain`
- `git diff --staged`
- `git diff`

判断规则：

- 如果存在 staged changes，优先基于 staged diff 生成提交信息
- 如果没有 staged changes，再基于 working tree diff 分析
- 如果 staged 与 unstaged 同时存在，默认只围绕 staged changes 处理

### 2. 判断是否需要暂存

如果没有 staged changes，或者用户明确要求重新分组提交，可以执行智能暂存。

可选方式：

- 按文件显式暂存
- 按模块或模式暂存
- 必要时使用 `git add -p`

暂存时遵守：

- 不扩大暂存范围
- 不把无关改动混进同一提交
- 如果改动主题明显不同，建议拆分提交

### 3. 分析变更并生成提交信息

需要判断：

- `type`：变更性质
- `scope`：受影响模块或主题
- `description`：一句话说明改动内容
- `summary`：一段中文摘要，说明补充了什么、重构了什么、整体结果是什么

判断规则：

- 文档类改动优先使用 `docs`
- 仅命名、格式、注释整理但不改行为，优先 `style` 或 `refactor`
- 运行时、打包、依赖、脚本调整优先 `build` 或 `chore`
- 若存在破坏性变更，使用 `!` 或 `BREAKING CHANGE`

### 4. 执行提交

如果用户要求直接提交：

- 先说明基于 staged 还是 unstaged 变更
- 如果需要重新暂存，先说明暂存范围
- 执行 `git commit`
- 返回最终标题、摘要和是否成功

如果用户只要求生成提交信息：

- 只输出候选标题和摘要
- 不自动执行提交

## 安全规则

- 不修改 `git config`
- 不执行 destructive git 命令，例如 `reset --hard`
- 不默认使用 `--no-verify`
- 不强推到 `main` 或 `master`
- 如果 hooks 失败，优先修复问题后重新提交，不默认 amend

## 输出约定

### 只生成提交信息

默认输出：

`<type>[scope]: <description>`

然后空一行，再输出一段中文摘要。

不要附加引号、代码块或多余解释。

### 需要执行提交

输出内容包括：

- 本次基于 staged 还是 unstaged 变更
- 是否做了暂存调整
- 最终提交标题
- 提交是否成功

## 示例

- `docs(api): 收整 Postman 全链路调试说明`
- `build(runtime): 调整 bundled Python 发布约定`
- `refactor(backend-service): 收平 deployment 路由命名边界`
- `fix(web-ui): 修正视频预览分支的响应体渲染`
