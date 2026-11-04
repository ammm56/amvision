import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { ref } from 'vue'
import GeometrySettingsEditor from '../../../custom_nodes/metrology3d_nodes/frontend/GeometrySettingsEditor.vue'
import MeasurementSettingsEditor from '../../../custom_nodes/metrology3d_nodes/frontend/MeasurementSettingsEditor.vue'
import BoundarySettingsEditor from '../../../custom_nodes/metrology3d_nodes/frontend/BoundarySettingsEditor.vue'
import DimensionSettingsEditor from '../../../custom_nodes/metrology3d_nodes/frontend/DimensionSettingsEditor.vue'
import template from '../../../docs/examples/workflows/lithium_workpiece.template.json'
import { newMeasurement } from '../../../custom_nodes/metrology3d_nodes/frontend/measurement-form'
import { parameterCloudPreviewsKey, parameterPreviewStateKey } from '@/workflows/workflow-editor/parameters/editor-context'

vi.mock('@/workflows/workflow-editor/point-cloud/CloudViewer.vue', () => ({
  __esModule: true,
  default: { props: ['payload'], template: '<div data-cloud />' },
}))

afterEach(() => { document.body.innerHTML = ''; vi.clearAllMocks() })

const cases = [
  ['fit-plane', GeometrySettingsEditor], ['build-frame', GeometrySettingsEditor],
  ['height-query', MeasurementSettingsEditor], ['measure-step', MeasurementSettingsEditor],
  ['extract-boundary', BoundarySettingsEditor], ['fit-circle', BoundarySettingsEditor],
  ['measure-extents', DimensionSettingsEditor], ['measure-hole', DimensionSettingsEditor],
] as const

function settings(kind: string) {
  const node = template.nodes.find(node => node.node_type_id === `custom.metrology3d.${kind}`)
  return node ? structuredClone(node.parameters.settings) : newMeasurement(true)
}

it.each(cases)('%s isolates changed upstream identity without closing an equivalent source refresh', async (kind, editor) => {
  const value = settings(kind), before = JSON.stringify(value)
  const sources = { features: [{ nodeId: 'source-a', nodeTypeId: 'custom.metrology3d.fit-plane', outputPort: 'features', parameters: { settings: { feature_id: 'datum' } } }] }
  const state = ref({ runId: 'run-a', succeeded: true })
  const views = [{ id: 'cloud', label: 'Current cloud', projectId: 'project-1', payload: { state: 'ready' } }]
  const wrapper = mount(editor, {
    props: { modelValue: value, nodeType: `custom.metrology3d.${kind}`, inputSources: sources },
    attachTo: document.body,
    global: {
      plugins: [createI18n({ legacy: false, locale: 'en-US' })],
      provide: { [parameterCloudPreviewsKey as symbol]: () => views, [parameterPreviewStateKey as symbol]: () => state.value },
    },
  })
  try {
    await wrapper.get('button').trigger('click'); await flushPromises()
    expect(document.querySelector('[role=dialog]')).not.toBeNull()
    await wrapper.setProps({ inputSources: structuredClone(sources) }); await flushPromises()
    expect(document.querySelector('[role=dialog]')).not.toBeNull()
    const select = [...document.querySelectorAll('select')].find(input => [...input.options].some(option => option.value === 'cloud'))!
    select.value = 'cloud'; select.dispatchEvent(new Event('change', { bubbles: true })); await flushPromises()
    expect(document.querySelector('[data-cloud]')).not.toBeNull()
    await wrapper.setProps({ inputSources: { features: [{ ...sources.features[0]!, nodeId: 'source-b' }] } }); await flushPromises()
    expect(document.querySelector('[role=dialog]')).toBeNull()
    expect(document.querySelector('[data-cloud]')).toBeNull()
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
    expect(JSON.stringify(value)).toBe(before)
    await wrapper.get('button').trigger('click'); await flushPromises()
    expect(document.querySelector('[data-cloud]')).toBeNull()
    const reopenedSelect = [...document.querySelectorAll('select')].find(input => [...input.options].some(option => option.value === 'cloud'))!
    reopenedSelect.value = 'cloud'; reopenedSelect.dispatchEvent(new Event('change', { bubbles: true })); await flushPromises()
    expect(document.querySelector('[data-cloud]')).not.toBeNull()
    state.value = { runId: 'run-b', succeeded: false }; await flushPromises()
    expect(document.querySelector('[data-cloud]')).toBeNull()
  } finally { wrapper.unmount() }
  expect(document.querySelector('[role=dialog]')).toBeNull()
})
