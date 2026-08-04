import { computed, ref, type Ref } from 'vue'

import {
  getPlatformBaseModelDetail,
  type DeploymentSourceModelSummary,
  type PlatformBaseModelDetail,
  type PlatformBaseModelSummary,
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
  sourceModels: Ref<DeploymentSourceModelSummary[]>
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
    const selectedModelTaskType = selectedModel.task_type.trim().toLowerCase()
    const selectedModelScale = selectedModel.model_scale.trim().toLowerCase()
    const baseVersionIds = new Set(
      (selectedModel.versions ?? selectedModel.available_versions ?? []).map((version) => version.model_version_id),
    )
    const matchedVersions: PlatformBaseModelVersionListItem[] = []
    const seenVersionIds = new Set<string>()

    for (const sourceModel of options.sourceModels.value) {
      if (sourceModel.scope_kind !== 'project') {
        continue
      }

      const sourceModelType = sourceModel.model_type.trim().toLowerCase()
      const sourceTaskType = sourceModel.task_type.trim().toLowerCase()
      const sourceModelScale = sourceModel.model_scale.trim().toLowerCase()
      if (
        sourceModelType !== selectedModelType
        || sourceTaskType !== selectedModelTaskType
        || sourceModelScale !== selectedModelScale
      ) {
        continue
      }

      for (const version of sourceModel.available_versions ?? []) {
        const modelVersionId = version.model_version_id.trim()
        if (!modelVersionId || seenVersionIds.has(modelVersionId) || baseVersionIds.has(modelVersionId)) {
          continue
        }

        // 训练和转换都必须从已登记 checkpoint 的版本开始，避免把仅有元数据的残缺版本暴露给用户。
        if (!version.checkpoint_file_id?.trim() || !version.checkpoint_storage_uri?.trim()) {
          continue
        }

        seenVersionIds.add(modelVersionId)
        matchedVersions.push({
          model_version_id: modelVersionId,
          source_kind: version.source_kind || 'project-training-output',
          title: sourceModel.model_name.trim() || modelVersionId,
          subtitle: modelVersionId,
        })
      }
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
