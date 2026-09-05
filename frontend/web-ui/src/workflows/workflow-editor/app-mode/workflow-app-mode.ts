import type { FlowApplication, NodeDefinition, WorkflowGraphNode, WorkflowJsonObject } from '../types'

export const WORKFLOW_APP_MODE_FORMAT = 'amvision.workflow-app-mode.v1' as const
export const WORKFLOW_APP_MODE_METADATA_KEY = 'app_mode'

export type WorkflowAppModeDisplaySize = 'small' | 'medium' | 'large'

export interface WorkflowAppModeDisplay {
  node_id: string
  output_port: string
  title: string
  size: WorkflowAppModeDisplaySize
}

export interface WorkflowAppModeConfig {
  format_id: typeof WORKFLOW_APP_MODE_FORMAT
  title: string
  displays: WorkflowAppModeDisplay[]
}

export interface WorkflowAppModeDisplayCandidate extends WorkflowAppModeDisplay {
  node_title: string
  output_title: string
}

export interface WorkflowAppContractInput {
  binding_id: string
  template_port_id: string
  payload_type_id: string
  binding_kind: string
  required: boolean
  config: WorkflowJsonObject
  payload_schema: WorkflowJsonObject
  request_schema: WorkflowJsonObject
  allowed_media_types: string[]
  max_inline_bytes: number | null
  max_file_bytes: number | null
  max_files: number | null
  transports: string[]
  charset: string | null
}

export interface WorkflowAppContract {
  format_id: 'amvision.workflow-app-contract.v1'
  application_id: string
  inputs: WorkflowAppContractInput[]
  outputs: WorkflowJsonObject[]
}

/** 按 App Entry 的显式 binding 顺序排列发布契约输入，不依赖 Contract 内部序列化顺序。 */
export function orderWorkflowAppContractInputs(
  application: FlowApplication | null | undefined,
  contract: WorkflowAppContract | null | undefined,
): WorkflowAppContractInput[] {
  if (!contract) return []
  const inputsById = new Map(contract.inputs.map((input) => [input.binding_id, input]))
  const ordered: WorkflowAppContractInput[] = []
  for (const binding of application?.bindings ?? []) {
    if (binding.direction !== 'input') continue
    const input = inputsById.get(binding.binding_id)
    if (!input) continue
    ordered.push(input)
    inputsById.delete(binding.binding_id)
  }
  ordered.push(...contract.inputs.filter((input) => inputsById.has(input.binding_id)))
  return ordered
}

function isObject(value: unknown): value is WorkflowJsonObject {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value))
}

function readText(value: unknown): string {
  return typeof value === 'string' ? value.trim() : ''
}

function readSize(value: unknown): WorkflowAppModeDisplaySize | null {
  return value === 'small' || value === 'medium' || value === 'large' ? value : null
}

/** 读取编辑器 metadata 中的稳定 App Mode v1 配置。 */
export function readWorkflowAppModeConfig(metadata: WorkflowJsonObject): WorkflowAppModeConfig | null {
  const rawConfig = metadata[WORKFLOW_APP_MODE_METADATA_KEY]
  if (!isObject(rawConfig) || rawConfig.format_id !== WORKFLOW_APP_MODE_FORMAT || !Array.isArray(rawConfig.displays)) return null
  const displays: WorkflowAppModeDisplay[] = []
  const identities = new Set<string>()
  for (const rawDisplay of rawConfig.displays) {
    if (!isObject(rawDisplay)) return null
    const nodeId = readText(rawDisplay.node_id)
    const outputPort = readText(rawDisplay.output_port)
    const displayTitle = readText(rawDisplay.title)
    const size = readSize(rawDisplay.size)
    const identity = `${nodeId}\u0000${outputPort}`
    if (!nodeId || !outputPort || displayTitle.length > 128 || !size || identities.has(identity)) return null
    identities.add(identity)
    displays.push({
      node_id: nodeId,
      output_port: outputPort,
      title: displayTitle,
      size,
    })
  }
  const title = readText(rawConfig.title)
  if (displays.length === 0 || title.length > 128) return null
  return {
    format_id: WORKFLOW_APP_MODE_FORMAT,
    title,
    displays,
  }
}

/** 写入或移除 App Mode 配置，不修改 Application 其他 metadata。 */
export function writeWorkflowAppModeConfig(
  metadata: WorkflowJsonObject,
  config: WorkflowAppModeConfig | null,
): WorkflowJsonObject {
  const nextMetadata = { ...metadata }
  if (config === null) {
    delete nextMetadata[WORKFLOW_APP_MODE_METADATA_KEY]
    return nextMetadata
  }
  nextMetadata[WORKFLOW_APP_MODE_METADATA_KEY] = {
    format_id: WORKFLOW_APP_MODE_FORMAT,
    title: config.title.trim(),
    displays: config.displays.map((display) => ({
      node_id: display.node_id,
      output_port: display.output_port,
      title: display.title.trim(),
      size: display.size,
    })),
  }
  return nextMetadata
}

/** 从当前画布生成可发布的 Preview 输出候选项。 */
export function buildWorkflowAppModeDisplayCandidates(
  nodes: WorkflowGraphNode[],
  definitionsById: Map<string, NodeDefinition>,
): WorkflowAppModeDisplayCandidate[] {
  const candidates: WorkflowAppModeDisplayCandidate[] = []
  for (const node of nodes) {
    if (node.enabled === false) continue
    const definition = definitionsById.get(node.node_type_id)
    if (!definition?.capability_tags?.includes('ui.preview')) continue
    for (const output of definition.output_ports) {
      candidates.push({
        node_id: node.node_id,
        output_port: output.name,
        title: 'Node',
        size: 'medium',
        node_title: definition.display_name || node.node_type_id,
        output_title: output.display_name || output.name,
      })
    }
  }
  return candidates
}
