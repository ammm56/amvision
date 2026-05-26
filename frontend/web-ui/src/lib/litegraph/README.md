# LiteGraph 本地源码说明

本目录保存 workflow editor 画布使用的 LiteGraph 源码快照，按 vendored source 方式纳入 `frontend/web-ui`。

## 来源

- 上游项目：Comfy-Org/litegraph.js 与 ComfyUI Frontend `src/lib/litegraph`
- 上游仓库：https://github.com/Comfy-Org/litegraph.js
- 导入日期：2026-05-19

## License

LiteGraph 使用 MIT license。复制、修改或随发布包分发这些文件时，保留本目录下的 `LICENSE` 文件。

## 本地修改

- 内部源码 import 从 `@/` 改为 `@litegraph/`。
- `@litegraph/*` 在 web UI 的 TypeScript 与 Vite 配置中映射到 `src/lib/litegraph/src/*`。
- alias 修改仅用于避免与本项目业务源码的 `@/*` alias 冲突，不改变 LiteGraph 功能行为。
- 少量源码文件加入 `// @ts-nocheck`，原因是当前快照与 web UI 的严格 `noUnused*` TypeScript 设置不完全一致。

## 项目边界

业务代码不直接 import LiteGraph 深层源码文件。workflow editor 通过 `src/workflows/workflow-editor/canvas/graph-engine/` 下的 adapter 使用 LiteGraph，后端 `WorkflowGraphTemplate` 与 `FlowApplication` 仍是正式保存格式。

## 升级记录要求

后续更新 LiteGraph 快照时，需要同步记录来源、上游 commit、license 状态和本地补丁范围，并重新执行 `npm run typecheck` 与 `npm run build`。