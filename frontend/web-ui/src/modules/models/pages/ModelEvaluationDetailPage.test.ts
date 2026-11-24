import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'

import { getDatasetExportDetail, listDatasetExports, type DatasetExportSummary } from '@/modules/datasets/services/dataset.service'
import { getDatasetWorkspace } from '@/modules/datasets/services/dataset-workspace.service'
import { i18n } from '@/platform/i18n'
import { getModelEvaluation, getModelEvaluationReport, type ModelEvaluationRecord } from '../services/model-evaluation.service'
import ModelEvaluationDetailPage from './ModelEvaluationDetailPage.vue'

vi.mock('vue-router', () => ({
  useRoute: () => ({ params: { taskType: 'classification', taskId: 'task-1' } }),
}))
vi.mock('@/app/stores/session.store', () => ({ useSessionStore: () => ({ hasScopes: () => true }) }))
vi.mock('../composables/useCatalogVersionLabel', () => ({ useCatalogVersionLabel: () => ref('托盘分类模型 · v3') }))
vi.mock('@/modules/datasets/services/dataset.service', () => ({ getDatasetExportDetail: vi.fn(), listDatasetExports: vi.fn() }))
vi.mock('@/modules/datasets/services/dataset-workspace.service', () => ({ getDatasetWorkspace: vi.fn() }))
vi.mock('../services/model-evaluation.service', async importOriginal => ({
  ...await importOriginal<typeof import('../services/model-evaluation.service')>(),
  getModelEvaluation: vi.fn(),
  getModelEvaluationReport: vi.fn(),
}))

enableAutoUnmount(afterEach)

const datasetExport: DatasetExportSummary = {
  dataset_export_id: 'dataset-export-z', dataset_id: 'dataset-1', dataset_version_id: 'dataset-version-1',
  project_id: 'project-1', format_id: 'imagenet-classification-v1', task_type: 'classification',
  status: 'completed', created_at: '2026-11-24T05:42:00Z', include_test_split: true, split_names: ['test'],
  sample_count: 96, category_names: ['ok', 'ng'], metadata: {},
}
const task: ModelEvaluationRecord = {
  task_id: 'task-1', display_name: 'classification evaluation dataset-export-z', project_id: 'project-1',
  state: 'succeeded', created_at: datasetExport.created_at, finished_at: '2026-11-24T05:42:18Z', sample_count: 96,
  metadata: { dataset_export_id: datasetExport.dataset_export_id, dataset_version_id: datasetExport.dataset_version_id },
}

async function renderReport() {
  const wrapper = mount(ModelEvaluationDetailPage, {
    global: { plugins: [i18n], stubs: ['RouterLink', 'ModelEvaluationSamplePreview'] },
  })
  await flushPromises()
  return wrapper
}

describe('Classification evaluation report labels', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(getModelEvaluation).mockResolvedValue(task)
    vi.mocked(getModelEvaluationReport).mockResolvedValue({
      file_status: 'ready', payload: { split_name: 'test', sample_count: 96, top1_accuracy: 1 },
    })
    vi.mocked(getDatasetExportDetail).mockResolvedValue(datasetExport)
    vi.mocked(listDatasetExports).mockResolvedValue([datasetExport, { ...datasetExport, dataset_export_id: 'dataset-export-a' }])
    vi.mocked(getDatasetWorkspace).mockResolvedValue({
      display_name: '托盘测试集', version_number: 2,
    } as Awaited<ReturnType<typeof getDatasetWorkspace>>)
  })

  it('labels an existing default-named task using the model and the exact dataset export', async () => {
    const wrapper = await renderReport()
    expect(wrapper.get('h1').text()).toBe('图像分类评估 · 托盘分类模型 · v3')
    const context = wrapper.get('.classification-report-context')
    expect(context.findAll('dt').map(term => term.text())).toEqual(['模型版本', '数据集导出', '评估范围', '完成时间'])
    expect(context.text()).toMatch(/托盘测试集 · v2 · ImageNet · .* · #2/)
    expect(context.text()).toContain('test · 96 张')
    expect(wrapper.text()).toContain('100%')
    expect(wrapper.text()).not.toContain('dataset-export-z')
    expect(context.text()).not.toContain('dataset-version-1')
    expect(getDatasetExportDetail).toHaveBeenCalledWith('dataset-export-z', expect.any(AbortSignal))
  })

  it('preserves a custom task title and displays the metrics if the export is unavailable', async () => {
    vi.mocked(getModelEvaluation).mockResolvedValue({ ...task, display_name: '产线测试复核' })
    vi.mocked(getDatasetExportDetail).mockRejectedValue(new Error('Export unavailable'))
    const wrapper = await renderReport()
    expect(wrapper.get('h1').text()).toBe('产线测试复核')
    expect(wrapper.get('.classification-report-context').text()).toContain('数据集信息暂不可用')
    expect(wrapper.get('.classification-report-context').text()).not.toContain('dataset-version-1')
    expect(wrapper.text()).toContain('100%')
  })

  it.each([
    [1, '100%'],
    [0, '0%'],
    [0.979, '97.9%'],
    [0.97846, '97.85%'],
    [undefined, '—'],
  ] as const)('formats Top-1 accuracy %s as %s', async (accuracy, label) => {
    vi.mocked(getModelEvaluationReport).mockResolvedValue({
      file_status: 'ready', payload: { split_name: 'test', sample_count: 96, top1_accuracy: accuracy },
    })
    const wrapper = await renderReport()
    const top1 = wrapper.findAll('.report-metrics > div').find(metric => metric.get('dt').text() === 'Top-1')
    expect(top1?.get('dd').text()).toBe(label)
  })
})
