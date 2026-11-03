import { afterEach, expect, it, vi } from 'vitest'
import { effectScope, ref } from 'vue'
import { mount } from '@vue/test-utils'
import { i18n } from '@/platform/i18n'
import WorkflowGraphOverlayLayer from '@/workflows/workflow-editor/components/WorkflowGraphOverlayLayer.vue'
import { useWorkflowCloudPackage } from '@/workflows/workflow-editor/documents/useWorkflowCloudPackage'
import { apiRequest } from '@/shared/api/http-client'
import { readCloudCapabilities } from '@/workflows/workflow-editor/services/measurement-resource.service'
import type { WorkflowAppDocumentV1 } from '@/workflows/workflow-editor/documents/workflow-app-document'

vi.mock('@/shared/api/http-client', () => ({ apiRequest: vi.fn() }))
vi.mock('@/workflows/workflow-editor/services/measurement-resource.service', () => ({ readCloudCapabilities: vi.fn() }))
const scopes: ReturnType<typeof effectScope>[] = []
afterEach(() => { scopes.splice(0).forEach(s => s.stop()); vi.resetAllMocks() })
function setup() {
  const scope = effectScope(); scopes.push(scope)
  const context = ref('project/editor'), onImported = vi.fn(), onExported = vi.fn(), onError = vi.fn()
  const actions = scope.run(() => useWorkflowCloudPackage({ context: () => context.value, project: () => 'project',
    onImported, onExported, onError, capacityError: () => 'capacity' }))!
  vi.mocked(readCloudCapabilities).mockResolvedValue({ max_archive_bytes: 100, renderer: null })
  return { scope, context, onImported, onExported, onError, actions }
}
const document = {} as WorkflowAppDocumentV1
const file = new File(['zip'], 'recipe.zip')

it('forwards both package menu commands through the actual overlay and respects busy state', async () => {
  const wrapper = mount(WorkflowGraphOverlayLayer, { global: { plugins: [i18n] }, props: {
    minimapVisible: false, viewportScalePercent: 100, minimapNodes: [], minimapViewportStyle: {},
    isMinimapNodeSelected: () => false, contextMenu: {x: 10, y: 10, worldX: 0, worldY: 0, nodeId: null, edgeId: null, port: null},
    contextMenuStyle: {}, saveDisabled: false, previewDisabled: false, documentDisabled: false,
    nodePicker: null, nodePickerDefinitions: [], nodePickerTitle: '', nodePickerRequiredPortDirection: null,
    nodePickerRequiredPayloadTypeId: null, nodeCount: 3,
  } })
  try {
    const buttons = wrapper.findAll('button')
    const exportButton = buttons.find(b => b.text() === i18n.global.t('workflowEditor.document.exportPackage'))!
    const importButton = buttons.find(b => b.text() === i18n.global.t('workflowEditor.document.importPackage'))!
    await exportButton.trigger('click'); await importButton.trigger('click')
    expect(wrapper.emitted('exportPackage')).toHaveLength(1)
    expect(wrapper.emitted('importPackage')).toHaveLength(1)
    await wrapper.setProps({ documentDisabled: true })
    expect(exportButton.attributes('disabled')).toBeDefined()
    expect(importButton.attributes('disabled')).toBeDefined()
  } finally { wrapper.unmount() }
})

it('uploads once with an explicit request identity and opens only the created app', async () => {
  const h = setup(), result = { application_id: 'new-app', template_id: 'new-template', resource_mapping: [] }
  vi.mocked(apiRequest).mockResolvedValue(result)
  await h.actions.importPackage(file)
  expect(h.onImported).toHaveBeenCalledWith(result)
  expect(apiRequest).toHaveBeenCalledOnce()
  expect(vi.mocked(apiRequest).mock.calls[0]![1]).toMatchObject({ body: file, retryOnUnauthorized: false,
    headers: { 'Content-Type': 'application/zip', 'Idempotency-Key': expect.any(String) } })
  expect(h.actions.busy.value).toBe(false)
})
it.each(['route', 'dispose', 'cancel'])('ignores late successful imports after %s', async mode => {
  const h = setup()
  let resolve!: (value: unknown) => void
  vi.mocked(apiRequest).mockImplementation(() => new Promise(r => { resolve = r }))
  const pending = h.actions.importPackage(file)
  await vi.waitFor(() => expect(apiRequest).toHaveBeenCalledOnce())
  if (mode === 'route') h.context.value = 'other/editor'
  else if (mode === 'dispose') h.scope.stop()
  else h.actions.cancel()
  expect(vi.mocked(apiRequest).mock.calls[0]![1]!.signal!.aborted).toBe(true)
  resolve({ application_id: 'old' }); await pending
  expect(h.onImported).not.toHaveBeenCalled(); expect(h.onError).not.toHaveBeenCalled()
})
it('does not send an upload after late capabilities from an old project', async () => {
  const h = setup()
  let resolve!: (value: any) => void
  vi.mocked(readCloudCapabilities).mockImplementation(() => new Promise(r => { resolve = r }))
  const pending = h.actions.importPackage(file)
  h.context.value = 'other'
  resolve({ max_archive_bytes: 100 }); await pending
  expect(apiRequest).not.toHaveBeenCalled(); expect(h.onError).not.toHaveBeenCalled()
})
it('rejects empty, unconfigured and oversized inputs without upload', async () => {
  const h = setup()
  await h.actions.importPackage(new File([], 'empty.zip'))
  await h.actions.importPackage(new File(['x'.repeat(101)], 'big.zip'))
  vi.mocked(readCloudCapabilities).mockResolvedValue({ max_archive_bytes: null, renderer: null })
  await h.actions.importPackage(file)
  expect(h.onError).toHaveBeenCalledTimes(3); expect(apiRequest).not.toHaveBeenCalled()
})
it('blocks duplicate transfers and does not let an old request reset a new busy state', async () => {
  const h = setup(), resolves: ((v: any) => void)[] = []
  vi.mocked(apiRequest).mockImplementation(() => new Promise(r => resolves.push(r)))
  const first = h.actions.exportPackage(document)
  await h.actions.exportPackage(document)
  expect(apiRequest).toHaveBeenCalledOnce()
  h.actions.cancel()
  const second = h.actions.exportPackage(document)
  resolves[0]!(new Blob()); await first
  expect(h.actions.busy.value).toBe(true); expect(h.onExported).not.toHaveBeenCalled()
  resolves[1]!(new Blob()); await second
  expect(h.onExported).toHaveBeenCalledOnce(); expect(h.actions.busy.value).toBe(false)
})
