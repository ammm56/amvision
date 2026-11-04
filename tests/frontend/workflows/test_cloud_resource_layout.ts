import { computed, ref } from 'vue'
import { expect, it } from 'vitest'
import { cloudResourceFieldHeight, visibleCloudParameterFields } from '@/workflows/workflow-editor/parameters/cloud-resource-fields'
import { useWorkflowGraphGeometry } from '@/workflows/workflow-editor/geometry/useWorkflowGraphGeometry'
import { useWorkflowNodeParameters } from '@/workflows/workflow-editor/parameters/useWorkflowNodeParameters'
import type { NodeParameterUiField } from '@/workflows/workflow-editor/types'

const field = (name: string, schema: Record<string, unknown> = {}) => ({ parameter_name: name, hidden: false, json_schema: schema } as NodeParameterUiField)
const source = field('source', { 'x-ui-widget': 'cloud-source', 'x-asset-clears': ['file_options'] })
const fields = [source, field('file_options'), field('other')]

it('hides only declared file-only fields for committed asset sources without changing parameters', () => {
  const parameters = { source: { kind: 'asset' }, file_options: { invalid: true } }
  expect(visibleCloudParameterFields(fields, parameters).map(f => f.parameter_name)).toEqual(['source', 'other'])
  expect(parameters.file_options).toEqual({ invalid: true })
  for (const value of [undefined, { kind: 'file' }, { kind: 'cloud' }]) {
    expect(visibleCloudParameterFields(fields, { source: value } as any)).toEqual(fields)
  }
  expect(visibleCloudParameterFields([field('source') , fields[1]!], parameters)).toHaveLength(2)
})

it('editor field selection restores parsing options when changing back to file input', () => {
  const editor = useWorkflowNodeParameters({ complexParameterDrafts: ref({}), readNodeTitle: () => '', readParameterLabel: () => '', setStatusMessage: () => {}, setErrorMessage: () => {} })
  const node = { node: { parameters: { source: { kind: 'asset' } } }, definition: { parameter_ui_schema: { fields } } } as any
  expect(editor.nodeParameterFieldsForNode(node)).toHaveLength(2)
  node.node.parameters.source = { kind: 'file' }
  expect(editor.nodeParameterFieldsForNode(node)).toHaveLength(3)
})

it.each(['cloud-source', 'cloud-target'])('reserves the full %s editor height in node and following port placement', widget => {
  const special = field('source', { 'x-ui-widget': widget }), following = field('next')
  const port = { name: 'next', payload_type_id: 'value.v1' }
  const node = { x: 0, y: 0, width: 256, node: { node_id: 'cloud', parameters: {} }, inputs: [port], outputs: [],
    definition: { input_ports: [port], parameter_input_bindings: [{ parameter_name: 'next', input_port_name: 'next' }] } } as any
  const geometry = useWorkflowGraphGeometry({
    graphNodes: ref([node]), graphEdges: ref([]), templateInputs: ref([]), templateOutputs: ref([]),
    appBoundaryNodes: computed(() => []), appInputBindings: computed(() => []), appOutputBindings: computed(() => []),
    templateInputById: computed(() => new Map()), templateOutputById: computed(() => new Map()), connectionDraft: ref(null),
    readPreviewDisplay: () => null, readParameterFields: () => [special, following], isJsonParameter: () => false,
    boundaryPortX: () => 0, boundaryPortY: () => 0, clampNumber: (v, low, high) => Math.max(low, Math.min(v, high)),
    layout: { nodeHeaderHeight: 60, portRowHeight: 30, portInsetX: 18, nodePreviewFrameHeight: 28,
      nodePreviewImageHeight: 140, nodePreviewDataHeight: 176, nodePreviewGalleryColumns: 2,
      nodePreviewGalleryItemHeight: 72, nodePreviewGalleryGap: 6, nodeWidgetRowHeight: 34,
      nodeJsonWidgetRowHeight: 126, nodeWidgetGap: 6, nodeWidgetPaddingTop: 6, nodeWidgetPaddingBottom: 10 },
  })
  const height = cloudResourceFieldHeight(special.json_schema)!
  expect(geometry.portY(node, 'next', 'input')).toBe(60 + 6 + height + 6 + 17)
  expect(geometry.nodeVisualHeight(node)).toBe(60 + 6 + height + 6 + 34 + 10 + 22)
  expect(cloudResourceFieldHeight({ 'x-ui-widget': 'unrelated' })).toBeNull()
})
