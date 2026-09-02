import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import { i18n } from '@/platform/i18n'
import type { NodeDefinition, NodeParameterUiField, NodePortDefinition, WorkflowGraphNode } from '../types'
import WorkflowNodeParameterWidgets from './WorkflowNodeParameterWidgets.vue'

const field: NodeParameterUiField = {
  parameter_name: 'max_concurrency',
  display_name: 'Max Concurrency',
  description: '',
  group_id: 'execution',
  order: 1,
  required: true,
  hidden: false,
  readonly: false,
  default_value: 2,
  enum_options: [],
  json_schema: { type: 'integer', minimum: 1, maximum: 64 },
}

const graphNode: WorkflowGraphNode = {
  node_id: 'parallel-start',
  node_type_id: 'core.logic.parallel-start',
  parameters: { max_concurrency: 2 },
  enabled: true,
  ui_state: {},
  metadata: {},
}

const node = {
  node: graphNode,
  definition: null,
  title: 'Parallel Start',
  x: 0,
  y: 0,
  width: 280,
  inputs: [],
  outputs: [],
}

const parameterPort: NodePortDefinition = {
  name: 'max_concurrency',
  display_name: 'Max Concurrency',
  payload_type_id: 'value.v1',
  description: '',
  required: false,
  multiple: false,
  metadata: {},
}

const dynamicDefinition: NodeDefinition = {
  format_id: 'amvision.node-definition.v1',
  node_type_id: graphNode.node_type_id,
  display_name: 'Parallel Start',
  category: 'Logic',
  description: '',
  implementation_kind: 'core-node',
  runtime_kind: 'python-callable',
  input_ports: [parameterPort],
  output_ports: [],
  parameter_schema: { type: 'object', properties: { max_concurrency: field.json_schema } },
  parameter_ui_schema: { groups: [], fields: [field] },
  parameter_input_bindings: [{ parameter_name: 'max_concurrency', input_port_name: 'max_concurrency' }],
  capability_tags: [],
  runtime_requirements: {},
  metadata: {},
}

describe('WorkflowNodeParameterWidgets', () => {
  it('数字参数在 input 阶段立即提交，保存操作不会读到旧值', async () => {
    const wrapper = mount(WorkflowNodeParameterWidgets, {
      global: { plugins: [i18n] },
      props: {
        node,
        fields: [field],
        readLabel: () => 'Max Concurrency',
        readEnumValue: () => '',
        readEnumOptions: () => [],
        isBoolean: () => false,
        readBooleanValue: () => false,
        isNumber: () => true,
        readTextValue: () => '2',
        isString: () => false,
        isColorMap: () => false,
        readValue: () => 2,
        isJson: () => false,
        readJsonTextValue: () => '',
        readJsonPlaceholder: () => '',
        isPortConnected: () => false,
        isSelectedEdgeEndpoint: () => false,
        isDraftAnchorPort: () => false,
        readInputSourceLabel: () => '',
      },
    })

    const input = wrapper.get('input[type="number"]')
    ;(input.element as HTMLInputElement).value = '1'
    await input.trigger('input')

    expect(wrapper.emitted('update-number')).toHaveLength(1)
    const event = wrapper.emitted('update-number')?.[0]?.[2] as Event | undefined
    expect(event).toBeInstanceOf(Event)
    expect((event?.target as HTMLInputElement).value).toBe('1')
  })

  it('参数端口沿用标准连线交互，连接后禁用固定回退值并显示来源', async () => {
    const dynamicNode = {
      ...node,
      definition: dynamicDefinition,
      inputs: [parameterPort],
    }
    const wrapper = mount(WorkflowNodeParameterWidgets, {
      global: { plugins: [i18n] },
      props: {
        node: dynamicNode,
        fields: [field],
        readLabel: () => 'Max Concurrency',
        readEnumValue: () => '',
        readEnumOptions: () => [],
        isBoolean: () => false,
        readBooleanValue: () => false,
        isNumber: () => true,
        readTextValue: () => '2',
        isString: () => false,
        isColorMap: () => false,
        readValue: () => 2,
        isJson: () => false,
        readJsonTextValue: () => '',
        readJsonPlaceholder: () => '',
        isPortConnected: () => true,
        isSelectedEdgeEndpoint: () => true,
        isDraftAnchorPort: () => false,
        readInputSourceLabel: () => 'Number Value / value',
      },
    })

    const port = wrapper.get('.workflow-graph-parameter-port')
    expect(port.attributes('data-port-name')).toBe('max_concurrency')
    expect(port.classes()).toContain('is-connected')
    expect(port.classes()).toContain('is-selected-endpoint')
    expect(wrapper.get('input[type="number"]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('.workflow-graph-node-widget__connection-source').text()).toBe('来自连接')
    expect(wrapper.get('.workflow-graph-node-widget__connection-source').attributes('title')).toContain('Number Value / value')

    await port.trigger('mousedown')
    expect(wrapper.emitted('start-port-connection')?.[0]?.[2]).toEqual(parameterPort)
  })
})
