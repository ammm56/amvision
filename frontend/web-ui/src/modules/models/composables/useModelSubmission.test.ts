import { computed, ref } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const api = vi.hoisted(() => ({ createModelTrainingTask: vi.fn(), createModelConversionTask: vi.fn(), resolveModelSubmission: vi.fn() }))
vi.mock('../services/model.service', () => api)
vi.mock('@/platform/i18n', () => ({ translate: (key: string) => key }))
vi.mock('../training-parameter-support', () => ({ buildTrainingParameters: () => ({}), validateTrainingModelLayerValues: () => null }))

import { useModelTrainingState } from './useModelTrainingState'
import { useModelConversionState } from './useModelConversionState'
import { ApiError } from '@/shared/api/error'
import type { ModelTaskType } from '../services/model.service'

describe('model task submission', () => {
  beforeEach(() => { vi.clearAllMocks(); sessionStorage.clear() })

  it('keeps a successful training submission when refreshing the list fails', async () => {
    let complete!: (result: { task_id: string }) => void
    api.createModelTrainingTask.mockReturnValue(new Promise(resolve => { complete = resolve }))
    const report = vi.fn()
    const options = {
      selectedTaskType: ref<ModelTaskType>('detection'), selectedProjectId: computed(() => 'project-1'),
      trainingSelectedModelSummary: computed(() => ({})),
      selectedTrainingDatasetExport: computed(() => ({ status: 'completed', task_type: 'detection', format_id: 'coco' })),
      resolvedTrainingManifestKey: computed(() => 'manifest'), resolvedTrainingModelType: computed(() => 'yolox'),
      resolvedTrainingModelScale: computed(() => 's'), trainingDatasetExportId: ref('export'), outputModelName: ref('model'),
      warmStartModelVersionId: ref(''), trainingTaskSupportsWarmStart: computed(() => false),
      evaluationInterval: ref(1), maxEpochs: ref(10), batchMode: ref('fixed'), batchSize: ref(1),
      batchTargetMemoryFraction: ref(0.6), batchMinimumSize: ref(1), batchMaximumSize: ref(undefined),
      batchRecoverOnOom: ref(false), batchMaxOomRetries: ref(0), trainingDevice: ref('cpu'),
      ampMode: ref('auto'), ampDtype: ref('auto'), checkpointInterval: ref(1), checkpointKeepPeriodic: ref(1),
      inputWidth: ref(640), inputHeight: ref(640), trainingDisplayName: ref(''), trainingModelParameterValues: {},
      trainingAugmentationEnabled: ref(false), trainingParameterSchema: computed(() => null),
      trainingExportFormatsByTaskAndModelType: computed(() => ({})), alignTrainingInputSizeForSubmit: () => ({ width: 640, height: 640 }),
      refreshTrainingTasks: vi.fn().mockRejectedValue(new Error('offline')), setErrorMessage: report,
      messages: { selectTrainingBaseModel: () => '', selectTrainingDatasetExport: () => '', trainingExportIncomplete: () => '', trainingExportTaskMismatch: () => '', trainingExportManifestMissing: () => '', trainingExportFormatMismatch: () => '', submitTrainingFailed: () => '' },
    } as unknown as Parameters<typeof useModelTrainingState>[0]
    const state = useModelTrainingState(options)
    const first = state.submitTraining()
    await state.submitTraining()
    expect(api.createModelTrainingTask).toHaveBeenCalledTimes(1)
    complete({ task_id: 'training-1' })
    await first
    expect(state.lastTrainingSubmission.value?.task_id).toBe('training-1')
    expect(report).toHaveBeenLastCalledWith('modelOps.messages.submittedRefreshFailed')
    await state.submitTraining()
    expect(api.createModelTrainingTask).toHaveBeenCalledTimes(1)
    state.resetTrainingSubmission()
    api.createModelTrainingTask.mockRejectedValue(new Error('connection lost'))
    await state.submitTraining()
    expect(state.trainingSubmissionUncertain.value).toBe(true)
    expect(report).toHaveBeenLastCalledWith(null)
    await state.submitTraining()
    expect(api.createModelTrainingTask).toHaveBeenCalledTimes(2)
    const afterReload = useModelTrainingState(options)
    expect(afterReload.trainingSubmissionUncertain.value).toBe(true)
    const [, id] = api.createModelTrainingTask.mock.calls.at(-1)!
    api.resolveModelSubmission.mockRejectedValueOnce(new Error('offline'))
    await afterReload.trainingReceipt.check()
    expect(afterReload.trainingReceipt.status.value).toBe('failed')
    expect(afterReload.trainingSubmissionUncertain.value).toBe(true)
    api.resolveModelSubmission.mockResolvedValueOnce({ status: 'not_created', task_id: null })
    await afterReload.trainingReceipt.check()
    expect(api.resolveModelSubmission).toHaveBeenLastCalledWith('project-1', id)
    expect(afterReload.trainingReceipt.status.value).toBe('not_created')
    expect(useModelTrainingState(options).trainingSubmissionUncertain.value).toBe(false)
  })

  it('keeps a successful conversion submission when refreshing the list fails', async () => {
    api.createModelConversionTask.mockResolvedValue({ task_id: 'conversion-1' })
    const report = vi.fn()
    const state = useModelConversionState({
      selectedTaskType: ref('detection'), selectedProjectId: computed(() => 'project-1'),
      selectedSource: computed(() => ({ model: { task_type: 'detection', project_id: 'project-1', model_type: 'yolox' }, version: { model_version_id: 'version', checkpoint_file_id: 'file', checkpoint_storage_uri: 'checkpoint', metadata: { category_names: ['object'] } } })) as never,
      canWriteTasks: computed(() => true), conversionTarget: ref('onnx'), conversionRuntimeProfileId: ref(''),
      conversionDisplayName: ref(''), refreshConversionTasks: vi.fn().mockRejectedValue(new Error('offline')),
      setErrorMessage: report, submitConversionFailedMessage: () => 'failed',
    })
    await state.submitConversion()
    expect(state.lastConversionSubmission.value?.task_id).toBe('conversion-1')
    expect(report).toHaveBeenLastCalledWith('modelOps.messages.submittedRefreshFailed')
    expect(api.createModelConversionTask).toHaveBeenCalledTimes(1)
    await state.submitConversion()
    expect(api.createModelConversionTask).toHaveBeenCalledTimes(1)
  })

  it('does not report a rejected conversion as submitted or refresh its list', async () => {
    api.createModelConversionTask.mockRejectedValue(new ApiError(422, { message: 'invalid source' }))
    const report = vi.fn(), refresh = vi.fn()
    const state = useModelConversionState({
      selectedTaskType: ref('detection'), selectedProjectId: computed(() => 'project-1'),
      selectedSource: computed(() => ({ model: { task_type: 'detection', project_id: 'project-1', model_type: 'yolox' }, version: { model_version_id: 'version', checkpoint_file_id: 'file', checkpoint_storage_uri: 'checkpoint', metadata: { category_names: ['object'] } } })) as never,
      canWriteTasks: computed(() => true), conversionTarget: ref('onnx'), conversionRuntimeProfileId: ref(''),
      conversionDisplayName: ref(''), refreshConversionTasks: refresh,
      setErrorMessage: report, submitConversionFailedMessage: () => 'failed',
    })
    await state.submitConversion()
    expect(state.lastConversionSubmission.value).toBeNull()
    expect(report).toHaveBeenLastCalledWith('invalid source')
    expect(refresh).not.toHaveBeenCalled()
  })

  it('holds conversion submission after a lost response until the task list is checked', async () => {
    api.createModelConversionTask.mockRejectedValue(new Error('connection lost'))
    const options = {
      selectedTaskType: ref<ModelTaskType>('detection'), selectedProjectId: computed(() => 'project-1'),
      selectedSource: computed(() => ({ model: { task_type: 'detection', project_id: 'project-1', model_type: 'yolox' }, version: { model_version_id: 'version', checkpoint_file_id: 'file', checkpoint_storage_uri: 'checkpoint', metadata: { category_names: ['object'] } } })) as never,
      canWriteTasks: computed(() => true), conversionTarget: ref('onnx' as const), conversionRuntimeProfileId: ref(''),
      conversionDisplayName: ref(''), refreshConversionTasks: vi.fn(), setErrorMessage: vi.fn(), submitConversionFailedMessage: () => 'failed',
    }
    const state = useModelConversionState(options)
    await state.submitConversion()
    await state.submitConversion()
    expect(api.createModelConversionTask).toHaveBeenCalledTimes(1)
    expect(state.conversionSubmissionUncertain.value).toBe(true)
    const afterReload = useModelConversionState(options)
    expect(afterReload.conversionSubmissionUncertain.value).toBe(true)
    const [, id] = api.createModelConversionTask.mock.calls.at(-1)!
    api.resolveModelSubmission.mockResolvedValueOnce({ status: 'accepted', task_id: 'conversion-2' })
    await expect(afterReload.conversionReceipt.check()).resolves.toBe('conversion-2')
    expect(api.resolveModelSubmission).toHaveBeenLastCalledWith('project-1', id)
    expect(afterReload.conversionSubmissionUncertain.value).toBe(true)
    afterReload.conversionReceipt.viewed('conversion-2')
    expect(useModelConversionState(options).conversionSubmissionUncertain.value).toBe(false)
  })
})
