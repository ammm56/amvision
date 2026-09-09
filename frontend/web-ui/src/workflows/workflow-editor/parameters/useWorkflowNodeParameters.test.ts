import { ref } from 'vue'
import { describe, expect, it } from 'vitest'

import type { NodeDefinition, NodeParameterUiField, WorkflowGraphNode } from '../types'
import { applyMissingNodeParameterDefaults, buildInitialNodeParameters, useWorkflowNodeParameters } from './useWorkflowNodeParameters'

const colorMapField: NodeParameterUiField = {
  parameter_name: 'class_colors',
  display_name: 'Class Colors',
  description: 'Class color map',
  group_id: 'default',
  order: 1,
  required: false,
  hidden: false,
  readonly: false,
  default_value: {},
  enum_options: [],
  widget: 'color-map',
  json_schema: { type: 'object' },
}

const jsonObjectField: NodeParameterUiField = {
  ...colorMapField,
  parameter_name: 'config',
  display_name: 'Config',
  widget: 'auto',
  json_schema: { type: 'object' },
}

const graphNode: WorkflowGraphNode = {
  node_id: 'draw-regions',
  node_type_id: 'custom.opencv.draw-regions',
  parameters: {},
  enabled: true,
  ui_state: {},
  metadata: {},
}

function buildParameters() {
  return useWorkflowNodeParameters({
    complexParameterDrafts: ref({}),
    readNodeTitle: () => 'Draw Regions',
    readParameterLabel: (field) => field.display_name,
    setStatusMessage: () => undefined,
    setErrorMessage: () => undefined,
  })
}

describe('useWorkflowNodeParameters color-map', () => {
  it('文字偏移输入支持负数、零值和保存后的数值回读', () => {
    const parameters = buildParameters()
    const node = { node: { ...graphNode, parameters: {} }, definition: null }
    for (const name of ['label_offset_x', 'label_offset_y']) {
      const field: NodeParameterUiField = {
        ...colorMapField, parameter_name: name, widget: 'auto', default_value: 0,
        json_schema: { type: 'integer', minimum: -2147483648, maximum: 2147483647 },
      }
      const input = document.createElement('input')
      input.type = 'number'
      input.addEventListener('input', (event) => parameters.updateNodeParameterFromNumberEvent(node, field, event))
      for (const value of [-16, 0, 24]) {
        input.value = String(value)
        input.dispatchEvent(new Event('input'))
        const saved = { ...node, node: JSON.parse(JSON.stringify(node.node)) }
        expect(parameters.readNodeParameterValue(saved, field)).toBe(value)
      }
    }
  })

  it('把 color-map 识别为紧凑专用控件而不是大 JSON 文本框', () => {
    const parameters = buildParameters()

    expect(parameters.isColorMapParameter(colorMapField)).toBe(true)
    expect(parameters.isJsonParameter(colorMapField)).toBe(false)
  })

  it('通过通用值更新入口一次性写入对象', () => {
    const parameters = buildParameters()
    const node: { node: WorkflowGraphNode; definition: NodeDefinition | null } = {
      node: { ...graphNode, parameters: {} },
      definition: null,
    }

    parameters.updateNodeParameterValue(node, colorMapField, {
      slot_empty: '#00C853',
    })

    expect(node.node.parameters).toEqual({
      class_colors: { slot_empty: '#00C853' },
    })
  })
})

describe('JSON 参数草稿生命周期', () => {
  function eventWithValue(value: string): Event {
    const target = document.createElement('textarea')
    target.value = value
    const event = new Event('input')
    Object.defineProperty(event, 'target', { value: target })
    return event
  }

  function subject() {
    const drafts = ref<Record<string, string>>({})
    const errors: Array<string | null> = []
    const parameters = useWorkflowNodeParameters({
      complexParameterDrafts: drafts,
      readNodeTitle: () => 'Node',
      readParameterLabel: field => field.display_name,
      setStatusMessage: () => undefined,
      setErrorMessage: message => errors.push(message),
    })
    const node: { node: WorkflowGraphNode; definition: NodeDefinition | null } = {
      node: { ...graphNode, parameters: {} },
      definition: null,
    }
    return { drafts, errors, node, parameters }
  }

  it('合法 JSON 失焦提交后清除 edited 标记并保留格式化草稿', () => {
    const { drafts, node, parameters } = subject()
    const event = eventWithValue('{"value":1}')

    parameters.updateNodeParameterJsonDraft(node, jsonObjectField, event)
    expect(parameters.hasPendingNodeParameterDrafts()).toBe(true)
    parameters.commitNodeParameterJsonDraft(node, jsonObjectField, event)

    expect(node.node.parameters).toEqual({ config: { value: 1 } })
    expect(drafts.value[`${graphNode.node_id}:config`]).toBe('{\n  "value": 1\n}')
    expect(parameters.hasPendingNodeParameterDrafts()).toBe(false)
  })

  it('非法或必填空 JSON 保留 pending，可选空值提交后清除 pending', () => {
    const { node, parameters } = subject()
    const invalid = eventWithValue('{')
    parameters.updateNodeParameterJsonDraft(node, jsonObjectField, invalid)
    parameters.commitNodeParameterJsonDraft(node, jsonObjectField, invalid)
    expect(parameters.hasPendingNodeParameterDrafts()).toBe(true)

    const empty = eventWithValue('')
    parameters.updateNodeParameterJsonDraft(node, jsonObjectField, empty)
    parameters.commitNodeParameterJsonDraft(node, { ...jsonObjectField, required: true }, empty)
    expect(parameters.hasPendingNodeParameterDrafts()).toBe(true)
    parameters.commitNodeParameterJsonDraft(node, jsonObjectField, empty)
    expect(parameters.hasPendingNodeParameterDrafts()).toBe(false)
    expect(node.node.parameters).not.toHaveProperty('config')
  })

  it('整体替换文档时同时清除文本和 edited 标记', () => {
    const { drafts, node, parameters } = subject()
    const event = eventWithValue('{"old":true}')
    parameters.updateNodeParameterJsonDraft(node, jsonObjectField, event)
    expect(parameters.hasPendingNodeParameterDrafts()).toBe(true)

    parameters.resetNodeParameterJsonDrafts()
    expect(drafts.value).toEqual({})
    parameters.readNodeParameterJsonTextValue(node, jsonObjectField)
    expect(parameters.hasPendingNodeParameterDrafts()).toBe(false)
  })

  it('直接保存时必填空 JSON 仍阻止提交，可选空 JSON 正常取消设置', () => {
    const requiredSubject = subject()
    const empty = eventWithValue('')
    requiredSubject.node.definition = {
      parameter_ui_schema: { groups: [], fields: [{ ...jsonObjectField, required: true }] },
    } as unknown as NodeDefinition
    requiredSubject.parameters.updateNodeParameterJsonDraft(
      requiredSubject.node,
      { ...jsonObjectField, required: true },
      empty,
    )

    expect(requiredSubject.parameters.commitPendingNodeParameterDrafts([
      requiredSubject.node,
    ])).toBe(false)
    expect(requiredSubject.parameters.hasPendingNodeParameterDrafts()).toBe(true)
    expect(requiredSubject.errors.at(-1)).toContain('Config')

    const optionalSubject = subject()
    optionalSubject.node.definition = {
      parameter_ui_schema: { groups: [], fields: [jsonObjectField] },
    } as unknown as NodeDefinition
    optionalSubject.parameters.updateNodeParameterJsonDraft(optionalSubject.node, jsonObjectField, empty)
    expect(optionalSubject.parameters.commitPendingNodeParameterDrafts([
      optionalSubject.node,
    ])).toBe(true)
    expect(optionalSubject.parameters.hasPendingNodeParameterDrafts()).toBe(false)
    expect(optionalSubject.node.node.parameters).not.toHaveProperty('config')
  })
})

describe('节点参数缺省与显式值', () => {
  function definition(): NodeDefinition {
    return {
      parameter_schema: {
        type: 'object',
        properties: {
          local_path: { type: 'string' },
          nullable: { default: null },
          number: { type: 'number', default: 9 },
          enabled: { type: 'boolean', default: true },
          text: { type: 'string', default: 'fallback' },
          items: { type: 'array', default: [{ key: 'value' }] },
          object: { type: 'object', default: {} },
        },
      },
      parameter_ui_schema: { groups: [], fields: [
        { ...colorMapField, parameter_name: 'local_path', default_value: null, json_schema: { type: 'string' } },
        { ...colorMapField, parameter_name: 'number', default_value: 999, json_schema: { default: 999 } },
      ] },
    } as unknown as NodeDefinition
  }

  it('只填入执行 Schema 明确声明的 default，包括显式 null', () => {
    expect(buildInitialNodeParameters(definition())).toEqual({
      nullable: null, number: 9, enabled: true, text: 'fallback', items: [{ key: 'value' }], object: {},
    })
  })

  it('补齐缺省不会覆盖 null、0、false、空字符串、空数组或空对象', () => {
    const node = { ...graphNode, parameters: { nullable: null, number: 0, enabled: false, text: '', items: [], object: {} } }
    expect(applyMissingNodeParameterDefaults(node, definition())).toBe(node)
    expect(applyMissingNodeParameterDefaults({ ...node, parameters: { local_path: null } }, definition()).parameters.local_path).toBeNull()
  })

  it('不同节点、复制与序列化不共享可变默认对象', () => {
    const schema = definition()
    const first = buildInitialNodeParameters(schema)
    const second = buildInitialNodeParameters(schema)
    ;(first.items as Array<{ key: string }>)[0].key = 'changed'
    expect(second.items).toEqual([{ key: 'value' }])
    const saved = JSON.parse(JSON.stringify({ ...graphNode, parameters: second }))
    expect(applyMissingNodeParameterDefaults(saved, schema).parameters).toEqual(second)
    expect(saved.parameters).not.toHaveProperty('local_path')
  })

  it('显示值区分缺省与 null，且不反向写入参数', () => {
    const parameters = buildParameters()
    const node = { node: { ...graphNode, parameters: { text: null } }, definition: definition() }
    expect(parameters.readNodeParameterValue(node, { ...colorMapField, parameter_name: 'text' })).toBeNull()
    expect(parameters.readNodeParameterValue(node, { ...colorMapField, parameter_name: 'local_path' })).toBeUndefined()
    expect(parameters.readNodeParameterValue(node, { ...colorMapField, parameter_name: 'number' })).toBe(9)
    expect(node.node.parameters).toEqual({ text: null })
  })

  it.each([null, '', 0, false, [], {}])('通用更新入口保留明确值 %j', (value) => {
    const parameters = buildParameters()
    const node = { node: { ...graphNode, parameters: {} }, definition: null }
    parameters.updateNodeParameterValue(node, colorMapField, value)
    expect(node.node.parameters).toEqual({ class_colors: value })
    parameters.updateNodeParameterValue(node, colorMapField, undefined)
    expect(node.node.parameters).toEqual({})
  })

  it('枚举选中 null 不变成空字符串，取消设置不选中第一个选项', () => {
    const parameters = buildParameters()
    const field = { ...colorMapField, enum_options: [{ label: 'Null', value: null }] }
    const node = { node: { ...graphNode, parameters: {} }, definition: null }
    parameters.updateNodeParameterFromEnumValue(node, field, '0')
    expect(node.node.parameters).toEqual({ class_colors: null })
    expect(parameters.readNodeParameterEnumIndex(node, field)).toBe('0')
    parameters.updateNodeParameterFromEnumValue(node, field, '')
    expect(node.node.parameters).toEqual({})
    expect(parameters.readNodeParameterEnumIndex(node, field)).toBe('')
  })
})
