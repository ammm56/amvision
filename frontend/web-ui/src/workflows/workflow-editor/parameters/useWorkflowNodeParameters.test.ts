import { ref } from 'vue'
import { describe, expect, it } from 'vitest'

import type { NodeParameterUiField, WorkflowGraphNode } from '../types'
import { useWorkflowNodeParameters } from './useWorkflowNodeParameters'

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
  it('把 color-map 识别为紧凑专用控件而不是大 JSON 文本框', () => {
    const parameters = buildParameters()

    expect(parameters.isColorMapParameter(colorMapField)).toBe(true)
    expect(parameters.isJsonParameter(colorMapField)).toBe(false)
  })

  it('通过通用值更新入口一次性写入对象', () => {
    const parameters = buildParameters()
    const node = { node: { ...graphNode, parameters: {} }, definition: null }

    parameters.updateNodeParameterValue(node, colorMapField, {
      slot_empty: '#00C853',
    })

    expect(node.node.parameters).toEqual({
      class_colors: { slot_empty: '#00C853' },
    })
  })
})
