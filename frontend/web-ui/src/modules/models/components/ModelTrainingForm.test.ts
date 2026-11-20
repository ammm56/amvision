import { flushPromises, shallowMount } from '@vue/test-utils'
import { ref } from 'vue'
import { describe, expect, it, vi } from 'vitest'

vi.mock('vue-i18n', async (importOriginal) => ({
  ...await importOriginal<typeof import('vue-i18n')>(),
  useI18n: () => ({ t: (key: string) => key, locale: ref('zh-CN') }),
}))
import ModelTrainingForm from './ModelTrainingForm.vue'
import { ApiError } from '@/shared/api/error'
import { getDatasetWorkspace } from '@/modules/datasets/services/dataset-workspace.service'

vi.mock('@/modules/datasets/services/dataset-workspace.service', () => ({ getDatasetWorkspace: vi.fn() }))

function mountWizard() {
  return shallowMount(ModelTrainingForm, {
    global: { stubs: { TrainingPreflightResults: false } },
    props: {
      selectedTaskType: 'detection', taskTypeOptions: [{ label: 'detection', value: 'detection' }],
      loading: false, baseModelsCount: 1, trainingDatasetExportsCount: 1,
      trainingSelectedModelSummary: null, selectedTrainingDatasetExport: null,
      trainingDeviceOptions: [], outputModelName: '', maxEpochs: 100, batchMode: 'auto',
      batchSize: 4, batchTargetMemoryFraction: 0.6, batchRecoverOnOom: true,
      batchMaxOomRetries: 3, trainingDevice: '', evaluationInterval: 1, ampMode: 'auto',
      ampDtype: 'auto', checkpointInterval: 5, inputWidth: 640, inputHeight: 640,
      trainingDisplayName: '', warmStartModelVersionId: '', trainingTaskSupportsWarmStart: true,
      trainingModelParameterFields: [], trainingAugmentationParameterFields: [],
      trainingAugmentationEnabled: true, trainingSupportsAugmentationToggle: false,
      trainingModelParameterValues: {}, trainingModelParameterSectionTitle: '', batchModeOptions: [],
      ampModeOptions: [], ampDtypeOptions: [], canWriteTasks: true, trainingSubmitting: false,
      lastTrainingSubmission: null,
    },
  })
}

describe('training wizard', () => {
  it('uses the selected dataset name and ignores an outdated workspace response', async () => {
    let finishOld!: (value: Awaited<ReturnType<typeof getDatasetWorkspace>>) => void
    vi.mocked(getDatasetWorkspace).mockImplementationOnce(() => new Promise(resolve => { finishOld = resolve }))
      .mockResolvedValueOnce({ dataset_id: 'dataset-b', dataset_version_id: 'version-b', version_number: 2, dataset: { display_name: '目标数据集' } } as never)
    const wrapper = mountWizard()
    await wrapper.setProps({ outputModelName: 'test', trainingSelectedModelSummary: { model_name: 'yolo' } as never,
      selectedTrainingDatasetExport: { dataset_export_id: 'a', dataset_id: 'dataset-a', dataset_version_id: 'version-a', category_names: [], metadata: {} } as never })
    await wrapper.find('form').trigger('submit')
    await wrapper.setProps({ selectedTrainingDatasetExport: { dataset_export_id: 'b', dataset_id: 'dataset-b', dataset_version_id: 'version-b', category_names: [], metadata: {} } as never })
    await flushPromises()
    finishOld({ dataset_id: 'dataset-a', dataset_version_id: 'version-a', version_number: 1, dataset: { display_name: '过期数据集' } } as never)
    await flushPromises()
    expect(wrapper.text()).toContain('目标数据集 · v2')
    expect(wrapper.text()).not.toContain('过期数据集')
  })

  it('keeps the export usable when its source name fails to load and permits retry', async () => {
    vi.mocked(getDatasetWorkspace).mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce({
      dataset_id: 'dataset-a', dataset_version_id: 'version-a', version_number: 3, dataset: { display_name: '恢复后的名称' },
    } as never)
    const wrapper = mountWizard()
    await wrapper.setProps({ outputModelName: 'test', trainingSelectedModelSummary: { model_name: 'yolo' } as never,
      selectedTrainingDatasetExport: { dataset_export_id: 'a', dataset_id: 'dataset-a', dataset_version_id: 'version-a', category_names: [], metadata: {} } as never })
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    expect(wrapper.text()).toContain('来源名称暂不可用')
    await wrapper.find('.training-retry').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('恢复后的名称 · v3')
    expect(wrapper.text()).not.toContain('来源名称暂不可用')
  })
  it('shows the selected export split counts without substituting the source dataset totals', async () => {
    const wrapper = mountWizard()
    await wrapper.setProps({ outputModelName: 'test', trainingSelectedModelSummary: { model_name: 'yolo' } as never,
      selectedTrainingDatasetExport: { dataset_export_id: 'e1', category_names: [], split_names: ['train', 'val'], metadata: { split_counts: { train: 20, val: 5 } } } as never })
    await wrapper.find('form').trigger('submit')
    const splits = wrapper.find('.training-splits')
    expect(splits.text()).toContain('训练集 (train)20')
    expect(splits.text()).toContain('验证集 (val)5')
    expect(splits.text()).toContain('测试集 (test)未包含')
    await wrapper.setProps({ selectedTrainingDatasetExport: { dataset_export_id: 'e2', category_names: [], split_names: ['train'], metadata: {} } as never })
    expect(splits.text()).toContain('训练集 (train)—')
  })

  it('keeps incompatible exports on the data step and allows advancing after correction', async () => {
    const wrapper = mountWizard()
    await wrapper.setProps({ outputModelName: 'test', trainingSelectedModelSummary: { model_name: 'yolo' } as never,
      selectedTrainingDatasetExport: { dataset_export_id: 'e1', category_names: [], split_names: [], metadata: {} } as never,
      selectionError: '数据格式不支持' })
    await wrapper.find('form').trigger('submit')
    expect(wrapper.text()).toContain('数据格式不支持')
    await wrapper.find('form').trigger('submit')
    expect(wrapper.text()).not.toContain('初始化方式')
    await wrapper.setProps({ selectionError: null })
    await wrapper.find('form').trigger('submit')
    expect(wrapper.text()).toContain('初始化方式')
  })
  it('checks model and data before advancing and submits only after review', async () => {
    const wrapper = mountWizard()
    await wrapper.find('form').trigger('submit')
    expect(wrapper.text()).toContain('请填写输出模型名称并选择模型')
    expect(wrapper.emitted('submit')).toBeUndefined()
    await wrapper.setProps({ outputModelName: 'test', trainingSelectedModelSummary: { model_name: 'yolo', model_id: 'm', model_type: 'yolo', model_scale: 's' } as never })
    await wrapper.find('form').trigger('submit')
    expect(wrapper.text()).toContain('modelOps.fields.trainingDatasetExport')
    await wrapper.find('form').trigger('submit')
    expect(wrapper.text()).toContain('请选择用于训练的数据集导出')
    await wrapper.setProps({ selectedTrainingDatasetExport: { dataset_export_id: 'e1', category_names: [], task_type: 'detection', format_id: 'yolo' } as never })
    await wrapper.find('form').trigger('submit')
    expect(wrapper.text()).toContain('初始化方式')
    expect(wrapper.text()).toContain('已取消的任务不能恢复')
    await wrapper.find('form').trigger('submit')
    expect(wrapper.text()).toContain('基础参数')
    expect(wrapper.text()).toContain('批次与精度')
    expect(wrapper.text()).toContain('保存设置')
    await wrapper.find('form').trigger('submit')
    expect(wrapper.text()).toContain('检查训练配置')
    expect(wrapper.text()).toContain('e1')
    expect(wrapper.emitted('submit')).toBeUndefined()
    await wrapper.find('form').trigger('submit')
    expect(wrapper.emitted('submit')).toHaveLength(1)
  })

  it('does not switch to weight initialization until a weight is selected', async () => {
    const wrapper = mountWizard()
    await wrapper.setProps({ outputModelName: 'test', trainingSelectedModelSummary: { model_name: 'yolo' } as never, selectedTrainingDatasetExport: { dataset_export_id: 'e1', category_names: [] } as never })
    await wrapper.find('form').trigger('submit')
    await wrapper.find('form').trigger('submit')
    const radio = wrapper.find('input[aria-label="使用权重初始化"]')
    await radio.trigger('click')
    expect(wrapper.emitted('open-training-weight-picker')).toHaveLength(1)
    expect((radio.element as HTMLInputElement).checked).toBe(false)
  })

  it('does not advance from invalid training parameters', async () => {
    const wrapper = mountWizard()
    await wrapper.setProps({ outputModelName: 'test', trainingSelectedModelSummary: { model_name: 'yolo' } as never,
      selectedTrainingDatasetExport: { dataset_export_id: 'e1', category_names: [] } as never })
    for (let i = 0; i < 3; i++) await wrapper.find('form').trigger('submit')
    await wrapper.setProps({ configurationError: '学习率超出范围' })
    await wrapper.find('form').trigger('submit')
    expect(wrapper.text()).toContain('学习率超出范围')
    expect(wrapper.text()).not.toContain('检查训练配置')
    await wrapper.setProps({ configurationError: null })
    await wrapper.find('form').trigger('submit')
    expect(wrapper.text()).toContain('检查训练配置')
  })

  it('blocks submission after a failed preflight and enables it after retry', async () => {
    const previewTraining = vi.fn().mockRejectedValueOnce(new Error('导出文件不存在')).mockResolvedValueOnce({})
    const wrapper = mountWizard()
    await wrapper.setProps({ previewTraining, outputModelName: 'test',
      trainingSelectedModelSummary: { model_name: 'yolo' } as never,
      selectedTrainingDatasetExport: { dataset_export_id: 'e1', category_names: [] } as never })
    for (let i = 0; i < 4; i++) await wrapper.find('form').trigger('submit')
    await flushPromises()
    expect(wrapper.text()).toContain('导出文件不存在')
    await wrapper.find('form').trigger('submit')
    expect(wrapper.emitted('submit')).toBeUndefined()
    await wrapper.get('.training-preflight__notice button-stub').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('检查通过')
    await wrapper.find('form').trigger('submit')
    expect(wrapper.emitted('submit')).toHaveLength(1)
  })

  it('shows independent failed checks, keeps the draft and takes the user to the affected step', async () => {
    const previewTraining = vi.fn().mockRejectedValue(new ApiError(400, {
      message: '导出无效',
      details: { checks: [
        { check: 'dataset_export', status: 'failed', missing_files: ['annotations/instances_val.json'] },
        { check: 'initialization', status: 'failed', message: '初始化权重文件摘要与登记值不一致' },
        { check: 'environment', status: 'deferred' },
        { check: 'output_model', status: 'passed' },
      ] },
    }))
    const wrapper = mountWizard()
    await wrapper.setProps({ previewTraining, outputModelName: 'retained-output', warmStartModelVersionId: 'warm-a',
      trainingSelectedModelSummary: { model_name: 'yolo', model_id: 'yolo' } as never,
      selectedTrainingDatasetExport: { dataset_export_id: 'e1', category_names: [] } as never })
    for (let i = 0; i < 4; i++) await wrapper.find('form').trigger('submit')
    await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain('2 项检查未通过')
    expect(wrapper.get('details.training-preflight__files').text()).toContain('annotations/instances_val.json')
    expect(wrapper.get('.training-preflight').text()).toContain('由 Worker 确认')
    expect(wrapper.get('button-stub[type="submit"]').attributes('disabled')).toBe('true')
    await wrapper.find('form').trigger('submit')
    expect(wrapper.emitted('submit')).toBeUndefined()
    await wrapper.get('.training-preflight button-stub[aria-label="返回初始化"]').trigger('click')
    expect(wrapper.text()).toContain('初始化方式')
    expect(wrapper.props('outputModelName')).toBe('retained-output')
  })
})
