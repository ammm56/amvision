import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { i18n } from '@/platform/i18n'
import DetectionEvaluationPanel from '@/modules/models/components/DetectionEvaluationPanel.vue'
import { listDetectionEvaluations, type DetectionEvaluationTask } from '@/modules/models/services/model-evaluation.service'

vi.mock('vue-router', () => ({
  useRoute: () => ({ query: {} }),
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
}))

vi.mock('@/modules/datasets/services/dataset.service', () => ({
  getDatasetExportDetail: vi.fn(),
  listProjectDatasetExports: vi.fn().mockResolvedValue([]),
}))

vi.mock('@/modules/datasets/services/dataset-workspace.service', () => ({
  getDatasetWorkspace: vi.fn(),
  listDatasetRecordPage: vi.fn().mockResolvedValue({ items: [] }),
}))

vi.mock('@/modules/models/services/model.service', () => ({
  listDeploymentSourceModels: vi.fn().mockResolvedValue([]),
}))

vi.mock('@/modules/models/model-display-name', () => ({
  modelDisplayName: (model: { model_name: string }) => model.model_name,
  modelVersionDisplayName: (version: { version_number?: number }) => `v${version.version_number ?? 1}`,
  readCatalogVersionNames: vi.fn().mockResolvedValue(new Map()),
}))

vi.mock('@/modules/models/evaluation-dataset-exports', () => ({
  readEvaluationDatasetVersionNames: vi.fn().mockResolvedValue(new Map()),
}))

vi.mock('@/modules/models/services/model-evaluation.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/modules/models/services/model-evaluation.service')>()),
  listDetectionEvaluations: vi.fn(),
}))

enableAutoUnmount(afterEach)

const succeededTask: DetectionEvaluationTask = {
  task_id: 'eval-1',
  display_name: 'det eval 1',
  state: 'succeeded',
  project_id: 'project-1',
  model_version_id: 'mv-1',
  dataset_export_id: 'exp-1',
  model_type: 'yolo11',
  created_at: '2026-11-24T00:00:00Z',
  report_object_key: 'reports/eval-1.json',
  map50_95: 0.812,
  progress: {},
  report_summary: { split_name: 'val', sample_count: 24 },
} as DetectionEvaluationTask

describe('DetectionEvaluationPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(listDetectionEvaluations).mockResolvedValue([succeededTask])
  })

  it('hides the bulk selection bar when 0 items are selected and shows it when selected', async () => {
    const wrapper = mount(DetectionEvaluationPanel, {
      props: { projectId: 'project-1', zh: true, canWrite: true },
      global: { plugins: [i18n], stubs: ['ButtonLink', 'Select', 'DetectionEvaluationComparison', 'ConfirmDialog'] },
    })
    await flushPromises()

    expect(wrapper.find('.evaluation-selection').exists()).toBe(false)
    expect(wrapper.find('.evaluation-toolbar__end').text()).not.toContain('创建评估')

    await wrapper.get('input[type="checkbox"]').setValue(true)
    await flushPromises()

    expect(wrapper.find('.evaluation-selection').exists()).toBe(true)
    expect(wrapper.get('.evaluation-selection').text()).toContain('已选 1 项')
  })

  it('exposes openCreate to launch the evaluation wizard from the top navigation action', async () => {
    const wrapper = mount(DetectionEvaluationPanel, {
      props: { projectId: 'project-1', zh: true, canWrite: true },
      global: { plugins: [i18n], stubs: ['ButtonLink', 'Select', 'DetectionEvaluationComparison', 'ConfirmDialog'] },
    })
    await flushPromises()

    const vm = wrapper.vm as unknown as { openCreate: () => Promise<void> }
    await vm.openCreate()
    await flushPromises()

    expect(wrapper.emitted('focusMode')).toContainEqual([true])
    expect(wrapper.find('ol.evaluation-steps').exists()).toBe(true)
  })
})
