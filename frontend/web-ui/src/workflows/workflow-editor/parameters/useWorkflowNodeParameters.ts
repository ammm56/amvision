import type { Ref } from 'vue'

import type { NodeDefinition, NodeParameterUiField, WorkflowGraphNode, WorkflowJsonObject } from '../types'

export type WorkflowNodeParameterSelectValue = string | number | boolean | null

export interface WorkflowNodeParameterSelectOption {
  label: string
  value: WorkflowNodeParameterSelectValue
  description?: string
}

export interface WorkflowNodeParameterView {
  node: WorkflowGraphNode
  definition: NodeDefinition | null
}

export interface WorkflowNodeParameterOptions<NodeView extends WorkflowNodeParameterView> {
  complexParameterDrafts: Ref<Record<string, string>>
  readNodeTitle: (node: NodeView) => string
  readParameterLabel: (field: NodeParameterUiField) => string
  setStatusMessage: (message: string | null) => void
  setErrorMessage: (message: string | null) => void
}

export function useWorkflowNodeParameters<NodeView extends WorkflowNodeParameterView>(options: WorkflowNodeParameterOptions<NodeView>) {
  function nodeParameterFieldsForNode(node: NodeView | null): NodeParameterUiField[] {
    if (!node?.definition?.parameter_ui_schema) return []
    return node.definition.parameter_ui_schema.fields.filter((field) => !field.hidden)
  }

  function isJsonParameter(field: NodeParameterUiField): boolean {
    return field.json_schema.type === 'object' || field.json_schema.type === 'array'
  }

  function isStringParameter(field: NodeParameterUiField): boolean {
    const type = field.json_schema.type
    return type === 'string' || type === undefined
  }

  function isNumberParameter(field: NodeParameterUiField): boolean {
    const type = field.json_schema.type
    return type === 'number' || type === 'integer'
  }

  function isBooleanParameter(field: NodeParameterUiField): boolean {
    return field.json_schema.type === 'boolean'
  }

  function readNodeParameterValue(node: NodeView, field: NodeParameterUiField): unknown {
    const value = node.node.parameters[field.parameter_name]
    return value ?? field.default_value ?? ''
  }

  function readNodeParameterTextValue(node: NodeView, field: NodeParameterUiField): string {
    const value = readNodeParameterValue(node, field)
    if (typeof value === 'string') return value
    if (typeof value === 'number' || typeof value === 'boolean') return String(value)
    return ''
  }

  function readNodeParameterBooleanValue(node: NodeView, field: NodeParameterUiField): boolean {
    const value = readNodeParameterValue(node, field)
    return value === true || value === 'true'
  }

  function readNodeParameterEnumIndex(node: NodeView, field: NodeParameterUiField): string {
    const value = readNodeParameterValue(node, field)
    const optionIndex = field.enum_options.findIndex((option) => areParameterValuesEqual(option.value, value))
    return optionIndex >= 0 ? String(optionIndex) : ''
  }

  function nodeParameterEnumOptions(field: NodeParameterUiField): WorkflowNodeParameterSelectOption[] {
    const enumOptions = field.enum_options.map((option, index) => ({ label: option.label, value: String(index) }))
    return field.required ? enumOptions : [{ label: '未设置', value: '' }, ...enumOptions]
  }

  function updateNodeParameterFromTextEvent(node: NodeView, field: NodeParameterUiField, event: Event): void {
    const target = event.target
    if (!(target instanceof HTMLInputElement)) return
    updateNodeParameter(node, field, target.value)
  }

  function updateNodeParameterFromNumberEvent(node: NodeView, field: NodeParameterUiField, event: Event): void {
    const target = event.target
    if (!(target instanceof HTMLInputElement)) return
    const value = target.value.trim()
    updateNodeParameter(node, field, value ? Number(value) : '')
  }

  function updateNodeParameterFromCheckboxEvent(node: NodeView, field: NodeParameterUiField, event: Event): void {
    const target = event.target
    if (!(target instanceof HTMLInputElement)) return
    updateNodeParameter(node, field, target.checked)
  }

  function updateNodeParameterFromEnumValue(node: NodeView, field: NodeParameterUiField, value: WorkflowNodeParameterSelectValue): void {
    const optionIndex = Number(selectValueToString(value))
    if (!Number.isInteger(optionIndex) || optionIndex < 0) {
      updateNodeParameter(node, field, '')
      return
    }
    updateNodeParameter(node, field, field.enum_options[optionIndex]?.value ?? '')
  }

  function readNodeParameterJsonTextValue(node: NodeView, field: NodeParameterUiField): string {
    const draftKey = buildComplexParameterDraftKey(node, field)
    if (!(draftKey in options.complexParameterDrafts.value)) {
      const value = readNodeParameterValue(node, field)
      options.complexParameterDrafts.value = {
        ...options.complexParameterDrafts.value,
        [draftKey]: value === '' || value === undefined ? '' : formatWorkflowJson(value),
      }
    }
    return options.complexParameterDrafts.value[draftKey] ?? ''
  }

  function updateNodeParameterJsonDraft(node: NodeView, field: NodeParameterUiField, event: Event): void {
    const target = event.target
    if (!(target instanceof HTMLTextAreaElement)) return
    const draftKey = buildComplexParameterDraftKey(node, field)
    options.complexParameterDrafts.value = {
      ...options.complexParameterDrafts.value,
      [draftKey]: target.value,
    }
  }

  function commitNodeParameterJsonDraft(node: NodeView, field: NodeParameterUiField, event: Event): void {
    const target = event.target
    if (!(target instanceof HTMLTextAreaElement)) return
    const rawValue = target.value.trim()
    if (!rawValue) {
      if (field.required) {
        options.setErrorMessage(`${options.readNodeTitle(node)} / ${options.readParameterLabel(field)} 不能为空。`)
        return
      }
      updateNodeParameter(node, field, '')
      const draftKey = buildComplexParameterDraftKey(node, field)
      options.complexParameterDrafts.value = { ...options.complexParameterDrafts.value, [draftKey]: '' }
      options.setErrorMessage(null)
      return
    }
    try {
      const parsedValue = JSON.parse(rawValue)
      if (!isJsonParameterValueCompatible(field, parsedValue)) {
        const expectedType = field.json_schema.type === 'array' ? '数组' : '对象'
        throw new Error(`参数要求 ${expectedType}`)
      }
      updateNodeParameter(node, field, parsedValue)
      const draftKey = buildComplexParameterDraftKey(node, field)
      options.complexParameterDrafts.value = {
        ...options.complexParameterDrafts.value,
        [draftKey]: formatWorkflowJson(parsedValue),
      }
      options.setErrorMessage(null)
    } catch (error) {
      const detail = error instanceof Error && error.message ? `：${error.message}` : ''
      options.setErrorMessage(`${options.readNodeTitle(node)} / ${options.readParameterLabel(field)} 需要填写合法 JSON${detail}`)
    }
  }

  function nodeParameterJsonPlaceholder(field: NodeParameterUiField): string {
    const exampleValue = buildSchemaExampleValue(field.json_schema)
    if (exampleValue === undefined) return field.json_schema.type === 'array' ? '[\n  \n]' : '{\n  \n}'
    return formatWorkflowJson(exampleValue)
  }

  function updateNodeParameter(node: NodeView, field: NodeParameterUiField, value: unknown): void {
    const nextParameters = { ...node.node.parameters }
    if (!field.required && (value === '' || value === null || value === undefined)) {
      delete nextParameters[field.parameter_name]
    } else {
      nextParameters[field.parameter_name] = value
    }
    node.node.parameters = nextParameters
    options.setStatusMessage('已更新节点参数')
  }

  function updateNodeParametersByName(node: NodeView, updates: Record<string, unknown>): void {
    const parameterNames = new Set(nodeParameterFieldsForNode(node).map((field) => field.parameter_name))
    const nextParameters = { ...node.node.parameters }
    let changed = false
    for (const [parameterName, value] of Object.entries(updates)) {
      if (!parameterNames.has(parameterName)) continue
      nextParameters[parameterName] = cloneWorkflowJsonValue(value)
      const draftKey = `${node.node.node_id}:${parameterName}`
      if (draftKey in options.complexParameterDrafts.value) {
        options.complexParameterDrafts.value = {
          ...options.complexParameterDrafts.value,
          [draftKey]: formatWorkflowJson(value),
        }
      }
      changed = true
    }
    if (!changed) {
      options.setErrorMessage(`${options.readNodeTitle(node)} 没有可更新的目标参数`)
      return
    }
    node.node.parameters = nextParameters
    options.setErrorMessage(null)
    options.setStatusMessage('已从图片取参更新节点参数')
  }

  return {
    nodeParameterFieldsForNode,
    isJsonParameter,
    isStringParameter,
    isNumberParameter,
    isBooleanParameter,
    readNodeParameterTextValue,
    readNodeParameterBooleanValue,
    readNodeParameterEnumIndex,
    nodeParameterEnumOptions,
    updateNodeParameterFromTextEvent,
    updateNodeParameterFromNumberEvent,
    updateNodeParameterFromCheckboxEvent,
    updateNodeParameterFromEnumValue,
    updateNodeParametersByName,
    readNodeParameterJsonTextValue,
    updateNodeParameterJsonDraft,
    commitNodeParameterJsonDraft,
    nodeParameterJsonPlaceholder,
  }
}

export function applyMissingNodeParameterDefaults(node: WorkflowGraphNode, definition: NodeDefinition): WorkflowGraphNode {
  const defaultParameters = buildInitialNodeParameters(definition)
  const missingParameterNames = Object.keys(defaultParameters).filter((parameterName) => !(parameterName in node.parameters) || node.parameters[parameterName] === null)
  if (missingParameterNames.length === 0) return node
  const normalizedParameters = { ...node.parameters }
  for (const parameterName of missingParameterNames) {
    normalizedParameters[parameterName] = defaultParameters[parameterName]
  }
  return {
    ...node,
    parameters: normalizedParameters,
  }
}

export function buildInitialNodeParameters(definition: NodeDefinition): WorkflowJsonObject {
  const nextParameters: WorkflowJsonObject = {}
  for (const field of definition.parameter_ui_schema?.fields ?? []) {
    if (field.default_value !== undefined) {
      nextParameters[field.parameter_name] = cloneWorkflowJsonValue(field.default_value)
    }
  }
  const schemaProperties = isWorkflowJsonObject(definition.parameter_schema) && isWorkflowJsonObject(definition.parameter_schema.properties)
    ? definition.parameter_schema.properties
    : null
  for (const [parameterName, propertySchema] of Object.entries(schemaProperties ?? {})) {
    if (parameterName in nextParameters) continue
    if (!isWorkflowJsonObject(propertySchema) || !('default' in propertySchema)) continue
    nextParameters[parameterName] = cloneWorkflowJsonValue(propertySchema.default)
  }
  return nextParameters
}

function buildComplexParameterDraftKey(node: WorkflowNodeParameterView, field: NodeParameterUiField): string {
  return `${node.node.node_id}:${field.parameter_name}`
}

function isJsonParameterValueCompatible(field: NodeParameterUiField, value: unknown): boolean {
  if (field.json_schema.type === 'array') return Array.isArray(value)
  if (field.json_schema.type === 'object') return Boolean(value && typeof value === 'object' && !Array.isArray(value))
  return true
}

function buildSchemaExampleValue(schema: unknown, keyHint = 'value'): unknown {
  if (!isWorkflowJsonObject(schema)) return undefined
  const enumValues = Array.isArray(schema.enum) ? schema.enum : null
  if (enumValues?.length) return enumValues[0]
  if ('default' in schema) return schema.default
  const schemaType = readDisplayText(schema.type)
  if (schemaType === 'object') {
    const properties = isWorkflowJsonObject(schema.properties) ? schema.properties : null
    if (!properties) return {}
    const sample: WorkflowJsonObject = {}
    let propertyCount = 0
    for (const [propertyName, propertySchema] of Object.entries(properties)) {
      if (propertyCount >= 4) break
      sample[propertyName] = buildSchemaExampleValue(propertySchema, propertyName) ?? buildSchemaFallbackValue(propertySchema, propertyName)
      propertyCount += 1
    }
    return sample
  }
  if (schemaType === 'array') {
    const itemSchema = isWorkflowJsonObject(schema.items) ? schema.items : null
    if (!itemSchema) return []
    return [buildSchemaExampleValue(itemSchema, keyHint) ?? buildSchemaFallbackValue(itemSchema, keyHint)]
  }
  return buildSchemaFallbackValue(schema, keyHint)
}

function buildSchemaFallbackValue(schema: unknown, keyHint: string): unknown {
  if (!isWorkflowJsonObject(schema)) return keyHint
  const schemaType = readDisplayText(schema.type)
  if (schemaType === 'integer' || schemaType === 'number') return 0
  if (schemaType === 'boolean') return true
  if (schemaType === 'array') return []
  if (schemaType === 'object') return {}
  if (keyHint === 'path') return 'field.path'
  if (keyHint === 'key') return 'column_key'
  if (keyHint === 'label') return 'Column Label'
  if (keyHint === 'title') return 'Preview Title'
  if (keyHint === 'caption') return 'Image'
  return keyHint
}

function areParameterValuesEqual(leftValue: unknown, rightValue: unknown): boolean {
  if (Object.is(leftValue, rightValue)) return true
  return String(leftValue) === String(rightValue)
}

function selectValueToString(value: WorkflowNodeParameterSelectValue): string {
  return typeof value === 'string' ? value : String(value ?? '')
}

function cloneWorkflowJsonValue<T>(value: T): T {
  if (value === undefined) return value
  return JSON.parse(JSON.stringify(value)) as T
}

function formatWorkflowJson(value: unknown): string {
  if (value === undefined) return ''
  return JSON.stringify(value, null, 2)
}

function isWorkflowJsonObject(value: unknown): value is WorkflowJsonObject {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value))
}

function readDisplayText(value: unknown): string {
  return typeof value === 'string' && value.trim() ? value.trim() : ''
}
