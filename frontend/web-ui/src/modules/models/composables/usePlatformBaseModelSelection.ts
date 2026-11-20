import { modelDisplayName, modelVersionDisplayName } from '../model-display-name'
import { computed, ref, type Ref } from 'vue'

import {
  getPlatformBaseModelDetail,
  type DeploymentSourceModelSummary,
  type PlatformBaseModelDetail,
  type PlatformBaseModelSummary,
  type PlatformBaseModelVersionSummary,
} from '../services/model.service'

export interface PlatformBaseModelVersionListItem {
  model_version_id: string
  title: string
  subtitle: string
  checkpoint_storage_uri: string
  checkpoint_state: PlatformBaseModelVersionSummary['checkpoint_state']
}

interface ResetPlatformBaseModelSelectionOptions {
  keepPickerOpen?: boolean
}

export function usePlatformBaseModelSelection(options: {
  baseModels: Ref<PlatformBaseModelSummary[]>
  sourceModels: Ref<DeploymentSourceModelSummary[]>
  detailFailedMessage: () => string
}) {
  const selectedModelDetail = ref<PlatformBaseModelDetail | null>(null)
  const selectedModelBrowseId = ref('')
  const selectedModelDetailLoading = ref(false)
  const selectedModelDetailError = ref('')
  const baseModelPickerOpen = ref(false)
  const trainingSelectedModelId = ref('')
  const warmStartModelVersionId = ref('')
  let detailRequestSerial = 0

  const trainingSelectedModelSummary = computed(
    () => options.baseModels.value.find((model) => model.model_id === trainingSelectedModelId.value) ?? null,
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

        // 继续训练从已登记 checkpoint 的版本开始。
        if (!version.checkpoint_file_id?.trim() || !version.checkpoint_storage_uri?.trim()) {
          continue
        }

        seenVersionIds.add(modelVersionId)
        matchedVersions.push({
          model_version_id: modelVersionId,
          title: modelDisplayName(sourceModel),
          subtitle: modelVersionDisplayName(version, true),
          checkpoint_storage_uri: version.checkpoint_storage_uri,
          checkpoint_state: version.checkpoint_state,
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
    selectedModelDetailError.value = ''
    try {
      const detail = await getPlatformBaseModelDetail(modelId)
      if (requestSerial === detailRequestSerial && selectedModelBrowseId.value === modelId) {
        selectedModelDetail.value = detail
      }
    } catch (error) {
      if (requestSerial === detailRequestSerial) {
        selectedModelDetailError.value = error instanceof Error ? error.message : options.detailFailedMessage()
      }
    } finally {
      if (requestSerial === detailRequestSerial) {
        selectedModelDetailLoading.value = false
      }
    }
  }

  async function openBaseModelPicker(): Promise<void> {
    baseModelPickerOpen.value = true
    if (options.baseModels.value.length === 0) {
      return
    }
    const preferred = trainingSelectedModelId.value || selectedModelBrowseId.value || selectedModelDetail.value?.model_id
    const available = (model: PlatformBaseModelSummary) => model.available_versions.some(version => version.checkpoint_state === 'present')
    const preferredModelId = options.baseModels.value.find(model => model.model_id === preferred)?.model_id
      || options.baseModels.value.find(available)?.model_id || options.baseModels.value[0].model_id
    if (preferredModelId && selectedModelDetail.value?.model_id !== preferredModelId) {
      await selectBaseModel(preferredModelId)
    }
  }

  function closeBaseModelPicker(): void {
    baseModelPickerOpen.value = false
  }

  function applyTrainingModelSelection(model: PlatformBaseModelSummary): void {
    trainingSelectedModelId.value = model.model_id
    warmStartModelVersionId.value = ''
  }

  function applyTrainingVersionSelection(payload: {
    model: PlatformBaseModelSummary
    modelVersionId: string
  }): void {
    trainingSelectedModelId.value = payload.model.model_id
    warmStartModelVersionId.value = payload.modelVersionId
  }

  function clearTrainingWarmStart(): void {
    warmStartModelVersionId.value = ''
  }

  function resetPlatformBaseModelSelection(options: ResetPlatformBaseModelSelectionOptions = {}): void {
    detailRequestSerial += 1
    selectedModelDetail.value = null
    selectedModelBrowseId.value = ''
    selectedModelDetailLoading.value = false
    selectedModelDetailError.value = ''
    if (options.keepPickerOpen !== true) {
      baseModelPickerOpen.value = false
    }
    trainingSelectedModelId.value = ''
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
      selectedModelDetailError.value = ''
    }
    if (!options.baseModels.value.some((model) => model.model_id === trainingSelectedModelId.value)) {
      trainingSelectedModelId.value = ''
      warmStartModelVersionId.value = ''
    }
  }

  return {
    selectedModelDetail,
    selectedModelBrowseId,
    selectedModelDetailLoading,
    selectedModelDetailError,
    baseModelPickerOpen,
    trainingSelectedModelId,
    warmStartModelVersionId,
    trainingSelectedModelSummary,
    selectedModelDerivedTrainingVersions,
    selectBaseModel,
    openBaseModelPicker,
    closeBaseModelPicker,
    applyTrainingModelSelection,
    applyTrainingVersionSelection,
    clearTrainingWarmStart,
    resetPlatformBaseModelSelection,
    ensureSelectedModelStillVisible,
  }
}
