import { computed, ref } from 'vue'
import { describe, expect, it } from 'vitest'

import type { WorkflowBoundaryNodeView } from '../bindings/useWorkflowBoundaryNodes'
import type { NodeDefinition, NodeParameterUiField, NodePortDefinition, WorkflowGraphNode } from '../types'
import { useWorkflowGraphGeometry, type WorkflowGraphGeometryLayout } from './useWorkflowGraphGeometry'

const imagePort: NodePortDefinition = {
  name: 'image',
  display_name: 'Image',
  payload_type_id: 'image-ref.v1',
  description: '',
  required: true,
  multiple: false,
  metadata: {},
}

const directoryPort: NodePortDefinition = {
  name: 'save_directory',
  display_name: 'Save Directory',
  payload_type_id: 'value.v1',
  description: '',
  required: false,
  multiple: false,
  metadata: {},
}

const outputPort: NodePortDefinition = {
  name: 'saved_image',
  display_name: 'Saved Image',
  payload_type_id: 'image-ref.v1',
  description: '',
  required: true,
  multiple: false,
  metadata: {},
}

const field: NodeParameterUiField = {
  parameter_name: 'save_directory',
  display_name: 'Save Directory',
  description: '',
  group_id: 'save',
  order: 1,
  required: false,
  hidden: false,
  readonly: false,
  default_value: '',
  enum_options: [],
  json_schema: { type: 'string' },
}

const definition: NodeDefinition = {
  format_id: 'amvision.node-definition.v1',
  node_type_id: 'core.io.image-save',
  display_name: 'Save Image',
  category: 'I/O',
  description: '',
  implementation_kind: 'core-node',
  runtime_kind: 'python-callable',
  input_ports: [imagePort, directoryPort],
  output_ports: [outputPort],
  parameter_schema: { type: 'object', properties: { save_directory: field.json_schema } },
  parameter_ui_schema: { groups: [], fields: [field] },
  parameter_input_bindings: [{ parameter_name: 'save_directory', input_port_name: 'save_directory' }],
  capability_tags: [],
  runtime_requirements: {},
  metadata: {},
}

const graphNode: WorkflowGraphNode = {
  node_id: 'save-image',
  node_type_id: definition.node_type_id,
  parameters: { save_directory: 'fallback' },
  enabled: true,
  ui_state: {},
  metadata: {},
}

const node = {
  node: graphNode,
  definition,
  x: 200,
  y: 100,
  width: 256,
  inputs: definition.input_ports,
  outputs: definition.output_ports,
}

const layout: WorkflowGraphGeometryLayout = {
  nodeHeaderHeight: 60,
  portRowHeight: 30,
  portInsetX: 18,
  nodePreviewFrameHeight: 28,
  nodePreviewImageHeight: 140,
  nodePreviewDataHeight: 176,
  nodePreviewGalleryColumns: 2,
  nodePreviewGalleryItemHeight: 72,
  nodePreviewGalleryGap: 6,
  nodeWidgetRowHeight: 34,
  nodeJsonWidgetRowHeight: 126,
  nodeWidgetGap: 6,
  nodeWidgetPaddingTop: 6,
  nodeWidgetPaddingBottom: 10,
}

describe('useWorkflowGraphGeometry parameter input positions', () => {
  it('参数端口连接到对应控件中心，且不会重复占用普通端口行', () => {
    const geometry = useWorkflowGraphGeometry({
      graphNodes: ref([node]),
      graphEdges: ref([]),
      templateInputs: ref([]),
      templateOutputs: ref([]),
      appBoundaryNodes: computed(() => [] as WorkflowBoundaryNodeView[]),
      appInputBindings: computed(() => []),
      appOutputBindings: computed(() => []),
      templateInputById: computed(() => new Map()),
      templateOutputById: computed(() => new Map()),
      connectionDraft: ref(null),
      readPreviewDisplay: () => null,
      readParameterFields: () => [field],
      isJsonParameter: () => false,
      boundaryPortX: () => 0,
      boundaryPortY: () => 0,
      layout,
      clampNumber: (value, minValue, maxValue) => Math.min(Math.max(value, minValue), maxValue),
    })

    expect(geometry.portY(node, 'image', 'input')).toBe(175)
    expect(geometry.portY(node, 'save_directory', 'input')).toBe(213)
    expect(geometry.portY(node, 'saved_image', 'output')).toBe(175)
    expect(geometry.nodeVisualHeight(node)).toBe(162)
  })
})
