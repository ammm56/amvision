import type { FlowApplication, WorkflowGraphTemplate } from '../types'

/** 便携编辑文档只封装现有 Application/Template，不携带运行态。 */
export const WORKFLOW_APP_DOCUMENT_FORMAT = 'amvision.workflow-app-document.v1' as const
export const WORKFLOW_DOCUMENT_MAX_BYTES = 16 * 1024 * 1024
export const WORKFLOW_DOCUMENT_MAX_NODES = 10_000
export const WORKFLOW_DOCUMENT_MAX_NOTES = 128
export const WORKFLOW_DOCUMENT_MAX_GRAPH_ITEMS = 50_000
export const WORKFLOW_DOCUMENT_MAX_JSON_DEPTH = 64
export const WORKFLOW_DOCUMENT_MAX_JSON_VALUES = 200_000

export type WorkflowDocumentLimitKind = 'bytes' | 'nodes' | 'notes' | 'graph-items' | 'json-depth' | 'json-values'

/** 为页面提供稳定、可本地化的错误类别，具体提示由当前语言环境决定。 */
export class WorkflowDocumentLimitError extends Error {
  constructor(
    readonly kind: WorkflowDocumentLimitKind,
    readonly limit: number,
    readonly path = '$',
  ) {
    super(`${path}: ${kind} limit ${limit}`)
    this.name = 'WorkflowDocumentLimitError'
  }
}
export interface WorkflowAppDocumentV1 {
  format_id: typeof WORKFLOW_APP_DOCUMENT_FORMAT
  application: FlowApplication
  template: WorkflowGraphTemplate
}

/** JSON 深复制兼容 Vue Proxy，且不复用导入对象的嵌套状态。 */
export function cloneWorkflowJson<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T
}

type Check = (value: unknown, path: string) => void
const fail = (path: string, expected: string): never => { throw new Error(`${path}: ${expected}`) }
const text: Check = (value, path) => { if (typeof value !== 'string') fail(path, 'string') }
const id: Check = (value, path) => { text(value, path); if (!(value as string).trim()) fail(path, 'non-empty string') }
const bool: Check = (value, path) => { if (typeof value !== 'boolean') fail(path, 'boolean') }
const number: Check = (value, path) => { if (typeof value !== 'number' || !Number.isFinite(value)) fail(path, 'finite number') }
const object: Check = (value, path) => { if (!value || typeof value !== 'object' || Array.isArray(value)) fail(path, 'object') }
/** 自由 JSON 字段使用显式栈校验深度，避免递归栈溢出。 */
const jsonValue: Check = (value, path) => {
  const stack: Array<{ value: unknown; path: string; depth: number }> = [{ value, path, depth: 0 }]
  while (stack.length) {
    const current = stack.pop()!
    if (current.depth > WORKFLOW_DOCUMENT_MAX_JSON_DEPTH) {
      throw new WorkflowDocumentLimitError('json-depth', WORKFLOW_DOCUMENT_MAX_JSON_DEPTH, current.path)
    }
    if (current.value === null || typeof current.value === 'string' || typeof current.value === 'boolean') continue
    if (typeof current.value === 'number') { number(current.value, current.path); continue }
    if (Array.isArray(current.value)) {
      for (let index = current.value.length - 1; index >= 0; index -= 1) {
        stack.push({ value: current.value[index], path: `${current.path}[${index}]`, depth: current.depth + 1 })
      }
      continue
    }
    object(current.value, current.path)
    const entries = Object.entries(current.value as Record<string, unknown>)
    for (let index = entries.length - 1; index >= 0; index -= 1) {
      const [key, item] = entries[index]!
      stack.push({ value: item, path: `${current.path}.${key}`, depth: current.depth + 1 })
    }
  }
}
const jsonObject: Check = (value, path) => { object(value, path); jsonValue(value, path) }
const oneOf = (...values: unknown[]): Check => (value, path) => { if (!values.includes(value)) fail(path, values.join(' | ')) }
const optional = (check: Check): Check => (value, path) => { if (value !== undefined) check(value, path) }
const nullable = (check: Check): Check => (value, path) => { if (value !== null) check(value, path) }
const list = (check: Check): Check => (value, path) => {
  if (!Array.isArray(value)) fail(path, 'array')
  ;(value as unknown[]).forEach((item, index) => check(item, `${path}[${index}]`))
}
const shape = (fields: Record<string, Check>): Check => (value, path) => {
  object(value, path)
  const record = value as Record<string, unknown>
  for (const key of Object.keys(record)) if (!Object.hasOwn(fields, key)) fail(`${path}.${key}`, 'unsupported field')
  for (const [key, check] of Object.entries(fields)) check(record[key], `${path}.${key}`)
}
const rect = shape({ x: number, y: number, width: number, height: number })
const node = shape({ node_id: id, node_type_id: id, enabled: bool, parameters: jsonObject, metadata: jsonObject, ui_state: jsonObject })
const edge = shape({ edge_id: id, source_node_id: id, source_port: id, target_node_id: id, target_port: id, metadata: jsonObject })
const input = shape({ input_id: id, display_name: text, payload_type_id: id, target_node_id: id, target_port: id, required: bool, metadata: jsonObject })
const output = shape({ output_id: id, display_name: text, payload_type_id: id, source_node_id: id, source_port: id, metadata: jsonObject })
const group = shape({ group_id: id, name: text, enabled: bool, rect, member_node_ids: list(id), member_note_ids: list(id), membership_policy: oneOf('full-containment'), color: optional(nullable(text)), collapsed: bool, locked: bool, metadata: jsonObject })
const note = shape({ note_id: id, title: text, content: text, content_format: oneOf('markdown'), rect, tone: oneOf('neutral', 'info', 'success', 'warning', 'danger'), collapsed: bool, locked: bool, metadata: jsonObject })
const reference = shape({ template_id: id, template_version: id, source_kind: oneOf('json-file', 'registry', 'embedded'), source_uri: optional(nullable(text)), metadata: jsonObject })
const binding = shape({ binding_id: id, direction: oneOf('input', 'output'), template_port_id: id, binding_kind: id, required: bool, config: jsonObject, metadata: jsonObject })
const application = shape({ format_id: oneOf('amvision.flow-application.v1'), application_id: id, display_name: text, description: text, runtime_mode: oneOf('python-json-workflow'), template_ref: reference, bindings: list(binding), metadata: jsonObject })
const template = shape({ format_id: oneOf('amvision.workflow-graph-template.v1'), template_id: id, template_version: id, display_name: text, description: text, nodes: list(node), edges: list(edge), template_inputs: list(input), template_outputs: list(output), groups: list(group), notes: list(note), metadata: jsonObject })
const documentShape = shape({ format_id: oneOf(WORKFLOW_APP_DOCUMENT_FORMAT), application, template })

/** 先对整份输入做有界遍历，阻止大量极小 JSON 值占满主线程。 */
function validateDocumentJsonValueCount(value: unknown): void {
  const stack: unknown[] = [value]
  let count = 0
  while (stack.length) {
    const current = stack.pop()
    count += 1
    if (count > WORKFLOW_DOCUMENT_MAX_JSON_VALUES) {
      throw new WorkflowDocumentLimitError('json-values', WORKFLOW_DOCUMENT_MAX_JSON_VALUES)
    }
    if (current === null || typeof current === 'string' || typeof current === 'boolean') continue
    if (typeof current === 'number') { number(current, '$'); continue }
    if (Array.isArray(current)) {
      for (let index = current.length - 1; index >= 0; index -= 1) stack.push(current[index])
      continue
    }
    object(current, '$')
    for (const item of Object.values(current as Record<string, unknown>)) stack.push(item)
  }
}

function readArray(record: unknown, key: string): unknown[] | null {
  if (!record || typeof record !== 'object' || Array.isArray(record)) return null
  const value = (record as Record<string, unknown>)[key]
  return Array.isArray(value) ? value : null
}

/** 图集合上限先于完整 shape 遍历执行。 */
function validateDocumentGraphItemCount(value: unknown): void {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return
  const document = value as Record<string, unknown>
  const template = document.template
  const application = document.application
  const nodes = readArray(template, 'nodes')
  const notes = readArray(template, 'notes')
  if (nodes && nodes.length > WORKFLOW_DOCUMENT_MAX_NODES) {
    throw new WorkflowDocumentLimitError('nodes', WORKFLOW_DOCUMENT_MAX_NODES, '$.template.nodes')
  }
  if (notes && notes.length > WORKFLOW_DOCUMENT_MAX_NOTES) {
    throw new WorkflowDocumentLimitError('notes', WORKFLOW_DOCUMENT_MAX_NOTES, '$.template.notes')
  }
  const collections = [
    nodes,
    readArray(template, 'edges'),
    readArray(template, 'template_inputs'),
    readArray(template, 'template_outputs'),
    readArray(template, 'groups'),
    notes,
    readArray(application, 'bindings'),
  ]
  let itemCount = collections.reduce((total, items) => total + (items?.length ?? 0), 0)
  for (const group of readArray(template, 'groups') ?? []) {
    itemCount += (readArray(group, 'member_node_ids')?.length ?? 0) + (readArray(group, 'member_note_ids')?.length ?? 0)
  }
  if (itemCount > WORKFLOW_DOCUMENT_MAX_GRAPH_ITEMS) {
    throw new WorkflowDocumentLimitError('graph-items', WORKFLOW_DOCUMENT_MAX_GRAPH_ITEMS, '$.template')
  }
}

function unique(values: string[], path: string): Set<string> {
  const result = new Set<string>()
  for (const value of values) { if (result.has(value)) fail(path, `duplicate id ${value}`); result.add(value) }
  return result
}
function refers(ids: Set<string>, value: string, path: string): void {
  if (!ids.has(value)) fail(path, `unknown id ${value}`)
}

/** 只校验文件结构和引用，不检查目录、运行参数或外部文件。 */
export function parseWorkflowAppDocumentV1(value: unknown): WorkflowAppDocumentV1 {
  validateDocumentJsonValueCount(value)
  validateDocumentGraphItemCount(value)
  documentShape(value, '$')
  const doc = value as WorkflowAppDocumentV1
  const a = doc.application
  const t = doc.template
  if (a.template_ref.template_id !== t.template_id || a.template_ref.template_version !== t.template_version) fail('$.application.template_ref', 'template mismatch')
  if (a.template_ref.source_kind === 'json-file') id(a.template_ref.source_uri, '$.application.template_ref.source_uri')
  const nodes = unique(t.nodes.map((item) => item.node_id), '$.template.nodes')
  unique(t.edges.map((item) => item.edge_id), '$.template.edges')
  const inputs = unique(t.template_inputs.map((item) => item.input_id), '$.template.template_inputs')
  const outputs = unique(t.template_outputs.map((item) => item.output_id), '$.template.template_outputs')
  unique(t.groups.map((item) => item.group_id), '$.template.groups')
  const notes = unique(t.notes.map((item) => item.note_id), '$.template.notes')
  unique(a.bindings.map((item) => item.binding_id), '$.application.bindings')
  t.edges.forEach((item, i) => {
    refers(nodes, item.source_node_id, `$.template.edges[${i}].source_node_id`)
    refers(nodes, item.target_node_id, `$.template.edges[${i}].target_node_id`)
  })
  t.template_inputs.forEach((item, i) => refers(nodes, item.target_node_id, `$.template.template_inputs[${i}].target_node_id`))
  t.template_outputs.forEach((item, i) => refers(nodes, item.source_node_id, `$.template.template_outputs[${i}].source_node_id`))
  a.bindings.forEach((item, i) => refers(item.direction === 'input' ? inputs : outputs, item.template_port_id, `$.application.bindings[${i}].template_port_id`))
  t.groups.forEach((item, i) => {
    unique(item.member_node_ids, `$.template.groups[${i}].member_node_ids`)
    unique(item.member_note_ids, `$.template.groups[${i}].member_note_ids`)
    item.member_node_ids.forEach((key) => refers(nodes, key, `$.template.groups[${i}].member_node_ids`))
    item.member_note_ids.forEach((key) => refers(notes, key, `$.template.groups[${i}].member_note_ids`))
  })
  return cloneWorkflowJson(doc)
}

/** 导出文件里的 Template 已嵌入，来源路径不作为跨项目依赖。 */
export function createWorkflowAppDocument(application: FlowApplication, template: WorkflowGraphTemplate): WorkflowAppDocumentV1 {
  const doc = parseWorkflowAppDocumentV1({ format_id: WORKFLOW_APP_DOCUMENT_FORMAT, application, template })
  delete doc.application.metadata.project_id
  doc.application.template_ref.source_kind = 'embedded'
  doc.application.template_ref.source_uri = null
  return doc
}

/** 目标身份由当前编辑页决定，名称、说明与图配置整体来自源文档。 */
export function retargetWorkflowAppDocument(doc: WorkflowAppDocumentV1, current: { application: FlowApplication; template: WorkflowGraphTemplate }): WorkflowAppDocumentV1 {
  const next = cloneWorkflowJson(doc)
  next.application.application_id = current.application.application_id
  next.application.template_ref = cloneWorkflowJson(current.application.template_ref)
  delete next.application.metadata.project_id
  if (Object.hasOwn(current.application.metadata, 'project_id')) next.application.metadata.project_id = current.application.metadata.project_id
  next.template.template_id = current.template.template_id
  next.template.template_version = current.template.template_version
  return next
}

/** 保证导出文件能被同一大小限制重新导入。 */
export function serializeWorkflowAppDocument(doc: WorkflowAppDocumentV1): string {
  const json = `${JSON.stringify(doc, null, 2)}\n`
  if (new Blob([json]).size > WORKFLOW_DOCUMENT_MAX_BYTES) {
    throw new WorkflowDocumentLimitError('bytes', WORKFLOW_DOCUMENT_MAX_BYTES)
  }
  return json
}

/** 下载完成取得 Blob 后再释放 URL，不创建服务端资产。 */
export function downloadWorkflowAppDocument(doc: WorkflowAppDocumentV1): void {
  const url = URL.createObjectURL(new Blob([serializeWorkflowAppDocument(doc)], { type: 'application/json;charset=utf-8' }))
  const link = document.createElement('a')
  link.href = url
  link.download = `${doc.application.application_id.replace(/[<>:"/\\|?*\u0000-\u001f]/g, '_')}.json`
  try { document.body.append(link); link.click() } finally { link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000) }
}
