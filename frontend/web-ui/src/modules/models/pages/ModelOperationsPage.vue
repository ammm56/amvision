<template>
  <section class="page-stack">
    <header class="page-header">
      <div>
        <p class="page-kicker">{{ t('modelOps.kicker') }}</p>
        <h1>{{ t('modelOps.title') }}</h1>
        <p class="page-description">{{ t('modelOps.description') }}</p>
      </div>
      <div class="page-actions">
        <Button variant="secondary" :disabled="loading" @click="refreshPage">
          <RefreshCw :size="16" />
          {{ t('common.refresh') }}
        </Button>
      </div>
    </header>

    <InlineError :message="errorMessage" />

    <div class="operation-grid model-ops-grid">
      <ModelTrainingForm
        :selected-task-type="selectedTaskType"
        :loading="loading"
        :base-models-count="baseModels.length"
        :training-dataset-exports-count="trainingDatasetExports.length"
        :training-selected-model-summary="trainingSelectedModelSummary"
        :selected-training-dataset-export="selectedTrainingDatasetExport"
        :output-model-name="outputModelName"
        :max-epochs="maxEpochs"
        :batch-size="batchSize"
        :gpu-count="gpuCount"
        :evaluation-interval="evaluationInterval"
        :precision="precision"
        :input-width="inputWidth"
        :input-height="inputHeight"
        :training-display-name="trainingDisplayName"
        :warm-start-model-version-id="warmStartModelVersionId"
        :training-supports-gpu-count="trainingSupportsGpuCount"
        :training-task-supports-warm-start="trainingTaskSupportsWarmStart"
        :training-model-parameter-fields="trainingModelParameterFields"
        :training-model-parameter-values="trainingModelParameterValues"
        :training-model-parameter-section-title="trainingModelParameterSectionTitle"
        :precision-options="precisionOptions"
        :can-write-tasks="canWriteTasks"
        :training-submitting="trainingSubmitting"
        :last-training-submission="lastTrainingSubmission"
        @submit="submitTraining"
        @open-base-model-picker="openBaseModelPicker('training')"
        @open-training-dataset-export-picker="openTrainingDatasetExportPicker"
        @clear-training-warm-start="clearTrainingWarmStart"
        @update:output-model-name="outputModelName = $event"
        @update:max-epochs="maxEpochs = $event"
        @update:batch-size="batchSize = $event"
        @update:gpu-count="gpuCount = $event"
        @update:evaluation-interval="evaluationInterval = $event"
        @update:precision="setPrecision"
        @update:input-width="inputWidth = $event"
        @update:input-height="inputHeight = $event"
        @update:training-display-name="trainingDisplayName = $event"
        @update:training-model-parameter-value="setTrainingModelParameterValue"
      />

      <ModelConversionForm
        :selected-task-type="selectedTaskType"
        :loading="loading"
        :base-models-count="baseModels.length"
        :conversion-selected-model-summary="conversionSelectedModelSummary"
        :conversion-model-type="conversionModelType"
        :conversion-source-model-version-id="conversionSourceModelVersionId"
        :conversion-target="conversionTarget"
        :conversion-target-options="conversionTargetOptions"
        :conversion-runtime-profile-id="conversionRuntimeProfileId"
        :conversion-display-name="conversionDisplayName"
        :can-write-tasks="canWriteTasks"
        :conversion-submitting="conversionSubmitting"
        :last-conversion-submission="lastConversionSubmission"
        @submit="submitConversion"
        @open-base-model-picker="openBaseModelPicker('conversion')"
        @update:conversion-model-type="conversionModelType = $event"
        @update:conversion-source-model-version-id="conversionSourceModelVersionId = $event"
        @update:conversion-target="setConversionTarget"
        @update:conversion-runtime-profile-id="conversionRuntimeProfileId = $event"
        @update:conversion-display-name="conversionDisplayName = $event"
      />
    </div>

    <TrainingTaskList
      :loading="loading"
      :selected-task-type="selectedTaskType"
      :training-tasks="trainingTasks"
    />

    <ConversionTaskList
      :loading="loading"
      :conversion-tasks="conversionTasks"
    />

    <PlatformBaseModelPickerDialog
      :open="baseModelPickerOpen"
      :loading="loading"
      :mode="baseModelPickerMode"
      :kicker="t('modelOps.baseKicker')"
      :title="baseModelPickerMode === 'training' ? t('modelOps.picker.trainingTitle') : t('modelOps.picker.conversionTitle')"
      :description="baseModelPickerMode === 'training' ? t('modelOps.picker.trainingDescription') : t('modelOps.picker.conversionDescription')"
      :close-label="t('modelOps.picker.close')"
      :task-type-label="t('modelOps.fields.taskType')"
      :task-type-options="taskTypeOptions"
      :selected-task-type="selectedTaskType"
      :model-list-title="t('modelOps.baseTitle')"
      :detail-title="t('modelOps.picker.detailTitle')"
      :versions-title="t('modelOps.availableVersionsTitle')"
      :extra-versions-title="t('modelOps.picker.projectTrainingVersionsTitle')"
      :versions-label="t('modelOps.columns.versions')"
      :builds-label="t('modelOps.columns.builds')"
      :scale-label="t('modelOps.columns.scale')"
      :apply-model-label="t('modelOps.picker.applyModel')"
      :apply-training-version-label="t('modelOps.actions.useWarmStart')"
      :apply-conversion-version-label="t('modelOps.actions.useConversionSource')"
      :empty-title="t('modelOps.emptyModelsTitle')"
      :empty-description="t('modelOps.emptyModelsDescription')"
      :detail-empty-title="t('modelOps.picker.detailEmptyTitle')"
      :detail-empty-description="t('modelOps.picker.detailEmptyDescription')"
      :empty-versions-title="t('modelOps.picker.emptyVersionsTitle')"
      :empty-versions-description="t('modelOps.picker.emptyVersionsDescription')"
      :models="baseModels"
      :selected-model-id="selectedModelDetail?.model_id ?? null"
      :selected-model-detail="selectedModelDetail"
      :extra-versions="selectedModelDerivedTrainingVersions"
      :selected-version-id="baseModelPickerMode === 'training' ? warmStartModelVersionId : conversionSourceModelVersionId"
      @close="closeBaseModelPicker"
      @change-task-type="setTaskType"
      @select-model="selectBaseModel"
      @apply-model="applyTrainingModel"
      @apply-training-version="applyTrainingVersion"
      @apply-conversion-version="applyConversionVersion"
    />

    <TrainingDatasetExportPickerDialog
      :open="trainingDatasetExportPickerOpen"
      :loading="loading"
      :kicker="t('modelOps.trainingKicker')"
      :title="t('modelOps.datasetExportPicker.title')"
      :description="t('modelOps.datasetExportPicker.description')"
      :close-label="t('modelOps.datasetExportPicker.close')"
      :search-value="trainingDatasetExportSearch"
      :search-placeholder="t('modelOps.datasetExportPicker.searchPlaceholder')"
      :list-title="t('modelOps.datasetExportPicker.listTitle')"
      :detail-title="t('modelOps.datasetExportPicker.detailTitle')"
      :apply-label="t('modelOps.actions.useTrainingDatasetExport')"
      :empty-title="t('modelOps.datasetExportPicker.emptyTitle')"
      :empty-description="t('modelOps.datasetExportPicker.emptyDescription')"
      :no-results-title="t('modelOps.datasetExportPicker.noResultsTitle')"
      :no-results-description="t('modelOps.datasetExportPicker.noResultsDescription')"
      :detail-empty-title="t('modelOps.datasetExportPicker.detailEmptyTitle')"
      :detail-empty-description="t('modelOps.datasetExportPicker.detailEmptyDescription')"
      :dataset-id-label="t('datasetOps.fields.datasetId')"
      :dataset-version-id-label="t('datasetOps.fields.datasetVersionId')"
      :sample-count-label="t('datasetOps.columns.samples')"
      :created-at-label="t('modelOps.columns.createdAt')"
      :category-names-label="t('datasetOps.fields.categoryNames')"
      :no-value-label="t('common.noValue')"
      :exports="trainingDatasetExports"
      :selected-export-id="trainingDatasetExportBrowseId || null"
      @close="closeTrainingDatasetExportPicker"
      @update:search-value="trainingDatasetExportSearch = $event"
      @select-export="selectTrainingDatasetExportBrowse"
      @apply-export="applyTrainingDatasetExport"
    />
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RefreshCw } from '@lucide/vue'
import { useI18n } from 'vue-i18n'

import {
  listProjectDatasetExports,
  type DatasetExportSummary,
} from '@/modules/datasets/services/dataset.service'
import {
  listPlatformBaseModels,
  type ConversionTargetKey,
  type ModelTaskType,
  type PlatformBaseModelDetail,
  type PlatformBaseModelSummary,
} from '../services/model.service'
import { useProjectStore } from '@/app/stores/project.store'
import { useSessionStore } from '@/app/stores/session.store'
import Button from '@/shared/ui/components/Button.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import ConversionTaskList from '../components/ConversionTaskList.vue'
import ModelConversionForm from '../components/ModelConversionForm.vue'
import ModelTrainingForm from '../components/ModelTrainingForm.vue'
import PlatformBaseModelPickerDialog from '../components/PlatformBaseModelPickerDialog.vue'
import TrainingDatasetExportPickerDialog from '../components/TrainingDatasetExportPickerDialog.vue'
import TrainingTaskList from '../components/TrainingTaskList.vue'
import { useModelConversionState } from '../composables/useModelConversionState'
import { useModelTaskLists } from '../composables/useModelTaskLists'
import { useModelTrainingState } from '../composables/useModelTrainingState'
import { usePlatformBaseModelSelection } from '../composables/usePlatformBaseModelSelection'
import { useTrainingDatasetExportSelection } from '../composables/useTrainingDatasetExportSelection'
import { useTrainingParameters } from '../composables/useTrainingParameters'

type SelectValue = string | number | boolean | null

const projectStore = useProjectStore()
const sessionStore = useSessionStore()
const { t } = useI18n()

const precisionOptions = [
  { label: 'fp32', value: 'fp32' },
  { label: 'fp16', value: 'fp16' },
]

const defaultTaskTypeOptions: Array<{ label: ModelTaskType; value: ModelTaskType }> = [
  { label: 'detection', value: 'detection' },
  { label: 'classification', value: 'classification' },
  { label: 'segmentation', value: 'segmentation' },
  { label: 'pose', value: 'pose' },
  { label: 'obb', value: 'obb' },
]

const conversionTargetOptions = [
  { label: 'ONNX', value: 'onnx' },
  { label: 'ONNX optimized', value: 'onnx-optimized' },
  { label: 'OpenVINO IR FP32', value: 'openvino-ir-fp32' },
  { label: 'OpenVINO IR FP16', value: 'openvino-ir-fp16' },
  { label: 'TensorRT FP32', value: 'tensorrt-engine-fp32' },
  { label: 'TensorRT FP16', value: 'tensorrt-engine-fp16' },
]

const baseModels = ref<PlatformBaseModelSummary[]>([])
const trainingDatasetExports = ref<DatasetExportSummary[]>([])
const loading = ref(false)
const errorMessage = ref<string | null>(null)
const selectedTaskType = ref<ModelTaskType>('detection')
const conversionTarget = ref<ConversionTargetKey>('onnx')
const conversionRuntimeProfileId = ref('')
const conversionDisplayName = ref('')

const canWriteTasks = computed(() => sessionStore.hasScopes(['tasks:write']))
const selectedProjectId = computed(() => projectStore.selectedProjectId)
const platformModelTypesByTaskType = computed<Record<string, string[]>>(() => {
  const rawValue = sessionStore.bootstrap?.capabilities.platform_model_types_by_task_type
  if (!rawValue || typeof rawValue !== 'object') {
    return {}
  }
  const normalizedEntries = Object.entries(rawValue).map(([taskType, modelTypes]) => [
    taskType,
    Array.isArray(modelTypes)
      ? modelTypes
          .filter((modelType): modelType is string => typeof modelType === 'string')
          .map((modelType) => modelType.toLowerCase())
      : [],
  ])
  return Object.fromEntries(normalizedEntries)
})
const taskTypeOptions = computed(() => {
  const supportedOptions = defaultTaskTypeOptions.filter((option) => {
    const supportedModelTypes = platformModelTypesByTaskType.value[option.value] ?? []
    return supportedModelTypes.length > 0
  })
  return supportedOptions.length > 0 ? supportedOptions : defaultTaskTypeOptions
})

const {
  trainingTasks,
  conversionTasks,
  refreshTrainingTasks,
  refreshConversionTasks,
  refreshTaskLists,
} = useModelTaskLists(selectedTaskType, selectedProjectId)

const {
  trainingDatasetExportPickerOpen,
  trainingDatasetExportSearch,
  trainingDatasetExportBrowseId,
  trainingDatasetExportId,
  selectedTrainingDatasetExport,
  openTrainingDatasetExportPicker,
  closeTrainingDatasetExportPicker,
  selectTrainingDatasetExportBrowse,
  applyTrainingDatasetExport,
  resetTrainingDatasetExportSelection,
  ensureTrainingDatasetExportSelectionVisible,
} = useTrainingDatasetExportSelection(trainingDatasetExports)

function setErrorMessage(message: string | null): void {
  errorMessage.value = message
}

const {
  selectedModelDetail,
  baseModelPickerOpen,
  baseModelPickerMode,
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
} = usePlatformBaseModelSelection({
  baseModels,
  trainingTasks,
  onError: setErrorMessage,
  detailFailedMessage: () => t('modelOps.messages.detailFailed'),
})

const resolvedTrainingManifestKey = computed(
  () => selectedTrainingDatasetExport.value?.manifest_object_key?.trim() ?? '',
)
const resolvedTrainingModelType = computed(
  () => trainingSelectedModelSummary.value?.model_type?.trim() ?? '',
)
const resolvedTrainingModelScale = computed(
  () => trainingSelectedModelSummary.value?.model_scale?.trim() ?? '',
)

const {
  outputModelName,
  maxEpochs,
  batchSize,
  gpuCount,
  evaluationInterval,
  precision,
  inputWidth,
  inputHeight,
  trainingDisplayName,
  trainingModelParameterValues,
  trainingTaskSupportsWarmStart,
  trainingSupportsGpuCount,
  trainingModelParameterFields,
  trainingModelParameterSectionTitle,
  setPrecision,
  setTrainingModelParameterValue,
  syncSuggestedOutputModelName,
  resetSuggestedOutputModelName,
  alignTrainingInputSizeForSubmit,
} = useTrainingParameters({
  selectedTaskType,
  resolvedTrainingModelType,
  resolvedTrainingModelScale,
})

const {
  trainingSubmitting,
  lastTrainingSubmission,
  submitTraining,
} = useModelTrainingState({
  selectedTaskType,
  selectedProjectId,
  trainingSelectedModelSummary,
  selectedTrainingDatasetExport,
  resolvedTrainingManifestKey,
  resolvedTrainingModelType,
  resolvedTrainingModelScale,
  trainingDatasetExportId,
  outputModelName,
  warmStartModelVersionId,
  trainingTaskSupportsWarmStart,
  trainingSupportsGpuCount,
  evaluationInterval,
  maxEpochs,
  batchSize,
  gpuCount,
  precision,
  inputWidth,
  inputHeight,
  trainingDisplayName,
  trainingModelParameterValues,
  alignTrainingInputSizeForSubmit,
  refreshTrainingTasks,
  setErrorMessage,
  messages: {
    selectTrainingBaseModel: () => t('modelOps.messages.selectTrainingBaseModel'),
    selectTrainingDatasetExport: () => t('modelOps.messages.selectTrainingDatasetExport'),
    trainingExportIncomplete: () => t('modelOps.messages.trainingExportIncomplete'),
    trainingExportTaskMismatch: () => t('modelOps.messages.trainingExportTaskMismatch'),
    trainingExportManifestMissing: () => t('modelOps.messages.trainingExportManifestMissing'),
    trainingExportFormatMismatch: (payload) => t('modelOps.messages.trainingExportFormatMismatch', payload),
    submitTrainingFailed: () => t('modelOps.messages.submitTrainingFailed'),
  },
})

const {
  conversionSubmitting,
  lastConversionSubmission,
  submitConversion,
} = useModelConversionState({
  selectedTaskType,
  selectedProjectId,
  conversionModelType,
  conversionSourceModelVersionId,
  conversionTarget,
  conversionRuntimeProfileId,
  conversionDisplayName,
  refreshConversionTasks,
  setErrorMessage,
  submitConversionFailedMessage: () => t('modelOps.messages.submitConversionFailed'),
})

onMounted(async () => {
  if (projectStore.projects.length === 0) {
    await projectStore.loadProjects()
  }
  await refreshPage()
})

function normalizeSelectValue(value: SelectValue): string {
  return typeof value === 'string' ? value : String(value ?? '')
}

async function setTaskType(value: SelectValue): Promise<void> {
  const nextValue = normalizeSelectValue(value)
  if (!taskTypeOptions.value.some((option) => option.value === nextValue)) {
    return
  }
  selectedTaskType.value = nextValue as ModelTaskType
  resetPlatformBaseModelSelection()
  resetTrainingDatasetExportSelection()
  resetSuggestedOutputModelName()
  await refreshPage()
}

function setConversionTarget(value: SelectValue): void {
  conversionTarget.value = (normalizeSelectValue(value) || 'onnx') as ConversionTargetKey
}

async function refreshPage(): Promise<void> {
  loading.value = true
  errorMessage.value = null
  try {
    const [models, datasetExports] = await Promise.all([
      listPlatformBaseModels(selectedTaskType.value),
      selectedProjectId.value
        ? listProjectDatasetExports(selectedProjectId.value, selectedTaskType.value, 'completed')
        : Promise.resolve<DatasetExportSummary[]>([]),
      refreshTaskLists(),
    ])
    baseModels.value = models
    trainingDatasetExports.value = datasetExports
    ensureSelectedModelStillVisible()
    ensureTrainingDatasetExportSelectionVisible()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : t('modelOps.messages.loadFailed')
  } finally {
    loading.value = false
  }
}

function applyTrainingModel(model: PlatformBaseModelDetail): void {
  applyTrainingModelSelection(model)
  syncSuggestedOutputModelName(model)
}

function applyTrainingVersion(payload: {
  model: PlatformBaseModelDetail
  modelVersionId: string
}): void {
  applyTrainingVersionSelection(payload)
  syncSuggestedOutputModelName(payload.model)
}
</script>

<style scoped>
.model-ops-grid {
  align-items: start;
}
</style>
