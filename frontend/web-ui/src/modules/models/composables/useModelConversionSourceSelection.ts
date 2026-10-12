import { computed, ref, watch, type ComputedRef, type Ref } from 'vue'

import { conversionSourceIssue } from '../conversion-source-support'
import {
  type DeploymentSourceModelSummary,
  type ModelTaskType,
  type PlatformBaseModelVersionSummary,
} from '../services/model.service'

export interface ModelConversionSource {
  model: DeploymentSourceModelSummary
  version: PlatformBaseModelVersionSummary
}

export function useModelConversionSourceSelection(options: {
  sourceModels: Ref<DeploymentSourceModelSummary[]>
  projectId: ComputedRef<string>
  taskType: Ref<ModelTaskType>
}) {
  const conversionSourcePickerOpen = ref(false)
  const conversionBrowseModelId = ref('')
  const selectedVersionId = ref('')
  const conversionModels = computed(() => options.sourceModels.value.filter((model) => (
    (model.project_id === options.projectId.value || model.scope_kind === 'platform-base')
    && model.task_type === options.taskType.value
    && model.available_versions.some((version) => conversionSourceIssue(version) === null)
  )))
  const conversionBrowseModel = computed(() => conversionModels.value.find((model) => model.model_id === conversionBrowseModelId.value) ?? null)
  const selectedConversionSource = computed<ModelConversionSource | null>(() => {
    for (const model of conversionModels.value) {
      const version = model.available_versions.find((item) => item.model_version_id === selectedVersionId.value)
      if (version && conversionSourceIssue(version) === null) return { model, version }
    }
    return null
  })
  const conversionSelectedModelSummary = computed(() => selectedConversionSource.value?.model ?? null)
  const conversionModelType = computed(() => selectedConversionSource.value?.model.model_type ?? '')
  const conversionSourceModelVersionId = computed(() => selectedConversionSource.value?.version.model_version_id ?? '')

  function openConversionSourcePicker(): void {
    conversionSourcePickerOpen.value = true
    conversionBrowseModelId.value = selectedConversionSource.value?.model.model_id
      ?? conversionBrowseModel.value?.model_id ?? conversionModels.value[0]?.model_id ?? ''
  }

  function selectConversionVersion(modelVersionId: string): void {
    const version = conversionBrowseModel.value?.available_versions.find((item) => item.model_version_id === modelVersionId)
    if (!version || conversionSourceIssue(version) !== null) return
    selectedVersionId.value = version.model_version_id
    conversionSourcePickerOpen.value = false
  }

  function resetConversionSourceSelection(keepPickerOpen = false): void {
    selectedVersionId.value = ''
    conversionBrowseModelId.value = ''
    if (!keepPickerOpen) conversionSourcePickerOpen.value = false
  }

  watch(conversionModels, () => {
    if (selectedVersionId.value && selectedConversionSource.value === null) selectedVersionId.value = ''
    if (conversionBrowseModel.value === null) conversionBrowseModelId.value = conversionModels.value[0]?.model_id ?? ''
  })

  return {
    conversionModels, conversionSourcePickerOpen, conversionBrowseModelId, conversionBrowseModel,
    selectedConversionSource, conversionSelectedModelSummary, conversionModelType, conversionSourceModelVersionId,
    openConversionSourcePicker, selectConversionVersion, resetConversionSourceSelection,
  }
}
