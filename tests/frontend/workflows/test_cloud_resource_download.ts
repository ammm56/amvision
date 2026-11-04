import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { reactive } from 'vue'
import CloudResourcePicker from '@/workflows/workflow-editor/point-cloud/CloudResourcePicker.vue'
import CloudResourceParameter from '@/workflows/workflow-editor/point-cloud/CloudResourceParameter.vue'

const mocks = vi.hoisted(() => ({ project: {} as { selectedProjectId: string }, request: vi.fn(), list: vi.fn(), capability: vi.fn() }))
vi.mock('@/app/stores/project.store', () => ({ useProjectStore: () => mocks.project }))
vi.mock('@/shared/api/http-client', () => ({ apiRequest: mocks.request }))
vi.mock('@/workflows/workflow-editor/services/measurement-resource.service', async original => ({
  ...await original<typeof import('@/workflows/workflow-editor/services/measurement-resource.service')>(),
  listMeasurementResources: mocks.list, readCloudCapabilities: mocks.capability,
}))
const reference = { project_id: 'p', resource_id: 'cloud-1', kind: 'point-cloud', version: 2, sha256: 'a'.repeat(64) } as const
const document = { reference, name: 'Workpiece', content: { point_cloud: { point_count: 14745099, spatial: { length_unit: 'mm' }, fields: [{ name: 'positions', dtype: 'float32', components: 3 }] } } }
const dialog = { props: ['title', 'confirmDisabled', 'showConfirm'], emits: ['confirm', 'cancel'], template: '<div role="dialog"><h2>{{ title }}</h2><slot/><button @click="$emit(\'cancel\')">Cancel</button><button :disabled="confirmDisabled" @click="$emit(\'confirm\')">Apply</button></div>' }
const global = () => ({ plugins: [createI18n({ legacy: false, locale: 'en-US' })], stubs: { Teleport: true, ConfirmDialog: dialog } })
let wrappers: ReturnType<typeof mount>[] = []
const createUrl = vi.fn(), revokeUrl = vi.fn()
beforeEach(() => {
  mocks.project = reactive({ selectedProjectId: 'p' })
  mocks.list.mockResolvedValue([document])
  mocks.capability.mockResolvedValue({ max_archive_bytes: 1024 })
  createUrl.mockReturnValue('blob:download')
  vi.stubGlobal('URL', Object.assign(class extends URL {}, { createObjectURL: createUrl, revokeObjectURL: revokeUrl }))
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
})
afterEach(() => { for (const w of wrappers) w.unmount(); wrappers = []; vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.resetAllMocks() })
async function open() {
  const w = mount(CloudResourcePicker, { props: { modelValue: reference }, global: global() }); wrappers.push(w)
  await w.get('button').trigger('click'); await flushPromises(); return w
}

it.each(['close', 'project', 'reference', 'disabled', 'unmount'])('ignores a late export after %s', async change => {
  let resolve!: (blob: Blob) => void
  mocks.request.mockImplementation(() => new Promise(r => { resolve = r }))
  const w = await open()
  await w.get('button[title="Export package"]').trigger('click')
  const signal = mocks.request.mock.calls[0]![1].signal
  if (change === 'close') await w.findAll('button').find(b => b.text() === 'Cancel')!.trigger('click')
  if (change === 'project') mocks.project.selectedProjectId = 'other'
  if (change === 'reference') await w.setProps({ modelValue: { ...reference, version: 3 } })
  if (change === 'disabled') await w.setProps({ disabled: true })
  if (change === 'unmount') { w.unmount(); wrappers = [] }
  await flushPromises(); expect(signal.aborted).toBe(true)
  resolve(new Blob(['zip'])); await flushPromises()
  expect(createUrl).not.toHaveBeenCalled()
  expect(w.emitted('update:modelValue')).toBeUndefined()
})

it('downloads the selected immutable version and releases both replaced and closed blob URLs', async () => {
  mocks.request.mockResolvedValue(new Blob(['zip']))
  const w = await open()
  for (let i = 0; i < 2; i++) { await w.get('button[title="Export package"]').trigger('click'); await flushPromises() }
  expect(mocks.request.mock.calls[0]![0]).toBe('/workflows/projects/p/measurement-resources/cloud-1/versions/2/export')
  expect(mocks.request.mock.calls[0]![1]).toMatchObject({ responseType: 'blob', retryTransientRead: false })
  expect(revokeUrl).toHaveBeenCalledTimes(1)
  await w.findAll('button').find(b => b.text() === 'Cancel')!.trigger('click')
  expect(revokeUrl).toHaveBeenCalledTimes(2)
  await w.get('button').trigger('click'); await flushPromises()
  expect(w.get('input[type=radio]').element).toHaveProperty('checked', true)
})

it('keeps the chosen version after an export failure without creating a download', async () => {
  mocks.request.mockRejectedValue(new Error('Archive budget exceeded'))
  const w = await open()
  await w.get('button[title="Export package"]').trigger('click'); await flushPromises()
  expect(w.get('[role=alert]').text()).toBe('Archive budget exceeded')
  expect(w.get('input[type=radio]').element).toHaveProperty('checked', true)
  expect(createUrl).not.toHaveBeenCalled()
})

it('keeps the save target name and exact reference when selecting a new resource version', async () => {
  const w = mount(CloudResourceParameter, { props: { modelValue: { kind: 'new', name: 'Saved workpiece' }, schema: { 'x-ui-widget': 'cloud-target' } }, global: global() }); wrappers.push(w)
  await w.get('select').setValue('new-version'); await flushPromises()
  expect(w.emitted('update:modelValue')).toBeUndefined()
  await w.get('input[type=radio]').setValue(true)
  await w.findAll('button').find(b => b.text() === 'Apply')!.trigger('click')
  expect(w.emitted('update:modelValue')).toEqual([[{ kind: 'new-version', name: 'Saved workpiece', reference }]])
})
