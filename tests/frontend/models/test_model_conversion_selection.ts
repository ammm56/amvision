import { computed, ref } from 'vue'
import { describe, expect, it, vi } from 'vitest'

import { conversionSourceIssue } from '@/modules/models/conversion-source-support'
import { useModelConversionSourceSelection } from '@/modules/models/composables/useModelConversionSourceSelection'
import { useModelConversionState } from '@/modules/models/composables/useModelConversionState'
import { createModelConversionTask, type DeploymentSourceModelSummary, type PlatformBaseModelVersionSummary } from '@/modules/models/services/model.service'

vi.mock('@/modules/models/services/model.service', async (importOriginal) => ({
  ...await importOriginal<typeof import('@/modules/models/services/model.service')>(), createModelConversionTask: vi.fn(),
}))

export function conversionVersion(id = 'trained-version'): PlatformBaseModelVersionSummary {
  return {
    model_version_id: id, source_kind: 'training-output', file_ids: ['checkpoint', 'labels'],
    metadata: { category_names: ['ok', 'ng'] }, checkpoint_file_id: 'checkpoint', checkpoint_storage_uri: 'best.pt',
    labels_file_id: 'labels', labels_storage_uri: 'labels.txt',
  }
}

export function conversionModel(versions = [conversionVersion()]): DeploymentSourceModelSummary {
  return {
    model_id: 'actual-trained-model', project_id: 'project-1', scope_kind: 'project', model_name: 'PCB-classifier',
    model_type: 'yolo11', model_scale: 's', task_type: 'classification', metadata: {}, version_count: versions.length,
    build_count: 0, available_versions: versions,
  }
}

describe('conversion source contract', () => {
  it('does not turn a checkpoint-only warm-start reference into an inference model', () => {
    const version = { ...conversionVersion(), metadata: {}, labels_file_id: null, labels_storage_uri: null }
    expect(conversionSourceIssue(version)).toBe('labelsMissing')
    expect(conversionSourceIssue({ ...version, metadata: { category_names: ['ok', 'ng'] } })).toBeNull()
    expect(conversionSourceIssue({ ...version, metadata: { category_names: ['ok', '', 'ng'] } })).toBe('labelsInvalid')
    expect(conversionSourceIssue({ ...version, metadata: { category_names: ['ok', 'ok'] } })).toBe('labelsInvalid')
  })

  it('selects the actual trained model without a platform model, ancestry or matching catalog scale', () => {
    const models = ref([conversionModel()])
    const taskType = ref<'classification' | 'detection'>('classification')
    const selection = useModelConversionSourceSelection({ sourceModels: models, projectId: computed(() => 'project-1'), taskType })
    selection.openConversionSourcePicker()
    selection.selectConversionVersion('trained-version')
    expect(selection.selectedConversionSource.value?.model.model_id).toBe('actual-trained-model')
    expect(selection.conversionModelType.value).toBe('yolo11')
    expect(selection.conversionSourcePickerOpen.value).toBe(false)
    taskType.value = 'detection'
    expect(selection.selectedConversionSource.value).toBeNull()
    taskType.value = 'classification'
    models.value = []
    expect(selection.selectedConversionSource.value).toBeNull()
  })

  it.each(['\n', '\r', '\v', '\f', '\u001c', '\u001d', '\u001e', '\u0085', '\u2028', '\u2029'])('rejects a class split by the labels file separator %j', (separator) => {
    const version = conversionVersion()
    version.metadata.category_names = [`part${separator}other`]
    expect(conversionSourceIssue(version)).toBe('labelsInvalid')
  })

  it('excludes other projects and invalid versions but permits explicitly labeled platform versions', () => {
    const model = conversionModel()
    const models = ref([
      { ...model, project_id: 'project-2' },
      { ...model, model_id: 'warm-start-only', available_versions: [{ ...conversionVersion(), labels_file_id: null, labels_storage_uri: null, metadata: {} }] },
      { ...model, model_id: 'labeled-platform', project_id: null, scope_kind: 'platform-base' },
    ])
    const selection = useModelConversionSourceSelection({ sourceModels: models, projectId: computed(() => 'project-1'), taskType: ref('classification') })
    expect(selection.conversionModels.value.map((item) => item.model_id)).toEqual(['labeled-platform'])
  })

  it('rejects empty selection and prevents a pending response from restoring the previous project', async () => {
    const projectId = ref('project-1')
    const source = ref<{ model: DeploymentSourceModelSummary; version: PlatformBaseModelVersionSummary } | null>(null)
    const setErrorMessage = vi.fn()
    const refresh = vi.fn()
    const state = useModelConversionState({
      selectedProjectId: computed(() => projectId.value), selectedTaskType: ref('classification'), selectedSource: computed(() => source.value),
      canWriteTasks: computed(() => true), conversionTarget: ref('onnx'), conversionRuntimeProfileId: ref(''), conversionDisplayName: ref(''),
      refreshConversionTasks: refresh, setErrorMessage, submitConversionFailedMessage: () => 'failed',
    })
    await state.submitConversion()
    expect(createModelConversionTask).not.toHaveBeenCalled()
    expect(setErrorMessage).toHaveBeenCalledWith(expect.any(String))
    source.value = { model: conversionModel(), version: conversionVersion() }
    let complete!: (value: never) => void
    vi.mocked(createModelConversionTask).mockImplementationOnce(() => new Promise((resolve) => { complete = resolve }))
    const pending = state.submitConversion()
    await state.submitConversion()
    expect(createModelConversionTask).toHaveBeenCalledTimes(1)
    projectId.value = 'project-2'
    complete({ task_id: 'old-task' } as never)
    await pending
    expect(state.lastConversionSubmission.value).toBeNull()
    expect(refresh).not.toHaveBeenCalled()
    vi.clearAllMocks()
  })
})
