import { computed, defineComponent } from 'vue'
import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useWorkflowNewAppDraft } from '@/workflows/workflow-editor/documents/useWorkflowNewAppDraft'
import { useWorkflowVersionHistory } from '@/workflows/workflow-editor/documents/useWorkflowVersionHistory'
import { listWorkflowAppVersions, getWorkflowAppVersion, renameWorkflowAppVersion, deleteWorkflowAppVersion } from '@/workflows/workflow-editor/services/workflow-application.service'
import type { WorkflowAppVersion } from '@/workflows/workflow-editor/types'
vi.mock('@/workflows/workflow-editor/services/workflow-application.service', () => ({ listWorkflowAppVersions: vi.fn(), getWorkflowAppVersion: vi.fn(), renameWorkflowAppVersion: vi.fn(), deleteWorkflowAppVersion: vi.fn() }))
const version = (number: number, state = 'published') => ({ workflow_app_version_id: `v${number}`, version_number: number, display_version: `v${number}`, state }) as WorkflowAppVersion
const page = (items: WorkflowAppVersion[], nextOffset: number | null = null) => ({ items, pagination: { offset: 0, limit: 25, totalCount: items.length, hasMore: nextOffset !== null, nextOffset } })
function setup() {
  const loadDocument = vi.fn()
  let history!: ReturnType<typeof useWorkflowVersionHistory>
  const wrapper = mount(defineComponent({ setup() { history = useWorkflowVersionHistory({ readTarget: () => ({ projectId: 'p', applicationId: 'a' }), loadDocument, readError: e => String(e) }); return () => null } }))
  return { history, wrapper, loadDocument }
}
beforeEach(() => vi.resetAllMocks())
describe('version history', () => {
  it('keeps the current list visible when switching back during refresh', async () => {
    vi.mocked(listWorkflowAppVersions).mockResolvedValueOnce(page([version(1)]))
    const { history, wrapper } = setup()
    await history.show()
    history.close()
    let resolve!: (value: ReturnType<typeof page>) => void
    vi.mocked(listWorkflowAppVersions).mockImplementationOnce(() => new Promise(done => { resolve = done }))
    const refreshing = history.show()
    expect(history.versions.value.map(item => item.version_number)).toEqual([1])
    expect(history.loading.value).toBe(true)
    resolve(page([version(2), version(1)]))
    await refreshing
    expect(history.versions.value.map(item => item.version_number)).toEqual([2, 1])
    wrapper.unmount()
  })
  it('paginates, deduplicates, sorts and excludes unpublished entries', async () => {
    vi.mocked(listWorkflowAppVersions).mockResolvedValueOnce(page([version(3), version(2, 'archived'), version(4, 'failed')], 25)).mockResolvedValueOnce(page([version(2), version(1)]))
    const { history, wrapper } = setup()
    await history.show()
    expect(history.versions.value.map(v => v.version_number)).toEqual([3, 2])
    await history.refresh(true)
    expect(listWorkflowAppVersions).toHaveBeenLastCalledWith('p', 'a', { offset: 25, limit: 25 })
    expect(history.versions.value.map(v => v.version_number)).toEqual([3, 2, 1])
    expect(history.nextOffset.value).toBeNull()
    wrapper.unmount()
  })
  it('directly loads an archived complete snapshot without writing version state', async () => {
    vi.mocked(listWorkflowAppVersions).mockResolvedValue(page([version(1, 'archived')]))
    const app = useWorkflowNewAppDraft({ isNewApp: computed(() => true), selectedProjectId: computed(() => 'p'), readNodeCount: () => 0, translate: k => k }).createLocalWorkflowAppDraft()
    vi.mocked(getWorkflowAppVersion).mockResolvedValue({ ...version(1, 'archived'), application: app.applicationDocument.application, template: app.graphDocument.template } as never)
    const { history, wrapper, loadDocument } = setup()
    await history.show()
    await history.select(version(1, 'archived'))
    expect(loadDocument).toHaveBeenCalledOnce()
    expect(loadDocument.mock.calls[0]![0].template).toEqual(app.graphDocument.template)
    expect(history.open.value).toBe(true)
    expect(getWorkflowAppVersion).toHaveBeenCalledWith('p', 'a', 'v1')
    wrapper.unmount()
  })
  it('does not apply a late detail response after closing or unmounting', async () => {
    vi.mocked(listWorkflowAppVersions).mockResolvedValue(page([version(1)]))
    let resolve!: (value: never) => void
    vi.mocked(getWorkflowAppVersion).mockImplementation(() => new Promise(done => { resolve = done }))
    const { history, wrapper, loadDocument } = setup()
    await history.show()
    const request = history.select(version(1))
    history.close()
    resolve({ application: {}, template: {} } as never)
    await request
    expect(loadDocument).not.toHaveBeenCalled()
    expect(history.open.value).toBe(false)
    wrapper.unmount()
  })
  it('keeps the panel and original graph on malformed detail or server failure', async () => {
    vi.mocked(listWorkflowAppVersions).mockResolvedValue(page([version(1, 'archived')]))
    vi.mocked(getWorkflowAppVersion).mockResolvedValue({ application: {}, template: {} } as never)
    const { history, wrapper, loadDocument } = setup()
    await history.show()
    await history.select(version(1, 'archived'))
    expect(history.open.value).toBe(true)
    expect(history.error.value).toContain('format_id')
    expect(loadDocument).not.toHaveBeenCalled()
    expect(history.loading.value).toBe(false)
    wrapper.unmount()
  })
})


describe('history menu requests', () => {
  it('renames without loading or changing the graph', async () => {
    vi.mocked(listWorkflowAppVersions).mockResolvedValue(page([version(1)]))
    vi.mocked(renameWorkflowAppVersion).mockResolvedValue({ ...version(1), display_version: 'Baseline' })
    const { history, wrapper, loadDocument } = setup()
    await history.show()
    expect(await history.act(version(1), 'rename', '  Baseline  ', 'Updated notes')).toBe(true)
    expect(renameWorkflowAppVersion).toHaveBeenCalledWith('p', 'a', 'v1', 'Baseline', 'Updated notes')
    expect(history.versions.value[0]?.display_version).toBe('Baseline')
    expect(loadDocument).not.toHaveBeenCalled()
    wrapper.unmount()
  })
  it('keeps a referenced version on failed deletion and resets pagination after success', async () => {
    vi.mocked(listWorkflowAppVersions).mockResolvedValueOnce(page([version(2), version(1)], 25)).mockResolvedValueOnce(page([version(1)]))
    vi.mocked(deleteWorkflowAppVersion).mockRejectedValueOnce(new Error('Runtime reference')).mockResolvedValueOnce(undefined)
    const { history, wrapper, loadDocument } = setup()
    await history.show()
    expect(await history.act(version(2), 'delete')).toBe(false)
    expect(history.error.value).toContain('Runtime reference')
    expect(history.versions.value).toHaveLength(2)
    expect(await history.act(version(2), 'delete')).toBe(true)
    expect(listWorkflowAppVersions).toHaveBeenLastCalledWith('p', 'a', { offset: 0, limit: 25 })
    expect(history.nextOffset.value).toBeNull()
    expect(history.versions.value.map(v => v.version_number)).toEqual([1])
    expect(loadDocument).not.toHaveBeenCalled()
    wrapper.unmount()
  })
  it('exports the selected immutable snapshot and never loads it into the editor', async () => {
    const source = useWorkflowNewAppDraft({ isNewApp: computed(() => true), selectedProjectId: computed(() => 'p'), readNodeCount: () => 0, translate: k => k }).createLocalWorkflowAppDraft()
    source.applicationDocument.application.display_name = 'Historical source'
    vi.mocked(listWorkflowAppVersions).mockResolvedValue(page([version(1)]))
    vi.mocked(getWorkflowAppVersion).mockResolvedValue({ ...version(1), application: source.applicationDocument.application, template: source.graphDocument.template } as never)
    let blob!: Blob
    vi.stubGlobal('URL', { createObjectURL: (value: Blob) => { blob = value; return 'blob:history' }, revokeObjectURL: vi.fn() })
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined)
    const { history, wrapper, loadDocument } = setup()
    await history.show()
    expect(await history.act(version(1), 'export')).toBe(true)
    const content = await new Promise<string>(resolve => { const reader = new FileReader(); reader.onload = () => resolve(String(reader.result)); reader.readAsText(blob) })
    expect(JSON.parse(content).application.display_name).toBe('Historical source')
    expect(JSON.parse(content).application.metadata.project_id).toBeUndefined()
    expect(loadDocument).not.toHaveBeenCalled()
    wrapper.unmount(); click.mockRestore(); vi.unstubAllGlobals()
  })
})
