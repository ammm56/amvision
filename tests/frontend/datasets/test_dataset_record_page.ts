import { expect, it, vi, afterEach } from 'vitest'
import { flushPromises, shallowMount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { reactive } from 'vue'
import DatasetRecordPage from '../../../frontend/web-ui/src/modules/datasets/pages/DatasetRecordPage.vue'

const api = vi.hoisted(() => ({ getDatasetImportDetail: vi.fn(), getDatasetExportDetail: vi.fn(), getDatasetInfo: vi.fn(), getDatasetWorkspace: vi.fn(), apiRequest: vi.fn() }))
const route = reactive({ params: { datasetImportId: 'import-a', datasetExportId: '' } })
vi.mock('../../../frontend/web-ui/src/modules/datasets/services/dataset.service', () => api)
vi.mock('../../../frontend/web-ui/src/modules/datasets/services/dataset-workspace.service', () => api)
vi.mock('../../../frontend/web-ui/src/shared/api/http-client', () => ({ apiRequest: api.apiRequest }))
vi.mock('../../../frontend/web-ui/src/app/stores/session.store', () => ({ useSessionStore: () => ({ hasScopes: () => true }) }))
vi.mock('../../../frontend/web-ui/src/app/stores/feedback.store', () => ({ useFeedbackStore: () => ({ info: vi.fn() }) }))
vi.mock('vue-router', () => ({ useRoute: () => route, useRouter: () => ({ push: vi.fn() }) }))
const mountPage = (kind: 'imports' | 'exports') => shallowMount(DatasetRecordPage, { props: { kind }, global: {
  plugins: [createI18n({ legacy: false, locale: 'zh-CN', messages: {} })],
  stubs: { DatasetExportFiles: false, ResourceTable: { template: '<table><slot /></table>' } },
} })
afterEach(() => vi.clearAllMocks())
it('失败导入展示结构化错误，不把没有检查报告误报为没有错误', async () => {
  api.getDatasetImportDetail.mockResolvedValue({ dataset_import_id: 'import-a', dataset_id: 'd', project_id: 'p', status: 'failed', metadata: {}, class_map: {}, detected_profile: {}, package_path: 'bad.zip', validation_report: { error: { code: 'INVALID_FORMAT', message: '标注格式无效' } } })
  api.getDatasetInfo.mockRejectedValue(new Error('unavailable'))
  const wrapper = mountPage('imports')
  await flushPromises()
  expect(wrapper.text()).toContain('标注格式无效')
  expect(wrapper.text()).not.toContain('报告中没有错误或警告')
  expect(wrapper.text()).not.toContain('检查通过')
  wrapper.unmount()
})
it('数据集信息不可用时仍加载导出文件；切换记录不会复用旧分页和文件', async () => {
  route.params.datasetExportId = 'export-a'
  api.getDatasetExportDetail.mockImplementation(async (id: string) => ({ dataset_export_id: id, dataset_id: 'd', project_id: 'p', status: 'completed', metadata: {}, category_names: ['a'], split_names: [], sample_count: 1 }))
  api.getDatasetInfo.mockRejectedValue(new Error('unavailable'))
  api.apiRequest.mockResolvedValue({ items: [{ path: 'data.yaml', name: 'data.yaml', directory: false, size: 10 }], next_cursor: null })
  const wrapper = mountPage('exports')
  await flushPromises()
  expect(wrapper.text()).toContain('data.yaml')
  route.params.datasetExportId = 'export-b'
  await flushPromises()
  expect(api.apiRequest).toHaveBeenLastCalledWith('/datasets/exports/export-b/files', { query: { path: '', after: '' }, signal: expect.any(AbortSignal) })
  wrapper.unmount()
})
