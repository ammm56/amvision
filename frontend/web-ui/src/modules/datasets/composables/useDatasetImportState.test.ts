import { enableAutoUnmount, mount } from '@vue/test-utils'
import { defineComponent, ref } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useDatasetImportState } from './useDatasetImportState'
import { listProjectDatasetImports, listProjectDatasetVersions, type DatasetImportSummary, type DatasetVersionRelation } from '../services/dataset.service'
vi.mock('../services/dataset.service', () => ({ listProjectDatasetImports: vi.fn(), listProjectDatasetVersions: vi.fn(), submitDatasetImport: vi.fn() }))
enableAutoUnmount(afterEach)
const version: DatasetVersionRelation = { dataset_id: 'dataset-1', dataset_version_id: 'version-1', project_id: 'project-1', task_type: 'classification', sample_count: 1, category_count: 1, split_names: [], metadata: {} }
function setup() {
  const options = { selectedProjectId: ref('project-1'), importDatasetId: ref('dataset-1'), datasetId: ref('dataset-1'), datasetVersionId: ref('version-1'), formatType: ref('auto'), taskType: ref('classification'), imports: ref<DatasetImportSummary[]>([]), datasetVersions: ref([version]), errorMessage: ref<string | null>(null), createDatasetId: () => 'new', t: (key: string) => key }
  let state!: ReturnType<typeof useDatasetImportState>
  mount(defineComponent({ setup() { state = useDatasetImportState(options); return () => null } }))
  return { options, state }
}
describe('dataset refresh after deletion', () => {
  it('preserves a surviving version when imports disappear and clears the last deleted version', async () => {
    const { options, state } = setup()
    vi.mocked(listProjectDatasetImports).mockResolvedValue([])
    vi.mocked(listProjectDatasetVersions).mockResolvedValueOnce([version]).mockResolvedValueOnce([])
    await state.refreshImportRecords()
    expect(options.datasetVersionId.value).toBe('version-1')
    await state.refreshImportRecords()
    expect(options.datasetVersionId.value).toBe('')
    expect(options.datasetId.value).toBe('')
    expect(options.datasetVersions.value).toEqual([])
  })
  it('does not restore an older response over a newer deletion refresh', async () => {
    const { options, state } = setup()
    let resolve!: (rows: DatasetVersionRelation[]) => void
    vi.mocked(listProjectDatasetImports).mockResolvedValue([])
    vi.mocked(listProjectDatasetVersions).mockReturnValueOnce(new Promise(done => { resolve = done })).mockResolvedValueOnce([])
    const previous = state.refreshImportRecords()
    await state.refreshImportRecords()
    resolve([version])
    await previous
    expect(options.datasetVersions.value).toEqual([])
  })
  it('discards a response for the previous project', async () => {
    const { options, state } = setup()
    let resolve!: (rows: DatasetVersionRelation[]) => void
    vi.mocked(listProjectDatasetImports).mockResolvedValue([])
    vi.mocked(listProjectDatasetVersions).mockReturnValueOnce(new Promise(done => { resolve = done }))
    const previous = state.refreshImportRecords()
    options.selectedProjectId.value = 'project-2'
    resolve([version])
    await previous
    expect(options.datasetVersions.value).toEqual([])
    expect(options.datasetVersionId.value).toBe('')
  })
})
