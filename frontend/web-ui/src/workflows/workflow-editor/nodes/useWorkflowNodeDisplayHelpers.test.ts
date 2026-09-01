import { computed, ref } from 'vue'
import { describe, expect, it } from 'vitest'

import { useWorkflowNodeDisplayHelpers, type WorkflowNodeDisplayView } from './useWorkflowNodeDisplayHelpers'
import { useWorkflowGraphNodeViews } from './useWorkflowGraphNodeViews'
import type { NodeDefinition, WorkflowNodeCatalogResponse } from '../types'

function buildDefinition(metadata: Record<string, unknown>): NodeDefinition {
  return {
    format_id: 'amvision.node-definition.v1',
    node_type_id: 'core.logic.object-field',
    display_name: 'Object Field',
    category: 'core.logic.object',
    description: '',
    implementation_kind: 'core-node',
    runtime_kind: 'python-callable',
    input_ports: [],
    output_ports: [],
    parameter_schema: {},
    parameter_ui_schema: null,
    capability_tags: [],
    runtime_requirements: {},
    metadata,
  }
}

function buildNode(definition: NodeDefinition, parameters: Record<string, unknown>): WorkflowNodeDisplayView {
  return {
    definition,
    title: definition.display_name,
    inputs: [],
    outputs: [],
    node: {
      node_id: 'field-node',
      node_type_id: definition.node_type_id,
      parameters,
      enabled: true,
      ui_state: {},
      metadata: {},
    },
  }
}

describe('workflow node semantic title', () => {
  it('shows the explicit object key carried by a deterministic field node', () => {
    const helpers = useWorkflowNodeDisplayHelpers({ currentLocale: computed(() => 'en-US'), graphEdges: ref([]) })
    const definition = buildDefinition({ title_parameter: 'key' })

    expect(helpers.readGraphNodeTitle(buildNode(definition, { key: 'image_width' })))
      .toBe('Object Field · image_width')
  })

  it('keeps the base title when the semantic parameter is dynamically connected', () => {
    const helpers = useWorkflowNodeDisplayHelpers({
      currentLocale: computed(() => 'en-US'),
      graphEdges: ref([{
        edge_id: 'dynamic-key-edge',
        source_node_id: 'dynamic-key',
        source_port: 'value',
        target_node_id: 'field-node',
        target_port: 'key',
        metadata: {},
      }]),
    })
    const definition = buildDefinition({ title_parameter: 'key' })
    definition.parameter_input_bindings = [{ parameter_name: 'key', input_port_name: 'key' }]

    expect(helpers.readGraphNodeTitle(buildNode(definition, { key: 'stale-static-key' }))).toBe('Object Field')
  })

  it('removes compatibility-only nodes from the node picker', () => {
    const legacyDefinition = buildDefinition({ palette_hidden: true })
    const replacementDefinition = {
      ...buildDefinition({}),
      node_type_id: 'core.logic.object-build',
    }
    const nodeCatalog = ref<WorkflowNodeCatalogResponse>({
      node_pack_manifests: [],
      payload_contracts: [],
      node_definitions: [legacyDefinition, replacementDefinition],
      palette_groups: [],
    })
    const views = useWorkflowGraphNodeViews({
      nodeCatalog,
      graphEdges: ref([]),
    })

    expect(views.nodePickerDefinitions.value.map((definition) => definition.node_type_id))
      .toEqual(['core.logic.object-build'])
  })
})
