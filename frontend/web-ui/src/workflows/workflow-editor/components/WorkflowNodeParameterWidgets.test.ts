import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import { i18n } from '@/platform/i18n'
import type { NodeParameterUiField, WorkflowGraphNode } from '../types'
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
        isJson: () => false,
        readJsonTextValue: () => '',
        readJsonPlaceholder: () => '',
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
})
