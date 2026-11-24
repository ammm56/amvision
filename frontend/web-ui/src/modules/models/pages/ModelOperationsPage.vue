<template>
  <section class="page-stack model-workspace">
    <div v-show="!trainingWizardOpen && !conversionWizardOpen && !packageImportOpen && (activeTab !== 'evaluation' || !evaluationFocusMode)" class="model-ops-navigation">
      <TabList v-model="activeTab" :tabs="modelTabs" :label="zh ? '模型管理' : 'Models'" />
      <div class="model-ops-navigation__actions">
        <Button v-if="activeTab === 'conversion' && canWriteModels" @click="packageExportRecordsOpen = true">{{ zh ? '导出记录' : 'Export records' }}</Button>
        <Button v-if="activeTab === 'conversion'" :variant="canWriteTasks ? 'primary' : 'secondary'" :disabled="!canWriteTasks || conversionSubmissionUncertain || conversionSubmitting || conversionCopyLoading" @click="startConversionWizard"><Plus :size="16" />{{ zh ? '创建转换' : 'Create conversion' }}</Button>
        <Button v-else-if="activeTab === 'training' || (activeTab === 'versions' && !catalogEmpty)" :variant="canWriteTasks ? 'primary' : 'secondary'" :disabled="!canWriteTasks" @click="startTraining()"><Plus :size="16" />{{ zh ? '创建训练' : 'Create training' }}</Button>
      </div>
    </div>

    <ProjectModelCatalog
      ref="projectModelCatalog"
      v-show="activeTab === 'versions' && !trainingWizardOpen && !packageImportOpen"
      :active="activeTab === 'versions' && !trainingWizardOpen && !packageImportOpen"
      :project-id="selectedProjectId"
      :principal-key="submissionPrincipal"
      :can-edit="canWriteModels"
      :can-train="canWriteTasks"
      :can-convert="canWriteTasks"
      :can-deploy="canDeployModelVersion"
      :launching-conversion="versionConversionLoading"
      :launch-error="versionActionError"
      :open-model-id="typeof transferRoute?.query.model === 'string' ? transferRoute.query.model : undefined"
      :open-version-id="typeof transferRoute?.query.version === 'string' ? transferRoute.query.version : undefined"
      :requested-task-type="activeTab === 'versions' && typeof transferRoute?.query.task === 'string' ? transferRoute.query.task : ''"
      @open-base-models="openCatalogBaseModels"
      @create-training="startTraining(true)"
      @import-model-package="startPackageImport"
      @empty-state="catalogEmpty = $event"
      @version-change="resetVersionAction"
      @version-deleted="clearDeletedVersionLink"
      @create-conversion="startVersionConversion"
      @create-deployment="startVersionDeployment"
      @change-task-type="setCatalogTaskType"
    />

    <InlineError v-if="activeTab !== 'versions' || baseModelPickerOpen" :message="errorMessage" />
    <InlineMessage v-if="trainingCopyLoading || trainingCopyMessage" :tone="trainingCopyLoading ? 'info' : 'warning'" :message="trainingCopyLoading ? (zh ? '正在读取原训练配置…' : 'Loading the original training configuration…') : trainingCopyMessage" />
    <InlineMessage v-if="activeTab === 'conversion' && (conversionCopyLoading || conversionCopyMessage)" :tone="conversionCopyLoading ? 'info' : 'warning'" :message="conversionCopyLoading ? (zh ? '正在读取原转换配置…' : 'Loading the original conversion configuration…') : conversionCopyMessage" />
    <ResourceCleanupPanel v-if="(activeTab === 'versions' || activeTab === 'conversion') && !trainingWizardOpen && !conversionWizardOpen && !packageImportOpen" :project-id="selectedProjectId" @settled="refreshPage" />

    <div v-show="trainingWizardOpen || (activeTab === 'conversion' && conversionWizardOpen)" class="operation-grid model-ops-grid">
      <ModelTrainingForm
        v-if="trainingWizardOpen"
        :selected-task-type="selectedTaskType"
        :loading="loading"
        :base-catalog="baseModels"
        :project-models="projectSourceModels"
        :training-dataset-exports-count="trainingDatasetExports.length"
        :training-selected-model-summary="trainingSelectedModelSummary"
        :selected-training-dataset-export="selectedTrainingDatasetExport"
        :training-device-options="trainingDeviceOptions"
        :output-model-name="outputModelName"
        :output-model-name-taken="outputModelNameTaken"
        :max-epochs="maxEpochs"
        :batch-mode="batchMode"
        :batch-size="batchSize"
        :batch-target-memory-fraction="batchTargetMemoryFraction"
        :batch-recover-on-oom="batchRecoverOnOom"
        :batch-max-oom-retries="batchMaxOomRetries"
        :training-device="trainingDevice"
        :evaluation-interval="evaluationInterval"
        :amp-mode="ampMode"
        :amp-dtype="ampDtype"
        :checkpoint-interval="checkpointInterval"
        :input-width="inputWidth"
        :input-height="inputHeight"
        :training-display-name="trainingDisplayName"
        :warm-start-model-version-id="warmStartModelVersionId"
        :warm-start-label="trainingWarmStartLabel"
        :warm-start-source="trainingWarmStartSource"
        :warm-start-file-name="trainingWarmStartFileName"
        :warm-start-file-status="trainingWarmStartFileStatus"
        :training-task-supports-warm-start="trainingTaskSupportsWarmStart"
        :training-model-parameter-fields="trainingModelParameterFields"
        :training-augmentation-parameter-fields="trainingAugmentationParameterFields"
        :training-augmentation-enabled="trainingAugmentationEnabled"
        :training-supports-augmentation-toggle="trainingSupportsAugmentationToggle"
        :training-model-parameter-values="trainingModelParameterValues"
        :training-model-parameter-section-title="trainingModelParameterSectionTitle"
        :batch-mode-options="batchModeOptions"
        :amp-mode-options="ampModeOptions"
        :amp-dtype-options="ampDtypeOptions"
        :can-write-tasks="canWriteTasks"
        :training-submitting="trainingSubmitting"
        :preview-training="previewTraining"
        :training-submission-uncertain="trainingSubmissionUncertain"
        :configuration-error="trainingConfigurationError"
        :selection-error="trainingSelectionError"
        :last-training-submission="lastTrainingSubmission"
        @submit="submitTraining"
        @cancel="closeTrainingWizard"
        @view-training-tasks="activeTab = 'training'; closeTrainingWizard()"
        @open-base-model-picker="openTrainingBaseModelPicker"
        @open-training-weight-picker="openTrainingWeightPicker"
        @open-training-dataset-export-picker="openTrainingDatasetExportPicker"
        @clear-training-warm-start="clearTrainingWarmStart"
        @update:output-model-name="outputModelName = $event"
        @dataset-name-resolved="syncTrainingDatasetName"
        @update:max-epochs="maxEpochs = $event"
        @update:batch-mode="setBatchMode"
        @update:batch-size="batchSize = $event"
        @update:batch-target-memory-fraction="batchTargetMemoryFraction = $event"
        @update:batch-recover-on-oom="batchRecoverOnOom = $event"
        @update:batch-max-oom-retries="batchMaxOomRetries = $event"
        @update:training-device="setTrainingDevice"
        @update:evaluation-interval="evaluationInterval = $event"
        @update:amp-mode="setAmpMode"
        @update:amp-dtype="setAmpDtype"
        @update:checkpoint-interval="checkpointInterval = $event"
        @update:input-width="inputWidth = $event"
        @update:input-height="inputHeight = $event"
        @update:training-display-name="trainingDisplayName = $event"
        @update:training-model-parameter-value="setTrainingModelParameterValue"
        @update:training-augmentation-enabled="trainingAugmentationEnabled = $event"
      >
        <template #submission-warning>
          <ModelSubmissionResolution v-if="trainingReceipt.visible.value && !trainingSubmitting" :receipt="trainingReceipt" :zh="zh" warning-only />
        </template>
        <template #submission-result>
          <ModelSubmissionResolution v-if="trainingReceipt.visible.value && !trainingSubmitting" :receipt="trainingReceipt" :zh="zh" :can-check="canWriteTasks" :section-number="5" show-list @check="checkModelSubmission('training')" @view-list="closeTrainingWizard" />
        </template>
      </ModelTrainingForm>

      <ModelConversionForm
        v-show="activeTab === 'conversion'"
        :selected-task-type="selectedTaskType"
        :project-id="selectedProjectId"
        :loading="loading"
        :conversion-selected-model-summary="conversionSelectedModelSummary"
        :conversion-model-type="conversionModelType"
        :conversion-source-model-version-id="conversionSourceModelVersionId"
        :conversion-source-version="selectedConversionSource?.version || null"
        :conversion-target="conversionTarget"
        :conversion-target-options="conversionTargetOptions"
        :conversion-runtime-profile-id="conversionRuntimeProfileId"
        :onnx-opset-version="conversionOpsetVersion"
        :input-shape-mode="conversionInputShapeMode"
        :tensor-rt-int8="tensorRtInt8"
        :open-vino-int8="openVinoInt8"
        :dataset-exports="trainingDatasetExports"
        :dataset-export-labels="trainingDatasetNames"
        :conversion-display-name="conversionDisplayName"
        :can-write-tasks="canWriteTasks"
        :conversion-submitting="conversionSubmitting"
        :conversion-submission-uncertain="conversionSubmissionUncertain"
        :last-conversion-submission="lastConversionSubmission"
        @submit="submitConversion"
        @cancel="closeConversionWizard"
        @reset-submission="resetConversionSubmission"
        @open-source-picker="openConversionSourcePicker"
        @update:conversion-target="setConversionTarget"
        @update:conversion-runtime-profile-id="conversionRuntimeProfileId = $event"
        @update:onnx-opset-version="conversionOpsetVersion = $event"
        @update:input-shape-mode="conversionInputShapeMode = $event"
        @update:tensor-rt-int8="tensorRtInt8 = $event"
        @update:open-vino-int8="openVinoInt8 = $event"
        @update:conversion-display-name="conversionDisplayName = $event"
      >
        <template #submission-warning>
          <ModelSubmissionResolution v-if="conversionReceipt.visible.value && !conversionSubmitting" :receipt="conversionReceipt" :zh="zh" warning-only />
        </template>
        <template #submission-result>
          <ModelSubmissionResolution v-if="conversionReceipt.visible.value && !conversionSubmitting" :receipt="conversionReceipt" :zh="zh" :can-check="canWriteTasks" show-list @check="checkModelSubmission('conversion')" @view-list="closeConversionWizard" />
        </template>
      </ModelConversionForm>
    </div>

    <ModelSubmissionResolution v-if="activeTab === 'training' && !trainingWizardOpen && trainingReceipt.visible.value && !trainingSubmitting" :receipt="trainingReceipt" :zh="zh" :can-check="canWriteTasks" @check="checkModelSubmission('training')" />
    <TrainingTaskList
      v-if="activeTab === 'training' && !trainingWizardOpen"
      :selected-task-type="selectedTaskType"
      :training-tasks="trainingTasks"
      :task-type-options="taskTypeOptions"
      :loading="trainingList.loading.value"
      :load-error="trainingList.error.value"
      :updated-at="trainingList.updatedAt.value"
      :dataset-names="trainingDatasetNames"
      :version-names="modelVersionNames"
      :can-reuse="canWriteTasks && sessionStore.hasScopes(['models:read', 'tasks:read'])"
      @change-task-type="setTaskType"
      @open-base-models="openCatalogBaseModels"
      @refresh="refreshPage"
    />


    <ModelSubmissionResolution v-if="activeTab === 'conversion' && !conversionWizardOpen && conversionReceipt.visible.value && !conversionSubmitting && !packageImportOpen" :receipt="conversionReceipt" :zh="zh" :can-check="canWriteTasks" @check="checkModelSubmission('conversion')" />
    <ConversionTaskList
      v-if="activeTab === 'conversion' && !conversionWizardOpen && !packageImportOpen"
      :selected-task-type="selectedTaskType"
      :conversion-tasks="conversionTasks"
      :task-type-options="taskTypeOptions"
      :loading="conversionList.loading.value"
      :load-error="conversionList.error.value"
      :updated-at="conversionList.updatedAt.value"
      :source-names="conversionSourceNames"
      :can-reuse="canWriteModels && canWriteTasks && sessionStore.hasScopes(['models:read', 'tasks:read'])"
      @change-task-type="setTaskType"
      @open-base-models="openCatalogBaseModels"
      @refresh="refreshPage"
    />


    <ModelPackageRecords v-if="canWriteModels && ((activeTab === 'conversion' && !conversionWizardOpen) || packageImportOpen)" v-model:import-open="packageImportOpen" v-model:export-records-open="packageExportRecordsOpen" :project-id="selectedProjectId" :project-name="projectStore.selectedProject?.display_name || selectedProjectId" :zh="zh" :version-names="modelVersionNames" @create-import="startPackageImport" />
    <ImportedModelAssets v-if="activeTab === 'conversion' && !conversionWizardOpen && !packageImportOpen && canWriteModels" :project-id="selectedProjectId" />
    <ModelEvaluationPanel v-if="activeTab === 'evaluation'" :project-id="selectedProjectId" :can-write="canWriteTasks && sessionStore.hasScopes(['datasets:read'])" :zh="zh" @focus-mode="evaluationFocusMode = $event" />

    <PlatformBaseModelPickerDialog
      :open="baseModelPickerOpen"
      :loading="pickerUsesPageCatalog ? loading : pickerLoading"
      :list-error="pickerUsesPageCatalog ? errorMessage : pickerError"
      :detail-loading="selectedModelDetailLoading"
      :detail-error="selectedModelDetailError"
      :weights-only="basePickerWeightsOnly"
      :allow-weights="trainingTaskSupportsWarmStart"
      :retry-label="zh ? '重试' : 'Retry'"
      :title="basePickerWeightsOnly ? (zh ? '选择初始化权重' : 'Choose initialization weights') : t('modelOps.picker.trainingTitle')"
      :close-label="t('modelOps.picker.close')"
      :task-type-label="t('modelOps.fields.taskType')"
      :task-type-options="basePickerTaskTypeOptions"
      :selected-task-type="pickerTaskType ?? selectedTaskType"
      :model-list-title="t('modelOps.picker.modelSelectionTitle')"
      :model-name-label="t('modelOps.picker.modelNameTitle')"
      :detail-title="t('modelOps.picker.detailTitle')"
      :detail-loading-label="t('modelOps.picker.detailLoading')"
      :extra-versions-title="t('modelOps.picker.projectTrainingVersionsTitle')"
      :scale-label="t('modelOps.picker.modelScaleTitle')"
      :apply-model-label="basePickerWeightsOnly ? (zh ? '使用所选权重' : 'Use selected weights') : t('modelOps.picker.applyModel')"
      :empty-title="t('modelOps.emptyModelsTitle')"
      :detail-empty-title="t('modelOps.picker.detailEmptyTitle')"
      :models="basePickerModels"
      :selected-model-id="selectedModelBrowseId || null"
      :selected-model-detail="selectedModelDetail"
      :extra-versions="selectedModelDerivedTrainingVersions"
      :applied-model-id="trainingSelectedModelSummary?.model_id"
      :selected-version-id="warmStartModelVersionId"
      @close="closeBaseModelPicker"
      @change-task-type="selectPickerTaskType"
      @select-model="selectBaseModel"
      @retry-detail="selectedModelBrowseId && selectBaseModel(selectedModelBrowseId)"
      @retry-list="refreshPickerCatalog"
      @apply-model="applyPickerModel({ model: $event })"
      @apply-training-version="applyPickerModel"
    />

    <ModelConversionSourcePickerDialog
      :open="conversionSourcePickerOpen" :loading="conversionPickerUsesPage ? loading : conversionPickerLoading" :load-error="conversionPickerError"
      :selected-task-type="conversionPickerTask" :task-type-options="taskTypeOptions"
      :models="conversionPickerModels" :selected-model="conversionPickerModel"
      :selected-version-id="conversionSourceModelVersionId"
      @close="conversionSourcePickerOpen = false" @change-task-type="changeConversionPickerTask" @retry="conversionPickerRevision++"
      @select-model="conversionBrowseModelId = $event" @select-version="confirmConversionPickerVersion"
    />

    <TrainingDatasetExportPickerDialog
      :open="trainingDatasetExportPickerOpen"
      :loading="loading"
      :names-loading="trainingDatasetNamesLoading"
      :names-error="trainingDatasetNamesError"
      :title="t('modelOps.datasetExportPicker.title')"
      :close-label="t('modelOps.datasetExportPicker.close')"
      :search-value="trainingDatasetExportSearch"
      :apply-label="t('modelOps.actions.useTrainingDatasetExport')"
      :empty-title="t('modelOps.datasetExportPicker.emptyTitle')"
      :exports="namedTrainingDatasetExports"
      :supported-formats="supportedTrainingExportFormats"
      :selected-export-id="trainingDatasetExportBrowseId || null"
      @close="closeTrainingDatasetExportPicker"
      @retry-names="trainingDatasetNamesRetry++"
      @update:search-value="trainingDatasetExportSearch = $event"
      @select-export="selectTrainingDatasetExportBrowse"
      @apply-export="applyTrainingDatasetExport"
    />
  </section>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { onBeforeRouteLeave, onBeforeRouteUpdate, useRoute, useRouter } from 'vue-router'
import { Plus } from '@lucide/vue'
import { useI18n } from 'vue-i18n'

import {
  getDatasetExportDetail,
  listProjectDatasetExports,
  type DatasetExportSummary,
} from '@/modules/datasets/services/dataset.service'
import { listDatasetVersionPage, type DatasetVersion } from '@/modules/datasets/services/dataset-workspace.service'
import {
  getDeploymentSourceModelDetail,
  getModelConversionTaskDetail,
  getModelTrainingTaskDetail,
  getProjectModelFileStatus,
  listDeploymentSourceModels,
  listPlatformBaseModels,
  listTrainingParameterSchemas,
  type ConversionTargetKey,
  type TensorRtInt8Settings,
  type Int8SampleSettings,
  type DeploymentSourceModelSummary,
  type ModelTaskType,
  type PlatformBaseModelDetail,
  type PlatformBaseModelSummary,
  type TrainingParameterSchemaItem,
} from '../services/model.service'
import { useProjectStore } from '@/app/stores/project.store'
import { useSessionStore } from '@/app/stores/session.store'
import { canAccessPage } from '@/platform/auth/page-access'
import Button from '@/shared/ui/components/Button.vue'
import ResourceCleanupPanel from '@/shared/ui/components/ResourceCleanupPanel.vue'
import ImportedModelAssets from '../components/ImportedModelAssets.vue'
import ModelPackageRecords from '../components/ModelPackageRecords.vue'
import ModelEvaluationPanel from '../components/ModelEvaluationPanel.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import InlineMessage from '@/shared/ui/feedback/InlineMessage.vue'
import TabList from '@/shared/ui/navigation/TabList.vue'
import ProjectModelCatalog from '../components/ProjectModelCatalog.vue'
import ConversionTaskList from '../components/ConversionTaskList.vue'
import ModelConversionForm from '../components/ModelConversionForm.vue'
import ModelConversionSourcePickerDialog from '../components/ModelConversionSourcePickerDialog.vue'
import ModelSubmissionResolution from '../components/ModelSubmissionResolution.vue'
import ModelTrainingForm from '../components/ModelTrainingForm.vue'
import PlatformBaseModelPickerDialog from '../components/PlatformBaseModelPickerDialog.vue'
import TrainingDatasetExportPickerDialog from '../components/TrainingDatasetExportPickerDialog.vue'
import TrainingTaskList from '../components/TrainingTaskList.vue'
import { useModelConversionState } from '../composables/useModelConversionState'
import { useModelConversionSourceSelection } from '../composables/useModelConversionSourceSelection'
import { useModelTaskLists } from '../composables/useModelTaskLists'
import { resolveSupportedTrainingExportFormats, useModelTrainingState } from '../composables/useModelTrainingState'
import { usePlatformBaseModelSelection } from '../composables/usePlatformBaseModelSelection'
import { useTrainingDatasetExportSelection } from '../composables/useTrainingDatasetExportSelection'
import { savedTrainingText, useTrainingParameters } from '../composables/useTrainingParameters'
import { hasCudaDevice } from '@/modules/deployments/deployment-device-support'
import { buildTrainingDeviceOptions } from '../training-parameter-support'
import { conversionSourceIssue } from '../conversion-source-support'
import { conversionRecord, readConversionInt8Samples, readConversionInt8Settings, readConversionTarget } from '../conversion-task-presentation'
import { modelDisplayName, modelVersionDisplayName, readCatalogVersionNames } from '../model-display-name'
import { evaluationTypes } from '../model-evaluation-types'
import type { ModelVersionAction } from '../model-version-action'

type SelectValue = string | number | boolean | null

const projectStore = useProjectStore()
const sessionStore = useSessionStore()
const submissionPrincipal = computed(() => sessionStore.currentUser?.principal_id ?? '')
const { t, locale } = useI18n()
const zh = computed(() => locale.value.startsWith('zh'))
const transferRoute = useRoute()
const router = useRouter()
const projectModelCatalog = ref<InstanceType<typeof ProjectModelCatalog> | null>(null)
const allowNavigation = () => projectModelCatalog.value?.allowNavigation?.() ?? true
onBeforeRouteLeave(allowNavigation)
onBeforeRouteUpdate(allowNavigation)

function clearDeletedVersionLink(versionId: string): void {
  if (transferRoute.query.version !== versionId) return
  const query = { ...transferRoute.query }
  delete query.model
  delete query.version
  void router.replace({ query })
}
function readTab(): string {
  const tab = transferRoute?.query.tab
  if (typeof tab === 'string' && ['versions', 'training', 'conversion', 'evaluation'].includes(tab)) return tab
  if (transferRoute?.query.conversionFrom) return 'conversion'
  return transferRoute?.query.datasetExport || transferRoute?.query.trainingFrom ? 'training' : 'versions'
}
const activeTab = ref(readTab())
const evaluationFocusMode = ref(false)
watch(() => [transferRoute?.query.tab, transferRoute?.query.datasetExport, transferRoute?.query.trainingFrom, transferRoute?.query.conversionFrom], () => {
  activeTab.value = readTab()
})
watch(activeTab, (tab) => {
  if (tab === readTab() || !router || transferRoute?.path !== '/models') return
  void router.push({ path: '/models', query: { tab, task: tab === 'training' || tab === 'conversion' ? selectedTaskType.value : undefined } })
})
function setCatalogTaskType(task: string): void {
  if (router && transferRoute?.path === '/models' && activeTab.value === 'versions') {
    void router.replace({ query: { ...transferRoute.query, task: task || undefined } })
  }
}
const trainingWizardOpen = ref(Boolean(transferRoute?.query.datasetExport))
const trainingCopyLoading = ref(false)
const trainingCopyMessage = ref('')
let trainingCopyRequest: AbortController | null = null
let restoreTrainingParameters: (() => void) | null = null
const copiedDatasetExport = ref<DatasetExportSummary | null>(null)
const conversionWizardOpen = ref(false)
const conversionCopyLoading = ref(false)
const conversionCopyMessage = ref('')
let conversionCopyRequest: AbortController | null = null
const packageImportOpen = ref(false)
const packageExportRecordsOpen = ref(false)
watch(activeTab, tab => { if (tab !== 'conversion') { packageImportOpen.value = false; packageExportRecordsOpen.value = false } })
function startPackageImport(): void {
  if (canWriteModels.value) packageImportOpen.value = true
}
function startTraining(keepCatalog = false): void {
  if (!canWriteTasks.value || trainingCopyLoading.value) return
  if (trainingSubmissionUncertain.value || trainingSubmitting.value) {
    activeTab.value = 'training'
    return
  }
  resetTrainingSubmission()
  if (!keepCatalog) activeTab.value = 'training'
  trainingWizardOpen.value = true
}
function closeTrainingWizard(): void {
  if (lastTrainingSubmission.value || trainingSubmissionUncertain.value) activeTab.value = 'training'
  trainingWizardOpen.value = false
  if (transferRoute?.query.trainingFrom || restoreTrainingParameters) {
    resetTrainingCopy()
    if (router && transferRoute?.path === '/models' && transferRoute.query.trainingFrom) {
      void router.replace({ query: { ...transferRoute.query, trainingFrom: undefined } })
    }
  }
}

function resetTrainingCopy(): void {
  trainingCopyRequest?.abort()
  trainingCopyRequest = null
  trainingCopyLoading.value = false
  trainingCopyMessage.value = ''
  if (!restoreTrainingParameters) return
  restoreTrainingParameters()
  restoreTrainingParameters = null
  copiedDatasetExport.value = null
  resetPlatformBaseModelSelection()
  resetTrainingDatasetExportSelection()
}

onBeforeUnmount(() => { trainingCopyRequest?.abort(); conversionCopyRequest?.abort() })
const catalogEmpty = ref(false)
const basePickerFromCatalog = ref(false)
const basePickerWeightsOnly = ref(false)
const modelTabs = computed(() => [
  { id: 'versions', label: zh.value ? '模型版本' : 'Model versions' },
  { id: 'training', label: zh.value ? '训练任务' : 'Training' },
  { id: 'conversion', label: zh.value ? '转换与导入' : 'Conversion and import' },
  { id: 'evaluation', label: zh.value ? '评估' : 'Evaluation' },
])

const batchModeOptions = computed(() => [
  { label: t('modelOps.trainingParameters.autoBatch'), value: 'auto' },
  { label: t('modelOps.trainingParameters.fixedBatch'), value: 'fixed' },
])
const ampModeOptions = computed(() => [
  { label: t('modelOps.trainingParameters.ampAuto'), value: 'auto' },
  { label: t('modelOps.trainingParameters.enabled'), value: 'enabled' },
  { label: t('modelOps.trainingParameters.disabled'), value: 'disabled' },
])
const ampDtypeOptions = computed(() => [
  { label: t('modelOps.trainingParameters.ampDtypeAuto'), value: 'auto' },
  { label: 'fp16', value: 'fp16' },
  { label: 'bf16', value: 'bf16' },
])

const defaultTaskTypeOptions: Array<{ label: ModelTaskType; value: ModelTaskType }> = [
  { label: 'detection', value: 'detection' },
  { label: 'classification', value: 'classification' },
  { label: 'segmentation', value: 'segmentation' },
  { label: 'pose', value: 'pose' },
  { label: 'obb', value: 'obb' },
]

const baseConversionTargetOptions: Array<{ label: string; value: ConversionTargetKey }> = [
  { label: 'ONNX', value: 'onnx' },
  { label: 'ONNX optimized', value: 'onnx-optimized' },
  { label: 'OpenVINO IR FP32', value: 'openvino-ir-fp32' },
  { label: 'OpenVINO IR FP16', value: 'openvino-ir-fp16' },
  { label: 'OpenVINO IR INT8', value: 'openvino-ir-int8' },
  { label: 'TensorRT FP32', value: 'tensorrt-engine-fp32' },
  { label: 'TensorRT FP16', value: 'tensorrt-engine-fp16' },
  { label: 'TensorRT INT8', value: 'tensorrt-engine-int8' },
]

const baseModels = ref<PlatformBaseModelSummary[]>([])
const projectSourceModels = ref<DeploymentSourceModelSummary[]>([])
const trainingDatasetExports = ref<DatasetExportSummary[]>([])
const trainingParameterSchemas = ref<TrainingParameterSchemaItem[]>([])
const loading = ref(true)
const errorMessage = ref<string | null>(null)
const selectedTaskType = ref<ModelTaskType>('detection')
const pickerTaskType = ref<ModelTaskType | null>(null)
const pickerCatalog = ref<{ models: PlatformBaseModelSummary[]; sources: DeploymentSourceModelSummary[] } | null>(null)
const pickerLoading = ref(false)
const pickerError = ref<string | null>(null)
let pickerRequest = 0
const pickerUsesPageCatalog = computed(() => pickerTaskType.value === null || pickerTaskType.value === selectedTaskType.value)
const basePickerSources = computed(() => pickerUsesPageCatalog.value ? projectSourceModels.value : pickerCatalog.value?.sources ?? [])
const conversionTarget = ref<ConversionTargetKey>('onnx')
const conversionRuntimeProfileId = ref('')
const conversionOpsetVersion = ref<number>()
const conversionInputShapeMode = ref<'dynamic-batch'>()
const tensorRtInt8 = ref<TensorRtInt8Settings>()
const openVinoInt8 = ref<Int8SampleSettings>()
watch(conversionWizardOpen, open => {
  if (!open) {
    conversionOpsetVersion.value = undefined
    conversionInputShapeMode.value = undefined
    tensorRtInt8.value = undefined
    openVinoInt8.value = undefined
  }
})
const conversionDisplayName = ref('')
let pageRequestSerial = 0

const canWriteTasks = computed(() => sessionStore.hasScopes(['tasks:write']))
const canWriteModels = computed(() => sessionStore.hasScopes(['models:read', 'models:write']))
const selectedProjectId = computed(() => projectStore.selectedProjectId)
const trainingDeviceOptions = computed(() => buildTrainingDeviceOptions(sessionStore.bootstrap?.devices ?? null).map((option) => (
  option.value === '' ? { ...option, label: t('modelOps.trainingParameters.autoDevice') } : option
)))
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
const trainingExportFormatsByTaskAndModelType = computed<Record<string, Record<string, string[]>>>(() => {
  const rawValue = sessionStore.bootstrap?.capabilities.training_export_formats_by_task_and_model_type
  return rawValue && typeof rawValue === 'object' ? rawValue : {}
})
const taskTypeOptions = computed(() => {
  const supportedOptions = defaultTaskTypeOptions.filter((option) => {
    const supportedModelTypes = platformModelTypesByTaskType.value[option.value] ?? []
    return supportedModelTypes.length > 0
  })
  return supportedOptions.length > 0 ? supportedOptions : defaultTaskTypeOptions
})
const basePickerTaskTypeOptions = computed(() => taskTypeOptions.value
  .filter(option => !basePickerWeightsOnly.value || option.value === selectedTaskType.value)
  .map(({ value }) => ({ value, label: evaluationTypes[value][zh.value ? 0 : 1] })))

const {
  training: trainingList,
  conversion: conversionList,
  trainingTasks,
  conversionTasks,
  refreshTrainingTasks,
  refreshConversionTasks,
  refreshTaskLists,
} = useModelTaskLists(selectedTaskType, selectedProjectId, submissionPrincipal)

const modelVersionNames = computed(() => new Map(projectSourceModels.value.flatMap(model =>
  model.available_versions.map(version => [version.model_version_id, modelVersionDisplayName(version, true)]))))
const conversionCatalogNames = ref(new Map<string, string>())
const conversionSourceNames = computed(() => new Map([
  ...conversionCatalogNames.value,
  ...projectSourceModels.value.flatMap(model => model.available_versions.map(version =>
    [version.model_version_id, `${modelDisplayName(model)} · ${modelVersionDisplayName(version, true)}`] as const)),
]))
const conversionSourceIds = computed(() => [...new Set(conversionTasks.value.map(task => task.source_model_version_id).filter(Boolean))].sort().join(','))
watch([activeTab, selectedProjectId, selectedTaskType, submissionPrincipal, conversionSourceIds], async ([tab, project, type, principal, ids], previous, onCleanup) => {
  if (!previous || project !== previous[1] || type !== previous[2] || principal !== previous[3]) conversionCatalogNames.value = new Map()
  if (tab !== 'conversion' || !project || !ids) return
  const missing = ids.split(',').filter(id => !conversionSourceNames.value.has(id))
  if (!missing.length) return
  const controller = new AbortController()
  onCleanup(() => controller.abort())
  try {
    const names = await readCatalogVersionNames(project, type, missing, controller.signal)
    if (!controller.signal.aborted) conversionCatalogNames.value = new Map([...conversionCatalogNames.value, ...names])
  } catch { /* 来源版本不可访问时继续显示任务保存的版本 ID。 */ }
}, { immediate: true })
const trainingDatasetVersions = ref(new Map<string, Pick<DatasetVersion, 'display_name' | 'version_number'>>())
const trainingDatasetNamesRetry = ref(0)
const trainingDatasetNamesLoading = ref(false)
const trainingDatasetNamesError = ref(false)
const trainingExports = computed(() => new Map(trainingDatasetExports.value.map(item => [item.dataset_export_id, item])))
const namedTrainingDatasetExports = computed(() => trainingDatasetExports.value.map(item => {
  const identity = trainingDatasetVersions.value.get(item.dataset_version_id)
  return identity ? { ...item, ...identity } : item
}))
const relevantTrainingVersions = computed(() => {
  const ids = trainingTasks.value.flatMap(task => {
    const id = task.dataset_version_id || trainingExports.value.get(task.dataset_export_id || '')?.dataset_version_id
    return id ? [id] : []
  })
  if (conversionWizardOpen.value) {
    ids.push(...trainingDatasetExports.value.filter(item => item.format_id === 'coco-detection-v1').map(item => item.dataset_version_id))
  }
  if (trainingWizardOpen.value) ids.push(...trainingDatasetExports.value.map(item => item.dataset_version_id))
  return [...new Set(ids)].sort().join(',')
})
const trainingDatasetNames = computed(() => {
  const labels = new Map([...trainingDatasetVersions.value].map(([id, identity]) => [id, `${identity.display_name} · v${identity.version_number}`]))
  for (const item of trainingDatasetExports.value) {
    const label = labels.get(item.dataset_version_id)
    if (label) labels.set(item.dataset_export_id, label)
  }
  return labels
})
watch([activeTab, selectedProjectId, selectedTaskType, submissionPrincipal, relevantTrainingVersions, conversionWizardOpen, trainingWizardOpen, trainingDatasetNamesRetry], async ([tab, project, type, principal, ids, conversionOpen, trainingOpen], previous, onCleanup) => {
  if (!previous || project !== previous[1] || type !== previous[2] || principal !== previous[3]) trainingDatasetVersions.value = new Map()
  trainingDatasetNamesLoading.value = false
  trainingDatasetNamesError.value = false
  if ((tab !== 'training' && !conversionOpen && !trainingOpen) || !project || !ids) return
  const missing = new Set(ids.split(',').filter(id => !trainingDatasetVersions.value.has(id)))
  if (!missing.size) return
  const controller = new AbortController()
  onCleanup(() => controller.abort())
  trainingDatasetNamesLoading.value = true
  const limit = 100
  const updated = new Map(trainingDatasetVersions.value)
  try {
    for (let offset = 0; missing.size; offset += limit) {
      const page = await listDatasetVersionPage({ project_id: project, task_type: type, offset, limit }, controller.signal)
      if (controller.signal.aborted) return
      for (const row of page.items) {
        if (missing.delete(row.dataset_version_id)) updated.set(row.dataset_version_id, { display_name: row.display_name, version_number: row.version_number })
      }
      if (!page.items.length || offset + limit >= page.total) break
    }
  } catch {
    if (!controller.signal.aborted) trainingDatasetNamesError.value = true
  } finally {
    if (!controller.signal.aborted) {
      trainingDatasetVersions.value = updated
      trainingDatasetNamesLoading.value = false
    }
  }
}, { immediate: true })

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
} = useTrainingDatasetExportSelection(namedTrainingDatasetExports)

function setErrorMessage(message: string | null): void {
  errorMessage.value = message
}

const {
  selectedModelDetail,
  selectedModelBrowseId,
  selectedModelDetailLoading,
  selectedModelDetailError,
  baseModelPickerOpen,
  warmStartModelVersionId,
  trainingSelectedModelSummary,
  selectedModelDerivedTrainingVersions,
  selectBaseModel,
  openBaseModelPicker,
  closeBaseModelPicker,
  applyTrainingModelSelection,
  applyTrainingVersionSelection,
  clearTrainingWarmStart,
  resetBaseModelBrowse,
  resetPlatformBaseModelSelection,
  ensureSelectedModelStillVisible,
  basePickerModels,
} = usePlatformBaseModelSelection({
  baseModels,
  pickerModels: computed(() => pickerUsesPageCatalog.value ? baseModels.value : pickerCatalog.value?.models ?? []),
  restrictPickerToTrainingModel: basePickerWeightsOnly,
  sourceModels: basePickerSources,
  detailFailedMessage: () => t('modelOps.messages.detailFailed'),
})
watch(baseModelPickerOpen, open => {
  if (open) return
  pickerRequest++
  pickerTaskType.value = null
  pickerCatalog.value = null
  pickerLoading.value = false
  pickerError.value = null
  basePickerFromCatalog.value = false
  basePickerWeightsOnly.value = false
  resetBaseModelBrowse()
}, { flush: 'sync' })

const {
  conversionModels, conversionSourcePickerOpen, conversionBrowseModelId,
  selectedConversionSource, conversionSelectedModelSummary, conversionModelType, conversionSourceModelVersionId,
  openConversionSourcePicker, selectConversionVersion, resetConversionSourceSelection,
  applyVersionSource,
} = useModelConversionSourceSelection({ sourceModels: projectSourceModels, projectId: selectedProjectId, taskType: selectedTaskType })
const conversionPickerTaskOverride = ref<ModelTaskType | null>(null)
const conversionPickerTask = computed(() => conversionPickerTaskOverride.value ?? selectedTaskType.value)
const conversionPickerUsesPage = computed(() => conversionPickerTask.value === selectedTaskType.value)
const conversionPickerSources = ref<DeploymentSourceModelSummary[]>([])
const conversionPickerError = ref('')
const conversionPickerLoading = ref(false)
const conversionPickerRevision = ref(0)
const conversionPickerModels = computed(() => conversionPickerUsesPage.value ? conversionModels.value
  : conversionPickerSources.value.filter(model => model.task_type === conversionPickerTask.value
    && (model.scope_kind === 'platform-base' || (model.scope_kind === 'project' && model.project_id === selectedProjectId.value))
    && model.available_versions.length))
const conversionPickerModel = computed(() => conversionPickerModels.value.find(model => model.model_id === conversionBrowseModelId.value) ?? null)

watch(conversionSourcePickerOpen, open => {
  if (!open) conversionPickerTaskOverride.value = null
}, { flush: 'sync' })
watch([conversionSourcePickerOpen, conversionPickerTask, conversionPickerUsesPage, selectedProjectId, conversionPickerRevision],
  async ([open, type, usesPage, projectId], _, onCleanup) => {
    conversionPickerSources.value = []
    conversionPickerError.value = ''
    conversionPickerLoading.value = open && !usesPage && Boolean(projectId)
    if (!conversionPickerLoading.value) return
    const request = new AbortController()
    onCleanup(() => request.abort())
    try {
      const models = await listDeploymentSourceModels(projectId, type, request.signal)
      if (!request.signal.aborted) conversionPickerSources.value = models
    } catch (error) {
      if (!request.signal.aborted) conversionPickerError.value = error instanceof Error ? error.message : t('modelOps.messages.loadFailed')
    } finally {
      if (!request.signal.aborted) conversionPickerLoading.value = false
    }
  })

function changeConversionPickerTask(value: string): void {
  const type = taskTypeOptions.value.find(option => option.value === value)?.value
  if (!type || type === conversionPickerTask.value) return
  conversionPickerTaskOverride.value = type
  conversionBrowseModelId.value = type === selectedTaskType.value ? selectedConversionSource.value?.model.model_id ?? '' : ''
}

function confirmConversionPickerVersion(versionId: string, modelId: string): void {
  if (conversionPickerUsesPage.value) {
    selectConversionVersion(versionId, modelId)
    return
  }
  const model = conversionPickerModels.value.find(item => item.model_id === modelId)
  const version = model?.available_versions.find(item => item.model_version_id === versionId)
  if (!model || !version || conversionSourceIssue(version)) return
  const taskType = conversionPickerTask.value
  conversionSourcePickerOpen.value = false
  void applyTaskType(taskType)
  applyVersionSource(model, versionId)
  void updateTaskTypeRoute(taskType)
}

watch(conversionSourceModelVersionId, (current, previous) => {
  if (previous && current !== previous) {
    tensorRtInt8.value = undefined
    openVinoInt8.value = undefined
  }
})
watch(conversionModelType, () => {
  conversionOpsetVersion.value = undefined
  conversionInputShapeMode.value = undefined
})
const conversionTargetOptions = computed(() => {
  const cuda = hasCudaDevice(sessionStore.bootstrap?.devices ?? null)
  const int8 = selectedTaskType.value === 'detection' && conversionModelType.value === 'yolo11'
  return baseConversionTargetOptions.filter(({ value }) =>
    (!value.startsWith('tensorrt-engine') || cuda) && (!value.endsWith('-int8') || int8),
  )
})
watch(conversionTargetOptions, (options) => {
  if (!options.some(option => option.value === conversionTarget.value)) conversionTarget.value = 'onnx'
}, { immediate: true })
watch([conversionTarget, selectedTaskType], () => {
  if (conversionTarget.value !== 'onnx' || selectedTaskType.value !== 'detection') conversionInputShapeMode.value = undefined
})

const resolvedTrainingManifestKey = computed(
  () => selectedTrainingDatasetExport.value?.manifest_object_key?.trim() ?? '',
)
const resolvedTrainingModelType = computed(
  () => trainingSelectedModelSummary.value?.model_type?.trim() ?? '',
)
const supportedTrainingExportFormats = computed(() => resolveSupportedTrainingExportFormats(
  selectedTaskType.value, resolvedTrainingModelType.value, trainingExportFormatsByTaskAndModelType.value,
))
const resolvedTrainingModelScale = computed(
  () => trainingSelectedModelSummary.value?.model_scale?.trim() ?? '',
)
const currentTrainingParameterSchema = computed<TrainingParameterSchemaItem | null>(() => {
  const modelType = resolvedTrainingModelType.value.toLowerCase()
  if (!modelType) return null
  return trainingParameterSchemas.value.find((item) => (
    item.task_type === selectedTaskType.value
    && item.model_type.toLowerCase() === modelType
  )) ?? null
})

const {
  outputModelName,
  trainingRecipeId,
  applySavedTrainingParameters,
  maxEpochs,
  batchMode,
  batchSize,
  batchTargetMemoryFraction,
  batchMinimumSize,
  batchMaximumSize,
  batchRecoverOnOom,
  batchMaxOomRetries,
  trainingDevice,
  evaluationInterval,
  ampMode,
  ampDtype,
  checkpointInterval,
  checkpointKeepPeriodic,
  inputWidth,
  inputHeight,
  trainingDisplayName,
  trainingModelParameterValues,
  trainingAugmentationEnabled,
  trainingTaskSupportsWarmStart,
  trainingModelParameterFields,
  trainingAugmentationParameterFields,
  trainingSupportsAugmentationToggle,
  trainingModelParameterSectionTitle,
  setBatchMode,
  setAmpMode,
  setAmpDtype,
  setTrainingDevice,
  setTrainingModelParameterValue,
  syncSuggestedOutputModelName,
  resetSuggestedOutputModelName,
  alignTrainingInputSizeForSubmit,
} = useTrainingParameters({
  selectedTaskType,
  resolvedTrainingModelType,
  resolvedTrainingModelScale,
  trainingParameterSchema: currentTrainingParameterSchema,
  isOutputModelNameTaken,
  translate: (key, params) => t(key, params ?? {}),
})
const outputModelNameTaken = computed(() => isOutputModelNameTaken(outputModelName.value))
watch(trainingSelectedModelSummary, model => {
  if (model) syncSuggestedOutputModelName(model, trainingDatasetTitle.value)
})

watch(trainingDeviceOptions, (options) => {
  if (!trainingDevice.value) return
  if (options.some((option) => option.value === trainingDevice.value)) return
  setTrainingDevice('')
}, { immediate: true })

const {
  trainingSubmitting,
  lastTrainingSubmission,
  trainingSubmissionUncertain,
  submitTraining,
  validateTrainingSelection,
  validateTrainingConfiguration,
  previewTraining,
  resetTrainingSubmission,
  trainingReceipt,
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
  trainingRecipeId,
  warmStartModelVersionId,
  trainingTaskSupportsWarmStart,
  evaluationInterval,
  maxEpochs,
  batchMode,
  batchSize,
  batchTargetMemoryFraction,
  batchMinimumSize,
  batchMaximumSize,
  batchRecoverOnOom,
  batchMaxOomRetries,
  trainingDevice,
  ampMode,
  ampDtype,
  checkpointInterval,
  checkpointKeepPeriodic,
  inputWidth,
  inputHeight,
  trainingDisplayName,
  trainingModelParameterValues,
  trainingAugmentationEnabled,
  trainingParameterSchema: currentTrainingParameterSchema,
  trainingExportFormatsByTaskAndModelType,
  alignTrainingInputSizeForSubmit,
  refreshTrainingTasks,
  principalId: submissionPrincipal,
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
const trainingConfigurationError = computed(() => validateTrainingConfiguration())
const trainingSelectionError = computed(() => validateTrainingSelection())

const {
  conversionSubmitting,
  lastConversionSubmission,
  conversionSubmissionUncertain,
  submitConversion,
  resetConversionSubmission,
  conversionReceipt,
} = useModelConversionState({
  selectedTaskType,
  selectedProjectId,
  selectedSource: selectedConversionSource,
  canWriteTasks,
  conversionTarget,
  conversionRuntimeProfileId,
  onnxOpsetVersion: conversionOpsetVersion,
  inputShapeMode: conversionInputShapeMode,
  tensorRtInt8,
  openVinoInt8,
  conversionDisplayName,
  refreshConversionTasks,
  principalId: submissionPrincipal,
  setErrorMessage,
  submitConversionFailedMessage: () => t('modelOps.messages.submitConversionFailed'),
})

const canDeployModelVersion = computed(() => canWriteModels.value && canAccessPage(sessionStore.currentUser, 'deployments'))
const versionConversionLoading = ref(false)
const versionActionError = ref('')
let versionActionSequence = 0

function resetVersionAction(): void {
  versionActionSequence += 1
  versionConversionLoading.value = false
  versionActionError.value = ''
}

watch([selectedProjectId, submissionPrincipal, activeTab], resetVersionAction, { flush: 'sync' })

async function startVersionConversion(source: ModelVersionAction): Promise<void> {
  if (versionConversionLoading.value || !canWriteTasks.value || source.projectId !== selectedProjectId.value) return
  resetVersionAction()
  const sequence = versionActionSequence
  versionConversionLoading.value = true
  const unavailable = zh.value ? '此版本的原始权重或类别信息不可用，请刷新后重试。' : 'The original weights or class information are unavailable. Refresh and try again.'
  try {
    const model = await getDeploymentSourceModelDetail(source.projectId, source.modelId)
    if (sequence !== versionActionSequence) return
    const version = model.available_versions.find(item => item.model_version_id === source.versionId)
    if (model.project_id !== source.projectId || model.scope_kind !== 'project' || model.task_type !== source.taskType
      || !version?.checkpoint_file_id || conversionSourceIssue(version)) {
      versionActionError.value = unavailable
      return
    }
    const status = await getProjectModelFileStatus({ ...source, fileId: version.checkpoint_file_id })
    if (sequence !== versionActionSequence || !canWriteTasks.value) return
    if (status.state !== 'present') {
      versionActionError.value = unavailable
      return
    }
    if (selectedTaskType.value !== source.taskType) void applyTaskType(source.taskType)
    if (!conversionSubmissionUncertain.value && !applyVersionSource(model, source.versionId)) {
      versionActionError.value = unavailable
      return
    }
    conversionWizardOpen.value = !conversionSubmissionUncertain.value
    activeTab.value = 'conversion'
  } catch {
    if (sequence === versionActionSequence) versionActionError.value = zh.value ? '无法确认版本文件，请重试。' : 'Could not verify the version files. Try again.'
  } finally {
    if (sequence === versionActionSequence) versionConversionLoading.value = false
  }
}

function startVersionDeployment(source: ModelVersionAction): void {
  if (!router || !canDeployModelVersion.value || source.projectId !== selectedProjectId.value) return
  void router.push({
    path: '/deployments',
    query: { sourceProject: source.projectId, sourceModel: source.modelId, sourceVersion: source.versionId, sourceTask: source.taskType, sourceBuild: source.buildId },
  })
}

async function checkModelSubmission(kind: 'training' | 'conversion'): Promise<void> {
  const receipt = kind === 'training' ? trainingReceipt : conversionReceipt
  const taskType = selectedTaskType.value
  const taskId = receipt.acceptedTaskId.value ?? await receipt.check()
  if (!taskId || !router || receipt.acceptedTaskId.value !== taskId) return
  const path = `/models/${taskType}/${kind}-tasks/${encodeURIComponent(taskId)}`
  try {
    await router.push(path)
    if (router.currentRoute.value.path === path) receipt.viewed(taskId)
  } catch {
    // 保留已找到的任务，用户可再次打开详情。
  }
}

onMounted(async () => {
  const deviceBootstrap = sessionStore.ensureDeviceBootstrap()
  if (projectStore.projects.length === 0) {
    await projectStore.loadProjects()
  }
  const task=transferRoute?.query.task, id=transferRoute?.query.datasetExport
  const trainingFrom = transferRoute?.query.trainingFrom
  const conversionFrom = transferRoute?.query.conversionFrom
  if ((typeof id === 'string' || typeof trainingFrom === 'string' || typeof conversionFrom === 'string' || transferRoute?.query.tab === 'training' || transferRoute?.query.tab === 'conversion') && taskTypeOptions.value.some(item => item.value === task)) selectedTaskType.value = task as ModelTaskType
  const pageReady = refreshPage()
  if (typeof conversionFrom === 'string' && conversionFrom) {
    await loadConversionCopy(conversionFrom, pageReady, deviceBootstrap)
    return
  }
  if (typeof trainingFrom === 'string' && trainingFrom) {
    await loadTrainingCopy(trainingFrom, pageReady, deviceBootstrap)
    return
  }
  await pageReady
  const resource=trainingDatasetExports.value.find(item=>item.dataset_export_id===id && !item.metadata.files_cleaned_at)
  if(resource)applyTrainingDatasetExport(resource)
})

function startConversionWizard(): void {
  if (transferRoute?.query.conversionFrom) closeConversionWizard()
  conversionWizardOpen.value = true
}

function closeConversionWizard(): void {
  conversionWizardOpen.value = false
  conversionCopyRequest?.abort()
  conversionCopyLoading.value = false
  conversionCopyMessage.value = ''
  if (!transferRoute?.query.conversionFrom) return
  resetConversionSourceSelection()
  conversionTarget.value = 'onnx'
  conversionRuntimeProfileId.value = ''
  conversionDisplayName.value = ''
  conversionOpsetVersion.value = undefined
  conversionInputShapeMode.value = undefined
  tensorRtInt8.value = undefined
  openVinoInt8.value = undefined
  if (router && transferRoute.path === '/models') {
    void router.replace({ query: { ...transferRoute.query, conversionFrom: undefined } })
  }
}

async function loadConversionCopy(taskId: string, pageReady: Promise<boolean>, deviceBootstrap: Promise<unknown>): Promise<void> {
  const taskType = selectedTaskType.value
  const projectId = selectedProjectId.value
  const principal = submissionPrincipal.value
  if (!canWriteTasks.value || !canWriteModels.value || !projectId) return
  const request = new AbortController()
  conversionCopyRequest = request
  conversionCopyLoading.value = true
  const isCurrent = () => !request.signal.aborted && transferRoute?.query.conversionFrom === taskId
    && projectId === selectedProjectId.value && principal === submissionPrincipal.value && taskType === selectedTaskType.value
  try {
    const [source, ready] = await Promise.all([getModelConversionTaskDetail(taskType, taskId, request.signal), pageReady, deviceBootstrap.catch(() => null)])
    if (!isCurrent()) return
    if (!ready || source.project_id !== projectId || source.task_id !== taskId) {
      throw new Error(zh.value ? '无法在当前项目读取原转换配置。' : 'The original conversion configuration could not be loaded in this project.')
    }
    if (conversionSubmitting.value || conversionSubmissionUncertain.value) {
      throw new Error(zh.value ? '请先确认当前转换的提交结果。' : 'Check the current conversion submission first.')
    }
    const versionId = source.source_model_version_id
    const model = conversionModels.value.find(item => item.available_versions.some(version => version.model_version_id === versionId))
    const messages: string[] = []
    if (!model || !applyVersionSource(model, versionId)) {
      messages.push(zh.value ? '原模型版本不可用，请重新选择来源。' : 'The original model version is unavailable. Choose a source version.')
    }
    const target = readConversionTarget(source)
    const options = conversionRecord(source.task_spec?.extra_options)
    const int8 = target === 'tensorrt-engine-int8' ? readConversionInt8Settings(options) : undefined
    const openVinoSamples = target === 'openvino-ir-int8' ? readConversionInt8Samples(options) : undefined
    await nextTick()
    if (!isCurrent()) return
    resetConversionSubmission()
    conversionTarget.value = target ?? 'onnx'
    conversionRuntimeProfileId.value = source.runtime_profile_id ?? ''
    conversionDisplayName.value = ''
    await nextTick()
    if (!isCurrent()) return
    conversionOpsetVersion.value = typeof options.onnx_opset_version === 'number' ? options.onnx_opset_version : undefined
    conversionInputShapeMode.value = target === 'onnx' && options.input_shape_mode === 'dynamic-batch' ? 'dynamic-batch' : undefined
    tensorRtInt8.value = int8
    openVinoInt8.value = openVinoSamples
    if (!target || !conversionTargetOptions.value.some(option => option.value === target)) {
      messages.push(zh.value ? '请在目标步骤核对原目标格式和可用环境。' : 'Review the original target format and available environment in the target step.')
    } else if ((target === 'tensorrt-engine-int8' && !int8) || (target === 'openvino-ir-int8' && !openVinoSamples)) {
      messages.push(zh.value ? '原 INT8 参数不完整，请重新设置校准和校验。' : 'The original INT8 settings are incomplete. Set calibration and validation again.')
    }
    conversionCopyMessage.value = messages.join(' ')
    conversionWizardOpen.value = true
  } catch (error) {
    if (isCurrent()) conversionCopyMessage.value = error instanceof Error ? error.message : t('modelOps.messages.loadFailed')
  } finally {
    if (conversionCopyRequest === request) {
      conversionCopyRequest = null
      conversionCopyLoading.value = false
    }
  }
}

async function loadTrainingCopy(taskId: string, pageReady: Promise<boolean>, deviceBootstrap: Promise<unknown>): Promise<void> {
  const taskType = selectedTaskType.value
  const projectId = selectedProjectId.value
  const principal = submissionPrincipal.value
  if (!canWriteTasks.value || !projectId) return
  const request = new AbortController()
  trainingCopyRequest = request
  trainingCopyLoading.value = true
  const isCurrent = () => !request.signal.aborted && transferRoute?.query.trainingFrom === taskId
    && projectId === selectedProjectId.value && principal === submissionPrincipal.value && taskType === selectedTaskType.value
  try {
    const [source, ready] = await Promise.all([
      getModelTrainingTaskDetail(taskType, taskId, request.signal), pageReady, deviceBootstrap.catch(() => null),
    ])
    if (!isCurrent()) return
    if (!ready || source.project_id !== projectId || source.task_id !== taskId) {
      throw new Error(zh.value ? '无法在当前项目读取原训练配置。' : 'The original training configuration could not be loaded in this project.')
    }
    if (trainingSubmitting.value || trainingSubmissionUncertain.value) {
      throw new Error(zh.value ? '请先确认当前训练的提交结果。' : 'Check the current training submission first.')
    }
    const spec = source.task_spec
    const modelType = savedTrainingText(spec.model_type || source.model_type).toLowerCase()
    const modelScale = savedTrainingText(spec.model_scale || source.model_scale).toLowerCase()
    const model = baseModels.value.find(item => item.model_type.toLowerCase() === modelType && item.model_scale.toLowerCase() === modelScale)
    const exportId = savedTrainingText(spec.dataset_export_id || source.dataset_export_id)
    const manifestKey = savedTrainingText(spec.dataset_export_manifest_key || source.dataset_export_manifest_key)
    const dataset = exportId ? (trainingDatasetExports.value.find(item => item.dataset_export_id === exportId)
      ?? await getDatasetExportDetail(exportId).catch(() => null)) : null
    if (!isCurrent()) return

    const messages: string[] = []
    const warmStart = savedTrainingText(spec.warm_start_model_version_id)
    if (model) {
      if (warmStart) applyTrainingVersionSelection({ model, modelVersionId: warmStart })
      else applyTrainingModelSelection(model)
    } else {
      messages.push(zh.value ? '原模型规格已不可选，请重新选择模型和初始化方式。' : 'The original model is unavailable. Choose a model and initialization method.')
    }
    if (dataset && dataset.project_id === projectId && dataset.task_type === taskType && dataset.status === 'completed'
      && !dataset.metadata.files_cleaned_at && dataset.manifest_object_key && (!manifestKey || dataset.manifest_object_key === manifestKey)) {
      if (!trainingDatasetExports.value.some(item => item.dataset_export_id === exportId)) {
        copiedDatasetExport.value = dataset
        trainingDatasetExports.value = [dataset, ...trainingDatasetExports.value]
      }
      applyTrainingDatasetExport(dataset)
    } else {
      messages.push(zh.value ? '原数据集导出已不可用，请重新选择数据。' : 'The original dataset export is unavailable. Choose your training data.')
    }
    const extra = spec.extra_options as Record<string, unknown> | undefined
    const device = savedTrainingText(extra?.requested_device ?? extra?.device)
    const deviceAvailable = !device || device === 'auto' || trainingDeviceOptions.value.some(option => option.value === device)
    if (!deviceAvailable) messages.push(zh.value ? `原训练设备 ${device} 已不可选，请在训练参数中核对设备。` : `The original device ${device} is unavailable. Review the device in the training parameters.`)
    await nextTick()
    if (!isCurrent()) return
    restoreTrainingParameters = applySavedTrainingParameters(source, deviceAvailable && device !== 'auto' ? device : '')
    trainingCopyMessage.value = messages.join(' ')
    trainingCopyLoading.value = false
    startTraining()
  } catch (error) {
    if (isCurrent()) trainingCopyMessage.value = error instanceof Error ? error.message : t('modelOps.messages.loadFailed')
  } finally {
    if (trainingCopyRequest === request) {
      trainingCopyRequest = null
      trainingCopyLoading.value = false
    }
  }
}

function normalizeSelectValue(value: SelectValue): string {
  return typeof value === 'string' ? value : String(value ?? '')
}

async function setTaskType(value: SelectValue): Promise<void> {
  const nextValue = normalizeSelectValue(value)
  if (nextValue === selectedTaskType.value || !taskTypeOptions.value.some((option) => option.value === nextValue)) {
    return
  }
  if (router && transferRoute?.path === '/models') {
    if (transferRoute.query.trainingFrom) resetTrainingCopy()
    await updateTaskTypeRoute(nextValue)
    return
  }
  await applyTaskType(nextValue as ModelTaskType)
}

async function updateTaskTypeRoute(task: string): Promise<void> {
  if (router && transferRoute?.path === '/models') {
    await router.replace({ query: { ...transferRoute.query, task, page: undefined, datasetExport: undefined, trainingFrom: undefined } })
  }
}

watch(() => transferRoute?.query.task, (value) => {
  if (value === undefined && readTab() !== 'training' && readTab() !== 'conversion') return
  const taskType = taskTypeOptions.value.find(option => option.value === value)?.value ?? 'detection'
  if (taskType !== selectedTaskType.value) void applyTaskType(taskType)
})

async function applyTaskType(nextValue: ModelTaskType, selection?: { model: PlatformBaseModelDetail; modelVersionId?: string }): Promise<void> {
  selectedTaskType.value = nextValue
  baseModels.value = []
  projectSourceModels.value = []
  trainingDatasetExports.value = []
  trainingParameterSchemas.value = []
  trainingTasks.value = []
  conversionTasks.value = []
  resetPlatformBaseModelSelection()
  resetConversionSourceSelection(conversionSourcePickerOpen.value)
  lastTrainingSubmission.value = null
  resetTrainingDatasetExportSelection()
  trainingDatasetTitle.value = ''
  if (selection) commitTrainingSelection(selection)
  else resetSuggestedOutputModelName()
  await refreshPage()
}

function setConversionTarget(value: SelectValue): void {
  conversionTarget.value = (normalizeSelectValue(value) || 'onnx') as ConversionTargetKey
}

watch([selectedProjectId, submissionPrincipal], async () => {
  if (trainingCopyLoading.value || restoreTrainingParameters) closeTrainingWizard()
  if (transferRoute?.query.conversionFrom) closeConversionWizard()
  resetPlatformBaseModelSelection()
  resetConversionSourceSelection()
  resetTrainingDatasetExportSelection()
  resetSuggestedOutputModelName()
  lastTrainingSubmission.value = null
  projectSourceModels.value = []
  trainingDatasetExports.value = []
  trainingTasks.value = []
  conversionTasks.value = []
  await refreshPage()
})

async function refreshPage(): Promise<boolean> {
  const requestSerial = ++pageRequestSerial
  const taskType = selectedTaskType.value
  const projectId = selectedProjectId.value
  loading.value = true
  errorMessage.value = null
  void refreshTaskLists()
  try {
    const [models, sourceModels, datasetExports, parameterCatalog] = await Promise.all([
      listPlatformBaseModels(taskType),
      projectId
        ? listDeploymentSourceModels(projectId, taskType)
        : Promise.resolve<DeploymentSourceModelSummary[]>([]),
      projectId
        ? listProjectDatasetExports(projectId, taskType, 'completed')
        : Promise.resolve<DatasetExportSummary[]>([]),
      listTrainingParameterSchemas(taskType),
    ])
    if (
      requestSerial !== pageRequestSerial
      || selectedTaskType.value !== taskType
      || selectedProjectId.value !== projectId
    ) {
      return false
    }
    if (parameterCatalog.protocol_version !== 1) {
      throw new Error(`不支持的训练参数协议版本: ${parameterCatalog.protocol_version}`)
    }
    const catalogModelTypes = new Set(
      parameterCatalog.items.map((item) => item.model_type.toLowerCase()),
    )
    const missingModelTypes = [...new Set(
      models
        .map((model) => model.model_type.toLowerCase())
        .filter((modelType) => !catalogModelTypes.has(modelType)),
    )]
    if (missingModelTypes.length > 0) {
      throw new Error(`训练参数目录缺少模型: ${missingModelTypes.join(', ')}`)
    }
    baseModels.value = models
    projectSourceModels.value = sourceModels
    const copied = copiedDatasetExport.value
    trainingDatasetExports.value = copied?.project_id === projectId && copied.task_type === taskType
      && !datasetExports.some(item => item.dataset_export_id === copied.dataset_export_id) ? [copied, ...datasetExports] : datasetExports
    trainingParameterSchemas.value = parameterCatalog.items
    ensureSelectedModelStillVisible()
    ensureTrainingDatasetExportSelectionVisible()
    if (baseModelPickerOpen.value && pickerUsesPageCatalog.value && !selectedModelBrowseId.value) {
      void openBaseModelPicker()
    }
    return true
  } catch (error) {
    if (requestSerial === pageRequestSerial) {
      errorMessage.value = error instanceof Error ? error.message : t('modelOps.messages.loadFailed')
    }
    return false
  } finally {
    if (requestSerial === pageRequestSerial) {
      loading.value = false
    }
  }
}

const trainingDatasetTitle = ref('')
const trainingWarmStartLabel = computed(() => {
  const model = trainingWarmStartModel.value
  const version = trainingWarmStartVersion.value
  return model && version ? `${modelDisplayName(model)} · ${modelVersionDisplayName(version, true)}` : ''
})
const trainingWarmStartModel = computed(() => {
  const id = warmStartModelVersionId.value
  return [...projectSourceModels.value, ...baseModels.value].find(item => item.available_versions.some(version => version.model_version_id === id))
})
const trainingWarmStartVersion = computed(() => trainingWarmStartModel.value?.available_versions.find(version => version.model_version_id === warmStartModelVersionId.value))
const trainingWarmStartSource = computed(() => {
  if (!trainingWarmStartModel.value) return ''
  return trainingWarmStartModel.value.scope_kind === 'project'
    ? (zh.value ? '项目训练版本' : 'Project training version')
    : (zh.value ? '平台基础模型' : 'Platform base model')
})
const trainingWarmStartFileName = computed(() => trainingWarmStartVersion.value?.checkpoint_storage_uri?.split(/[\\/]/).pop() ?? '')
const trainingWarmStartFileStatus = computed(() => {
  const state = trainingWarmStartVersion.value?.checkpoint_state
  if (state === 'present') return zh.value ? '文件存在' : 'File present'
  if (state === 'missing') return zh.value ? '文件缺失' : 'File missing'
  return state === 'unavailable' ? (zh.value ? '无法检查' : 'Cannot check') : ''
})
function syncTrainingDatasetName(name: string): void {
  trainingDatasetTitle.value = name
  if (trainingSelectedModelSummary.value) syncSuggestedOutputModelName(trainingSelectedModelSummary.value, name)
}

function isOutputModelNameTaken(name: string): boolean {
  const normalized = name.trim().toLowerCase()
  return !!normalized && projectSourceModels.value.some(model => model.scope_kind === 'project'
    && [model.model_name, modelDisplayName(model)].some(value => value.trim().toLowerCase() === normalized))
}

function commitTrainingSelection({ model, modelVersionId }: { model: PlatformBaseModelDetail; modelVersionId?: string }): void {
  if (modelVersionId) applyTrainingVersionSelection({ model, modelVersionId })
  else applyTrainingModelSelection(model)
  syncSuggestedOutputModelName(model, trainingDatasetTitle.value)
}

function applyPickerModel(selection: { model: PlatformBaseModelDetail; modelVersionId?: string }): void {
  const task = pickerTaskType.value ?? selectedTaskType.value
  if (selection.model.task_type !== task) return
  const fromCatalog = basePickerFromCatalog.value
  closeBaseModelPicker()
  if (task === selectedTaskType.value) commitTrainingSelection(selection)
  else {
    if (transferRoute?.query.trainingFrom) resetTrainingCopy()
    void applyTaskType(task, selection)
    void updateTaskTypeRoute(task)
  }
  if (fromCatalog) startTraining()
}

function openCatalogBaseModels(): void {
  basePickerFromCatalog.value = true
  openTrainingBaseModelPicker()
}

function openTrainingBaseModelPicker(): void {
  basePickerWeightsOnly.value = false
  pickerTaskType.value = selectedTaskType.value
  void openBaseModelPicker()
}

function openTrainingWeightPicker(): void {
  basePickerWeightsOnly.value = true
  pickerTaskType.value = selectedTaskType.value
  void openBaseModelPicker()
}

function selectPickerTaskType(value: string): void {
  const task = taskTypeOptions.value.find(option => option.value === value)?.value
  if (!task || task === pickerTaskType.value) return
  pickerTaskType.value = task
  resetBaseModelBrowse()
  void refreshPickerCatalog()
}

async function refreshPickerCatalog(): Promise<void> {
  const request = ++pickerRequest
  const task = pickerTaskType.value
  pickerCatalog.value = null
  pickerError.value = null
  if (!task || pickerUsesPageCatalog.value) {
    pickerLoading.value = false
    if (errorMessage.value || !baseModels.value.length) await refreshPage()
    if (request === pickerRequest && !selectedModelBrowseId.value) void openBaseModelPicker()
    return
  }
  pickerLoading.value = true
  try {
    const project = selectedProjectId.value
    const [models, sources] = await Promise.all([
      listPlatformBaseModels(task),
      project ? listDeploymentSourceModels(project, task) : Promise.resolve([]),
    ])
    if (request !== pickerRequest) return
    pickerCatalog.value = { models, sources }
    void openBaseModelPicker()
  } catch (error) {
    if (request === pickerRequest) pickerError.value = error instanceof Error ? error.message : t('modelOps.messages.loadFailed')
  } finally {
    if (request === pickerRequest) pickerLoading.value = false
  }
}

</script>

<style scoped>
.model-ops-grid {
  align-items: start;
  grid-template-columns: minmax(0, 1fr);
}
.model-ops-navigation { display:flex; flex-wrap:wrap; justify-content:space-between; align-items:center; gap:10px 24px; margin-block-end:4px; border-bottom:1px solid var(--am-border); }
.model-ops-navigation__actions { display:flex; flex-wrap:wrap; align-items:center; justify-content:flex-end; gap:12px; margin-inline-start:auto; padding-block:4px 8px; }
.model-ops-navigation :deep(.local-tabs) { border:0; gap:8px; }
.model-ops-navigation :deep(.local-tabs__tab) { min-height:44px; padding-inline:16px; border:0; border-bottom:3px solid transparent; border-radius:var(--am-radius-sm) var(--am-radius-sm) 0 0; background:transparent; color:var(--am-text); }
.model-ops-navigation :deep(.local-tabs__tab:not(.is-active):hover) { background:var(--am-hover-surface); }
.model-ops-navigation :deep(.local-tabs__tab.is-active) { border-bottom-color:var(--am-brand-primary); background:transparent; color:var(--am-brand-primary); }
</style>
