---
name: git-commit
description: 'Execute git commit with Conventional Commits analysis, intelligent staging, and message generation. Use when user asks to commit changes, create a git commit, generate a commit message, or mentions /commit. Supports auto-detecting type and scope from diff, staged-first analysis, optional type/scope overrides, and intelligent file staging. 提交信息优先使用中文，专有名词保持英文。'
argument-hint: '可选：说明是否只看 staged changes、指定 type/scope、是否需要正文'
user-invocable: true
---

# Git Commit Skill

## 适用场景

在以下场景使用本技能：

- 用户要求提交当前改动
- 用户要求生成 git commit message
- 用户要求按 Conventional Commits 规范提交
- 用户提到 `/commit`
- 用户希望先分析 diff，再决定 type、scope 和 description

## 目标

基于当前 Git 变更生成标准化、语义化的提交信息，并在需要时完成暂存与提交。

提交信息要求：

- 优先使用中文
- 专有名词、技术名词、框架名、协议名、文件格式名保持英文
- 遵循 Conventional Commits 结构
- 描述简洁、准确、可读
- 支持规范标题模式与自然摘要模式

## 输出模式

### 1. 默认模式：标题 + 一段摘要

- 第一行输出 Conventional Commits 标题
- 第二段输出一段中文摘要，用自然语言概括本次改动的范围、重点和结果
- 摘要默认使用 2 到 4 句，不展开无关背景，不堆砌文件清单
- 适用于大多数提交信息生成场景，兼顾规范性与可读性

### 2. 自然摘要模式

- 用于生成更接近 Visual Studio 风格的中文概述
- 仍保留 Conventional Commits 标题，但摘要可更完整地概括改动主题、分层、补充内容和整体效果
- 适合文档重构、跨目录整理、配置与约束补全等改动较多的场景
- 若用户明确要求“更自然”“更像 Visual Studio 生成结果”“中文概述风格”，优先使用此模式

### 3. 精简标题模式

- 仅输出单行 Conventional Commits 标题
- 仅在用户明确要求“只要标题”“只要一行 commit message”时使用

## Conventional Commit 格式

```text
<type>[optional scope]: <description>

[optional body]

[optional footer(s)]
```

## Commit Type 选择

| Type | 用途 |
| --- | --- |
| feat | 新功能 |
| fix | 缺陷修复 |
| docs | 仅文档变更 |
| style | 格式或样式调整，不改行为 |
| refactor | 重构，不新增功能也不修复缺陷 |
| perf | 性能优化 |
| test | 测试新增或更新 |
| build | 构建系统、依赖、打包相关变更 |
| ci | CI 或自动化流程变更 |
| chore | 维护性杂项变更 |
| revert | 回滚提交 |

## 中文提交信息规则

- 类型与 scope 保持 Conventional Commits 风格，例如 `docs(architecture): 补充数据集导入规范`
- description 优先中文，但专有名词保留英文，例如 `docs: 补充 JSON Schema 草案`
- 使用现在时、祈使式或中性描述，不写口语化表达
- description 默认控制在 72 个字符以内
- 如果用户没有明确要求只输出单行标题，默认生成“标题 + 一段摘要”
- 默认摘要应聚焦改动主题、主要补充内容和整体结果，不重复标题原文
- 自然摘要模式下可适度放宽摘要长度，但仍应保持紧凑、可读和便于直接作为提交说明使用

## 工作流程

### 1. 读取 Git 状态

优先检查 staged changes。

建议命令：

```bash
git status --porcelain
git diff --staged
git diff
```

规则：

- 如果存在 staged changes，优先基于 staged diff 生成提交信息
- 如果没有 staged changes，再基于 working tree diff 分析
- 如果 staged 与 unstaged 同时存在，除非用户明确要求混合提交，否则默认只围绕 staged changes 生成和提交

### 2. 判断是否需要暂存

如果没有 staged changes，或者用户明确要求重新分组提交，可以执行智能暂存。

可选方式：

- 按文件显式暂存
- 按模块或模式暂存
- 必要时使用交互式暂存

示例：

```bash
git add path/to/file1 path/to/file2
git add docs/architecture/*.md
git add -p
```

安全约束：

- 不提交 secrets、私钥、凭证或本地敏感配置
- 不擅自扩大暂存范围，把无关改动混入同一提交
- 若改动明显跨多个主题，应建议拆分提交，而不是硬拼一个大提交

### 3. 分析变更并生成提交信息

需要从 diff 中判断：

- type：变更性质
- scope：受影响模块或主题
- description：一句话说明改动内容
- summary：一段中文摘要，说明本次改动补充了什么、重构了什么、整体带来了什么变化

scope 建议：

- 优先使用仓库中真实存在的模块、目录或主题名
- 文档改动可用 `architecture`、`deployment`、`plugins`、`api` 等
- 前端改动可用 `web-ui`、`frontend`
- 后端改动可用 `backend-service`、`workers`、`models` 等
- 如果没有稳定 scope，可省略 scope

生成规则：

- 文档类改动优先使用 `docs`
- 仅命名、格式、注释整理但不改行为，优先 `style` 或 `refactor`
- 运行时、打包、依赖、脚本调整优先 `build` 或 `chore`
- 若存在破坏性变更，使用 `!` 或 `BREAKING CHANGE` footer
- 默认同时生成标题与摘要；仅在用户明确要求时退化为单行标题
- 若改动跨多个文档主题但仍属于同一主线，可在摘要中概括“重构与补全”“完善分层与导航”“补充约束与规范”等整体动作
- 自然摘要模式下，摘要应更像发布说明中的短段落，而不是按文件逐条罗列

### 4. 执行提交

单行提交：

```bash
git commit -m "<type>[scope]: <description>"
```

多行提交：

```bash
git commit -m "$(cat <<'EOF'
<type>[scope]: <description>

<optional body>

<optional footer>
EOF
)"
```

## 最佳实践

- 一个 commit 只表达一个逻辑变更
- staged changes 优先，避免把未确认改动顺手一起提交
- 文档、架构、配置、脚本、代码实现尽量不要混成同一提交
- 若用户没有要求自动提交，可以先给出候选 commit message 再等待确认
- issue 引用、`Closes #123`、`Refs #456` 等 footer 只在用户明确需要时添加
- 默认摘要要比标题提供更多信息，但不要扩展成完整变更日志

## Git 安全协议

- 不修改 git config
- 不执行 destructive git 命令，例如 `--force`、`reset --hard`
- 不绕过 hooks，例如 `--no-verify`，除非用户明确要求
- 不强推到 main 或 master
- 若 commit 因 hooks 失败，优先修复问题后重新提交，不默认 amend

## 输出约定

### 只生成提交信息时

- 默认输出两部分：第一行标题，空一行后输出一段摘要
- 不附加额外解释、引号或代码块
- 如果用户明确要求自然摘要风格，则摘要可写得更接近 Visual Studio 风格的中文概述
- 如果用户明确要求只要标题，则仅输出单行 commit message

### 需要执行提交时

- 先说明将基于 staged 还是 unstaged 变更
- 如果需要重新暂存，先说明暂存范围
- 提交完成后返回最终标题、摘要和是否成功

## 示例

- `docs(architecture): 补充数据集导入规范与导出映射`
- `docs: 新增 commit message Prompt 与 Skill 配置`
- `build(runtime): 调整 bundled Python 发布约定`
- `refactor(backend-service): 收敛任务状态回写边界`

### 标题 + 摘要示例

`docs: 重构与补全文档体系`

本次提交系统整理了 docs 目录下的架构、数据、插件和部署文档，补充了文档分层、入口导航和推荐阅读路径，同时完善了 AGENTS.md、agent 配置与 git-commit Skill 约束，整体提升了文档体系的可维护性与可追溯性。

### 自然摘要模式示例

`docs: 完善核心文档分层与导航`

本次提交重构并补全了 docs 目录下的核心文档，建立了更清晰的文档分层、入口导航和推荐阅读路径。新增文档整改路线图、专题架构文档与 ADR 记录，并同步完善 AGENTS.md、各 agent 角色配置以及 git-commit Skill，整体提升了项目文档体系的分工、可读性和长期维护边界。