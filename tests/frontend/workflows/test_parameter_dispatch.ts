import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { reactive, ref } from 'vue'
import { createI18n } from 'vue-i18n'
import Widgets from '@/workflows/workflow-editor/components/WorkflowNodeParameterWidgets.vue'
import RoiEditor from '../../../custom_nodes/_metrology3d_nodes/frontend/RoiEditor.vue'
import CloudResourceParameter from '@/workflows/workflow-editor/point-cloud/CloudResourceParameter.vue'
import { useWorkflowNodeParameters } from '@/workflows/workflow-editor/parameters/useWorkflowNodeParameters'
import { rowScalar } from '@/workflows/workflow-editor/parameters/row-scalar'
import { parseWorkflowNumericDisplayValue, readWorkflowNumericParameterInputAttributes } from '@/workflows/workflow-editor/parameters/numeric-parameter-input'
import type { NodeDefinition, NodeParameterUiField, WorkflowGraphNode } from '@/workflows/workflow-editor/types'
import catalog from './fixtures/metrology-parameter-ui.json'

const parameters = () => useWorkflowNodeParameters({ complexParameterDrafts: ref({}), readNodeTitle: v => v.node.node_id, readParameterLabel: f => f.display_name, setStatusMessage: vi.fn(), setErrorMessage: vi.fn() })
const field = (schema: Record<string, unknown>) => ({ parameter_name: 'value', display_name: 'Value', description: '', group_id: 'default', order: 0, required: false, hidden: false, readonly: false, default_value: null, enum_options: [], widget: 'auto', json_schema: schema }) as NodeParameterUiField
afterEach(() => { document.body.innerHTML = '' })

function render(kind: keyof typeof catalog, name: string, value: unknown) {
  const f = structuredClone(catalog[kind].fields.find(f => f.parameter_name === name)!) as NodeParameterUiField
  const node = reactive({ node: { node_id: 'one', node_type_id: `custom.metrology3d.${kind}`, parameters: { [name]: value }, enabled: true, ui_state: {}, metadata: {} } as WorkflowGraphNode, definition: { parameter_schema: {}, input_ports: [], parameter_input_bindings: [] } as unknown as NodeDefinition, title: kind, x: 0, y: 0, width: 250, inputs: [], outputs: [] })
  const p = parameters()
  const w = mount(Widgets, { attachTo: document.body, props: {
    node, fields: [f], readLabel: f => f.display_name, readEnumValue: p.readNodeParameterEnumIndex, readEnumOptions: p.nodeParameterEnumOptions,
    isBoolean: p.isBooleanParameter, readBooleanValue: p.readNodeParameterBooleanValue, isNumber: p.isNumberParameter, readTextValue: p.readNodeParameterTextValue,
    isString: p.isStringParameter, isColorMap: p.isColorMapParameter, readValue: p.readNodeParameterValue, isJson: p.isJsonParameter,
    readJsonTextValue: p.readNodeParameterJsonTextValue, readJsonPlaceholder: () => '', isPortConnected: () => false, isSelectedEdgeEndpoint: () => false,
    isDraftAnchorPort: () => false, readInputSourceLabel: () => '',
    'onUpdate-value': (n, f, v) => p.updateNodeParameterValue(n, f, v),
  }, global: { plugins: [createI18n({ legacy: false, locale: 'en-US', missingWarn: false, fallbackWarn: false })] } })
  return { w, node, f, p }
}

it('dispatches the real ROI union schema to its existing editor and isolates node changes', async () => {
  const source = { kind: 'parameters', bounds: [], roi: { roi_id: 'area', frame_id: 'fixture', length_unit: 'mm', kind: 'box', geometry: { center: [0, 0, 0], size: [2, 3, 4], rotation: [[1, 0, 0], [0, 1, 0], [0, 0, 1]] } } }
  const { w, node } = render('crop-roi', 'source', source)
  try {
    expect(w.findComponent(RoiEditor).exists()).toBe(true)
    expect(w.find('input').exists()).toBe(false)
    await w.get('button').trigger('click'); await flushPromises()
    expect(document.querySelector('[role=dialog]')).not.toBeNull()
    const coordinate = document.querySelector<HTMLInputElement>('input[aria-label="Center XYZ 1"]')!
    coordinate.value = '9'; coordinate.dispatchEvent(new Event('input', { bubbles: true })); await flushPromises()
    const apply = [...document.querySelectorAll('button')].find(button => button.textContent?.trim() === 'Apply')!
    apply.click(); await flushPromises()
    expect((node.node.parameters.source as typeof source).roi.geometry.center[0]).toBe(9)
    await w.get('button').trigger('click'); await flushPromises()
    node.node.node_id = 'two'; node.node.parameters = { source: { kind: 'input', bounds: [] } }
    await flushPromises()
    expect(document.querySelector('[role=dialog]')).toBeNull()
    expect(node.node.parameters.source).toEqual({ kind: 'input', bounds: [] })
    await w.get('button').trigger('click'); await flushPromises()
  } finally { w.unmount() }
  expect(document.querySelector('[role=dialog]')).toBeNull()
})

it.each([['read-cloud', 'source', { kind: 'file' }], ['save-cloud', 'target', { kind: 'new', name: 'Scan' }]] as const)('dispatches %s resource union before scalar controls', (kind, name, value) => {
  const { w } = render(kind, name, value)
  try { expect(w.findComponent(CloudResourceParameter).exists()).toBe(true); expect(w.find('select').exists()).toBe(true) } finally { w.unmount() }
})

it('does not display an uncommitted file source in a blank node', async () => {
  const { w, node } = render('read-cloud', 'source', undefined)
  try {
    expect((w.get('select').element as HTMLSelectElement).value).toBe('')
    expect(node.node.parameters.source).toBeUndefined()
    await w.get('select').setValue('file')
    expect(node.node.parameters.source).toEqual({ kind: 'file' })
    node.node.node_id = 'another'; node.node.parameters = {}
    await flushPromises()
    expect((w.get('select').element as HTMLSelectElement).value).toBe('')
    expect(node.node.parameters.source).toBeUndefined()
  } finally { w.unmount() }
})

it.each([['read-cloud', 'file_options'], ['cloud-preview', 'color']] as const)('keeps %s.%s compound data visible as JSON, never an empty string', (kind, name) => {
  const value = name === 'color' ? { mode: 'solid' } : { profile_id: 'ply-ascii' }
  const { w } = render(kind, name, value)
  try { expect(w.get('textarea').element.value).toBe(JSON.stringify(value, null, 2)); expect(w.find('input').exists()).toBe(false) } finally { w.unmount() }
})

it('does not flatten multi-branch unions or unknown schemas into primitive controls', () => {
  const p = parameters()
  for (const schema of [{}, { oneOf: [{ type: 'string' }, { type: 'object' }] }, { anyOf: [{ type: 'number' }, { type: 'string' }, { type: 'null' }] }, { type: ['string', 'object', 'null'] }]) {
    expect(p.isStringParameter(field(schema))).toBe(false)
    expect(p.isNumberParameter(field(schema))).toBe(false)
    expect(p.isJsonParameter(field(schema))).toBe(true)
  }
})

it('retains nullable scalar kinds, constraints and explicit null values', () => {
  const p = parameters()
  expect(p.isStringParameter(field({ oneOf: [{ type: 'string' }, { type: 'null' }] }))).toBe(true)
  expect(p.isBooleanParameter(field({ type: 'boolean' }))).toBe(true)
  const nullableBoolean = field({ type: ['boolean', 'null'] })
  expect(p.isBooleanParameter(nullableBoolean)).toBe(false)
  expect(p.isJsonParameter(nullableBoolean)).toBe(true)
  const numeric = field({ anyOf: [{ type: 'integer', minimum: 2, maximum: 8 }, { type: 'null' }] })
  expect(p.isNumberParameter(numeric)).toBe(true)
  expect(readWorkflowNumericParameterInputAttributes(numeric)).toEqual({ min: 2, max: 8, step: 1 })
  expect(parseWorkflowNumericDisplayValue(numeric, '')).toBeNull()
  expect(rowScalar({ anyOf: [{ type: 'string', minLength: 1 }, { type: 'null' }] })).toMatchObject({ type: 'string', minLength: 1, nullable: true })
})
