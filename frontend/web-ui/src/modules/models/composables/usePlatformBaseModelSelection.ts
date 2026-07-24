import { computed, ref, type Ref } from 'vue'

import {
  getPlatformBaseModelDetail,
  type PlatformBaseModelDetail,
  type PlatformBaseModelSummary,
  type ModelTrainingTaskSummary,
} from '../services/model.service'

export interface PlatformBaseModelVersionListItem {
  model_version_id: string
  source_kind: string
  title: string
  subtitle: string
}

interface ResetPlatformBaseModelSelectionOptions {
  keepPickerOpen?: boolean
}

export function usePlatformBaseModelSelection(options: {
  baseModels: Ref<PlatformBaseModelSummary[]>
  trainingTasks: Ref<ModelTrainingTaskSummary[]>
  onError: (message: string) => void
  detailFailedMessage: () => string
}) {
  const selectedModelDetail = ref<PlatformBaseModelDetail | null>(null)
  const selectedModelBrowseId = ref('')
  const selectedModelDetailLoading = ref(false)
  const baseModelPickerOpen = ref(false)
  const baseModelPickerMode = ref<'training' | 'conversion'>('training')
  const trainingSelectedModelId = ref('')
  const conversionSelectedModelId = ref('')
  const conversionModelType = ref('')
  const conversionSourceModelVersionId = ref('')
  const warmStartModelVersionId = ref('')
  let detailRequestSerial = 0

  const trainingSelectedModelSummary = computed(
    () => options.baseModels.value.find((model) => model.model_id === trainingSelectedModelId.value) ?? null,
  )
  const conversionSelectedModelSummary = computed(
    () => options.baseModels.value.find((model) => model.model_id === conversionSelectedModelId.value) ?? null,
  )

  const selectedModelDerivedTrainingVersions = computed<PlatformBaseModelVersionListItem[]>(() => {
    const selectedModel = selectedModelDetail.value
    if (selectedModel === null) {
      return []
    }

    const selectedModelType = selectedModel.model_type.trim().toLowerCase()
    const selectedModelScale = selectedModel.model_scale.trim().toLowerCase()
    const baseVersionIds = new Set(
      (selectedModel.versions ?? selectedModel.available_versions ?? []).map((version) => version.model_version_id),
    )
    const matchedVersions: PlatformBaseModelVersionListItem[] = []
    const seenVersionIds = new Set<string>()

    for (const task of options.trainingTasks.value) {
      const modelVersionId = (task.model_version_id || task.latest_checkpoint_model_version_id || '').trim()
      if (!modelVersionId || seenVersionIds.has(modelVersionId) || baseVersionIds.has(modelVersionId)) {
        continue
      }

      const taskModelType = (task.model_type || '').trim().toLowerCase()
      const taskModelScale = (task.model_scale || '').trim().toLowerCase()
      if (taskModelType !== selectedModelType || taskModelScale !== selectedModelScale) {
        continue
      }

      const warmStartPayload = task.training_summary?.warm_start
      const warmStartSummary = warmStartPayload && typeof warmStartPayload === 'object'
        ? warmStartPayload as Record<string, unknown>
        : null
      const sourceModelVersionId = typeof warmStartSummary?.source_model_version_id === 'string'
        ? warmStartSummary.source_model_version_id.trim()
        : ''
      if (sourceModelVersionId && baseVersionIds.size > 0 && !baseVersionIds.has(sourceModelVersionId)) {
        continue
      }

      seenVersionIds.add(modelVersionId)
      matchedVersions.push({
        model_version_id: modelVersionId,
        source_kind: 'project-training-output',
        title: task.output_model_name?.trim() || task.display_name?.trim() || modelVersionId,
        subtitle: modelVersionId,
      })
    }

    return matchedVersions
  })

  async function selectBaseModel(modelId: string): Promise<void> {
    const requestSerial = ++detailRequestSerial
    selectedModelBrowseId.value = modelId
    selectedModelDetailLoading.value = true
    selectedModelDetail.value = null
    try {
      const detail = await getPlatformBaseModelDetail(modelId)
      if (requestSerial === detailRequestSerial && selectedModelBrowseId.value === modelId) {
        selectedModelDetail.value = detail
      }
    } catch (error) {
      if (requestSerial === detailRequestSerial) {
        options.onError(error instanceof Error ? error.message : options.detailFailedMessage())
      }
    } finally {
      if (requestSerial === detailRequestSerial) {
        selectedModelDetailLoading.value = false
      }
    }
  }

  async function openBaseModelPicker(mode: 'training' | 'conversion'): Promise<void> {
    baseModelPickerMode.value = mode
    baseModelPickerOpen.value = true
    if (options.baseModels.value.length === 0) {
      return
    }
    const preferredModelId = mode === 'training'
      ? trainingSelectedModelId.value || selectedModelBrowseId.value || selectedModelDetail.value?.model_id || options.baseModels.value[0].model_id
      : conversionSelectedModelId.value || selectedModelBrowseId.value || selectedModelDetail.value?.model_id || options.baseModels.value[0].model_id
    if (preferredModelId && selectedModelDetail.value?.model_id !== preferredModelId) {
      await selectBaseModel(preferredModelId)
    }
  }

  function closeBaseModelPicker(): void {
    baseModelPickerOpen.value = false
  }

  function applyTrainingModelSelection(model: PlatformBaseModelDetail): void {
    trainingSelectedModelId.value = model.model_id
    warmStartModelVersionId.value = ''
  }

  function applyTrainingVersionSelection(payload: {
    model: PlatformBaseModelDetail
    modelVersionId: string
  }): void {
    trainingSelectedModelId.value = payload.model.model_id
    warmStartModelVersionId.value = payload.modelVersionId
  }

  function clearTrainingWarmStart(): void {
    warmStartModelVersionId.value = ''
  }

  function applyConversionVersion(payload: {
    model: PlatformBaseModelDetail
    modelVersionId: string
  }): void {
    conversionSelectedModelId.value = payload.model.model_id
    conversionModelType.value = payload.model.model_type
    conversionSourceModelVersionId.value = payload.modelVersionId
  }

  function resetPlatformBaseModelSelection(options: ResetPlatformBaseModelSelectionOptions = {}): void {
    detailRequestSerial += 1
    selectedModelDetail.value = null
    selectedModelBrowseId.value = ''
    selectedModelDetailLoading.value = false
    if (options.keepPickerOpen !== true) {
      baseModelPickerOpen.value = false
    }
    trainingSelectedModelId.value = ''
    conversionSelectedModelId.value = ''
    conversionModelType.value = ''
    conversionSourceModelVersionId.value = ''
    warmStartModelVersionId.value = ''
  }

  function ensureSelectedModelStillVisible(): void {
    const selectedModelId = selectedModelBrowseId.value || selectedModelDetail.value?.model_id || ''
    const selectedModelStillVisible = selectedModelId !== ''
      && options.baseModels.value.some((model) => model.model_id === selectedModelId)
    if (!selectedModelStillVisible) {
      detailRequestSerial += 1
      selectedModelBrowseId.value = ''
      selectedModelDetail.value = null
      selectedModelDetailLoading.value = false
    }
  }

  return {
    selectedModelDetail,
    selectedModelBrowseId,
    selectedModelDetailLoading,
    baseModelPickerOpen,
    baseModelPickerMode,
    trainingSelectedModelId,
    conversionSelectedModelId,
    conversionModelType,
    conversionSourceModelVersionId,
    warmStartModelVersionId,
    trainingSelectedModelSummary,
    conversionSelectedModelSummary,
    selectedModelDerivedTrainingVersions,
    selectBaseModel,
    openBaseModelPicker,
    closeBaseModelPicker,
    applyTrainingModelSelection,
    applyTrainingVersionSelection,
    clearTrainingWarmStart,
    applyConversionVersion,
    resetPlatformBaseModelSelection,
    ensureSelectedModelStillVisible,
  }
}
