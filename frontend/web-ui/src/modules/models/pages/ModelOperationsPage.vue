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
      <form class="form-panel model-ops-form" @submit.prevent="submitTraining">
        <div>
          <p class="page-kicker">{{ t('modelOps.trainingKicker') }}</p>
          <h2>{{ t('modelOps.trainingTitle') }}</h2>
        </div>
        <div class="form-grid model-ops-form__grid">
          <div class="field field--wide model-picker-field">
            <div class="model-picker-field__header">
              <div class="model-picker-field__title">
                <span>{{ t('modelOps.fields.trainingBaseModel') }}</span>
                <span class="model-picker-chip">{{ selectedTaskType }}</span>
              </div>
              <Button size="sm" variant="secondary" type="button" :disabled="loading || baseModels.length === 0" @click="openBaseModelPicker('training')">
                {{ t('modelOps.actions.chooseBaseModel') }}
              </Button>
            </div>
            <div class="model-picker-summary" :class="{ 'is-empty': !trainingSelectedModelSummary }">
              <template v-if="trainingSelectedModelSummary">
                <div class="model-picker-summary__top">
                  <div class="model-picker-summary__identity">
                    <strong>{{ trainingSelectedModelSummary.model_name }}</strong>
                    <span>{{ trainingSelectedModelSummary.model_id }}</span>
                  </div>
                  <div class="model-picker-summary__chips">
                    <span class="model-picker-chip">{{ trainingSelectedModelSummary.model_type }}</span>
                    <span class="model-picker-chip">{{ t('modelOps.columns.scale') }} · {{ trainingSelectedModelSummary.model_scale }}</span>
                  </div>
                </div>
              </template>
              <template v-else>
                <strong>{{ t('modelOps.baseModelEmptyTitle') }}</strong>
                <span>{{ t('modelOps.baseModelEmptyDescription') }}</span>
              </template>
            </div>
          </div>
          <div class="field field--wide model-picker-field">
            <div class="model-picker-field__header">
              <div class="model-picker-field__title">
                <span>{{ t('modelOps.fields.trainingDatasetExport') }}</span>
                <span class="model-picker-chip">{{ selectedTaskType }}</span>
              </div>
              <Button
                size="sm"
                variant="secondary"
                type="button"
                :disabled="loading || trainingDatasetExports.length === 0"
                @click="openTrainingDatasetExportPicker"
              >
                {{ selectedTrainingDatasetExport ? t('modelOps.actions.changeTrainingDatasetExport') : t('modelOps.actions.chooseTrainingDatasetExport') }}
              </Button>
            </div>
            <div class="model-picker-summary" :class="{ 'is-empty': !selectedTrainingDatasetExport }">
              <template v-if="selectedTrainingDatasetExport">
                <div class="model-picker-summary__top">
                  <div class="model-picker-summary__identity">
                    <strong>{{ selectedTrainingDatasetExport.dataset_export_id }}</strong>
                    <span>{{ t('datasetOps.fields.datasetVersionId') }} {{ selectedTrainingDatasetExport.dataset_version_id }}</span>
                  </div>
                  <div class="model-picker-summary__chips">
                    <span class="model-picker-chip">{{ selectedTrainingDatasetExport.task_type }}</span>
                    <span class="model-picker-chip">{{ selectedTrainingDatasetExport.format_id }}</span>
                  </div>
                </div>
                <div class="model-picker-summary__grid">
                  <div class="model-picker-summary__item">
                    <span>{{ t('datasetOps.fields.datasetId') }}</span>
                    <strong>{{ selectedTrainingDatasetExport.dataset_id }}</strong>
                  </div>
                  <div class="model-picker-summary__item">
                    <span>{{ t('datasetOps.columns.samples') }}</span>
                    <strong>{{ selectedTrainingDatasetExport.sample_count }}</strong>
                  </div>
                  <div class="model-picker-summary__item">
                    <span>{{ t('modelOps.columns.createdAt') }}</span>
                    <strong>{{ formatSystemDateTime(selectedTrainingDatasetExport.created_at) }}</strong>
                  </div>
                  <div class="model-picker-summary__item">
                    <span>{{ t('datasetOps.fields.categoryNames') }}</span>
                    <strong>{{ selectedTrainingDatasetExport.category_names.join(', ') || t('common.noValue') }}</strong>
                  </div>
                </div>
              </template>
              <template v-else>
                <strong>{{ t('modelOps.trainingDatasetExportEmptyTitle') }}</strong>
                <span>{{ t('modelOps.trainingDatasetExportEmptyDescription') }}</span>
              </template>
            </div>
          </div>
          <section class="training-parameter-section field field--wide">
            <div class="training-parameter-section__header">
              <div>
                <p class="page-kicker">COMMON</p>
                <h3>通用参数</h3>
              </div>
            </div>
            <div class="form-grid training-parameter-grid">
              <label class="field">
                <span>{{ t('modelOps.fields.outputModelName') }}</span>
                <input v-model="outputModelName" required />
              </label>
              <label class="field">
                <span>{{ t('modelOps.fields.maxEpochs') }}</span>
                <input v-model.number="maxEpochs" type="number" min="1" />
              </label>
              <label class="field">
                <span>{{ t('modelOps.fields.batchSize') }}</span>
                <input v-model.number="batchSize" type="number" min="1" />
              </label>
              <label class="field">
                <span>{{ t('modelOps.fields.precision') }}</span>
                <SelectField :model-value="precision" :options="precisionOptions" @update:model-value="setPrecision" />
              </label>
              <label class="field">
                <span>{{ t('modelOps.fields.inputWidth') }}</span>
                <input v-model.number="inputWidth" type="number" min="32" step="32" />
              </label>
              <label class="field">
                <span>{{ t('modelOps.fields.inputHeight') }}</span>
                <input v-model.number="inputHeight" type="number" min="32" step="32" />
              </label>
              <label class="field">
                <span>{{ t('modelOps.fields.evaluationInterval') }}</span>
                <input v-model.number="evaluationInterval" type="number" min="1" />
              </label>
              <label v-if="trainingSupportsGpuCount" class="field">
                <span>{{ t('modelOps.fields.gpuCount') }}</span>
                <input v-model.number="gpuCount" type="number" min="1" step="1" />
              </label>
              <div v-if="trainingTaskSupportsWarmStart" class="field field--wide">
                <span>{{ t('modelOps.fields.warmStart') }}</span>
                <div class="training-inline-summary" :class="{ 'is-empty': !warmStartModelVersionId.trim() }">
                  <strong>{{ warmStartModelVersionId || '当前未选择继续训练来源版本' }}</strong>
                  <span>
                    {{ warmStartModelVersionId ? '已选择继续训练来源版本。' : '未选择时从当前基础模型默认版本开始训练。' }}
                  </span>
                  <div class="training-inline-summary__actions">
                    <Button
                      v-if="warmStartModelVersionId"
                      size="sm"
                      variant="ghost"
                      type="button"
                      @click="clearTrainingWarmStart"
                    >
                      {{ t('common.filePicker.clear') }}
                    </Button>
                  </div>
                </div>
              </div>
              <label class="field field--wide">
                <span>{{ t('modelOps.fields.trainingDisplayName') }}</span>
                <input v-model="trainingDisplayName" />
              </label>
            </div>
          </section>

          <section v-if="trainingModelParameterFields.length > 0" class="training-parameter-section field field--wide">
            <div class="training-parameter-section__header">
              <div>
                <p class="page-kicker">MODEL TYPE</p>
                <h3>{{ trainingModelParameterSectionTitle }}</h3>
              </div>
              <span class="training-parameter-section__hint">已按当前模型预填默认值，可按需修改</span>
            </div>
            <div class="form-grid training-parameter-grid">
              <label
                v-for="field in trainingModelParameterFields"
                :key="field.key"
                class="field"
                :class="{ 'field--wide': field.wide }"
              >
                <span>{{ field.label }}</span>
                <SelectField
                  v-if="field.inputKind === 'select'"
                  :model-value="trainingModelParameterValues[field.key] ?? ''"
                  :options="field.options ?? []"
                  @update:model-value="setTrainingModelParameterValue(field.key, $event)"
                />
                <input
                  v-else
                  v-model="trainingModelParameterValues[field.key]"
                  :type="field.inputKind"
                  :min="field.min"
                  :max="field.max"
                  :step="field.step"
                  :placeholder="field.placeholder"
                />
              </label>
            </div>
          </section>
        </div>
        <div class="form-actions">
          <Button
            variant="primary"
            type="submit"
            :disabled="!canWriteTasks || trainingSubmitting"
          >
            <Play :size="16" />
            {{ trainingSubmitting ? t('modelOps.actions.submitting') : t('modelOps.actions.submitTraining') }}
          </Button>
        </div>
        <p v-if="lastTrainingSubmission" class="result-note">
          {{ t('modelOps.messages.trainingSubmitted') }}
          <RouterLink :to="`/tasks/${lastTrainingSubmission.task_id}`">{{ lastTrainingSubmission.task_id }}</RouterLink>
        </p>
      </form>

      <form class="form-panel model-ops-form" @submit.prevent="submitConversion">
        <div>
          <p class="page-kicker">{{ t('modelOps.conversionKicker') }}</p>
          <h2>{{ t('modelOps.conversionTitle') }}</h2>
        </div>
        <div class="form-grid model-ops-form__grid">
          <div class="field field--wide model-picker-field">
            <div class="model-picker-field__header">
              <div class="model-picker-field__title">
                <span>{{ t('modelOps.fields.conversionBaseModel') }}</span>
                <span class="model-picker-chip">{{ selectedTaskType }}</span>
              </div>
              <Button size="sm" variant="secondary" type="button" :disabled="loading || baseModels.length === 0" @click="openBaseModelPicker('conversion')">
                {{ t('modelOps.actions.chooseConversionSource') }}
              </Button>
            </div>
            <div class="model-picker-summary" :class="{ 'is-empty': !conversionSelectedModelSummary }">
              <template v-if="conversionSelectedModelSummary">
                <div class="model-picker-summary__top">
                  <div class="model-picker-summary__identity">
                    <strong>{{ conversionSelectedModelSummary.model_name }}</strong>
                    <span>{{ conversionSelectedModelSummary.model_id }}</span>
                  </div>
                  <div class="model-picker-summary__chips">
                    <span class="model-picker-chip">{{ conversionSelectedModelSummary.model_type }}</span>
                    <span class="model-picker-chip">{{ t('modelOps.columns.scale') }} · {{ conversionSelectedModelSummary.model_scale }}</span>
                  </div>
                </div>
                <div class="model-picker-summary__footer">
                  <span>{{ t('modelOps.fields.sourceModelVersionId') }}: {{ conversionSourceModelVersionId || t('common.noValue') }}</span>
                </div>
              </template>
              <template v-else>
                <strong>{{ t('modelOps.baseModelEmptyTitle') }}</strong>
                <span>{{ t('modelOps.baseModelEmptyDescription') }}</span>
              </template>
            </div>
          </div>
          <label class="field">
            <span>model_type</span>
            <input v-model="conversionModelType" placeholder="yolox / yolov8 / yolo11 / yolo26 / rfdetr" required />
          </label>
          <label class="field field--wide">
            <span>{{ t('modelOps.fields.sourceModelVersionId') }}</span>
            <input v-model="conversionSourceModelVersionId" required />
          </label>
          <label class="field">
            <span>{{ t('modelOps.fields.targetFormat') }}</span>
            <SelectField :model-value="conversionTarget" :options="conversionTargetOptions" @update:model-value="setConversionTarget" />
          </label>
          <label class="field">
            <span>{{ t('modelOps.fields.conversionRuntimeProfileId') }}</span>
            <input v-model="conversionRuntimeProfileId" />
          </label>
          <label class="field field--wide">
            <span>{{ t('modelOps.fields.conversionDisplayName') }}</span>
            <input v-model="conversionDisplayName" />
          </label>
        </div>
        <div class="form-actions">
          <Button variant="primary" type="submit" :disabled="!canWriteTasks || conversionSubmitting || !conversionSourceModelVersionId.trim()">
            <Wand2 :size="16" />
            {{ conversionSubmitting ? t('modelOps.actions.submitting') : t('modelOps.actions.submitConversion') }}
          </Button>
        </div>
        <p v-if="lastConversionSubmission" class="result-note">
          {{ t('modelOps.messages.conversionSubmitted') }}
          <RouterLink :to="`/tasks/${lastConversionSubmission.task_id}`">{{ lastConversionSubmission.task_id }}</RouterLink>
        </p>
      </form>
    </div>

    <section class="resource-section">
      <div>
        <p class="page-kicker">{{ t('modelOps.trainingHistoryKicker') }}</p>
        <h2>{{ t('modelOps.trainingHistoryTitle') }}</h2>
      </div>
      <EmptyState v-if="!loading && trainingTasks.length === 0" :title="t('modelOps.emptyTrainingTitle')" :description="t('modelOps.emptyTrainingDescription')" />
      <div v-else class="resource-table">
        <table>
          <thead>
            <tr>
              <th>{{ t('modelOps.columns.task') }}</th>
              <th>{{ t('modelOps.columns.state') }}</th>
              <th>{{ t('modelOps.columns.progress') }}</th>
              <th>{{ t('modelOps.columns.outputModel') }}</th>
              <th>{{ t('modelOps.columns.modelVersion') }}</th>
              <th>{{ t('modelOps.columns.createdAt') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="task in trainingTasks" :key="task.task_id">
              <td>
                <RouterLink :to="`/models/${selectedTaskType}/training-tasks/${task.task_id}`"><strong>{{ task.display_name || task.task_id }}</strong></RouterLink>
                <span>{{ task.dataset_export_id || task.dataset_export_manifest_key }}</span>
              </td>
              <td><StatusBadge :tone="statusTone(task.state)">{{ task.state }}</StatusBadge></td>
              <td>{{ progressText(task.progress) }}</td>
              <td>{{ task.output_model_name || '-' }}</td>
              <td>{{ task.model_version_id || task.latest_checkpoint_model_version_id || '-' }}</td>
              <td>{{ formatSystemDateTime(task.created_at) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <section class="resource-section">
      <div>
        <p class="page-kicker">{{ t('modelOps.conversionHistoryKicker') }}</p>
        <h2>{{ t('modelOps.conversionHistoryTitle') }}</h2>
      </div>
      <EmptyState v-if="!loading && conversionTasks.length === 0" :title="t('modelOps.emptyConversionTitle')" :description="t('modelOps.emptyConversionDescription')" />
      <div v-else class="resource-table">
        <table>
          <thead>
            <tr>
              <th>{{ t('modelOps.columns.task') }}</th>
              <th>{{ t('modelOps.columns.state') }}</th>
              <th>{{ t('modelOps.columns.sourceVersion') }}</th>
              <th>{{ t('modelOps.columns.targetFormat') }}</th>
              <th>{{ t('modelOps.columns.builds') }}</th>
              <th>{{ t('modelOps.columns.createdAt') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="task in conversionTasks" :key="task.task_id">
              <td>
                <RouterLink :to="`/tasks/${task.task_id}`"><strong>{{ task.display_name || task.task_id }}</strong></RouterLink>
                <span>{{ task.task_id }}</span>
              </td>
              <td><StatusBadge :tone="statusTone(task.state)">{{ task.state }}</StatusBadge></td>
              <td>{{ task.source_model_version_id }}</td>
              <td>{{ (task.produced_formats.length ? task.produced_formats : task.target_formats).join(', ') || '-' }}</td>
              <td>{{ task.builds.map((build) => build.model_build_id).join(', ') || '-' }}</td>
              <td>{{ formatSystemDateTime(task.created_at) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

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
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { Play, RefreshCw, Wand2 } from '@lucide/vue'
import { RouterLink } from 'vue-router'
import { useI18n } from 'vue-i18n'

import {
  listProjectDatasetExports,
  type DatasetExportSummary,
} from '@/modules/datasets/services/dataset.service'
import {
  createModelConversionTask,
  createModelTrainingTask,
  getPlatformBaseModelDetail,
  listPlatformBaseModels,
  listModelConversionTasks,
  listModelTrainingTasks,
  type ConversionTargetKey,
  type PlatformBaseModelDetail,
  type PlatformBaseModelSummary,
  type ModelConversionTaskSummary,
  type ModelTrainingTaskSubmissionResponse,
  type ModelTrainingTaskSummary,
  type ModelConversionTaskSubmissionResponse,
  type ModelTaskType,
} from '../services/model.service'
import {
  buildTrainingExtraOptions,
  getDefaultTrainingEvaluationInterval,
  getDefaultTrainingModelParameterValues,
  getModelLayerTrainingFields,
  supportsTrainingWarmStart,
  type TrainingParameterValues,
  validateTrainingModelLayerValues,
} from '../training-parameter-support'
import { useProjectStore } from '@/app/stores/project.store'
import { useSessionStore } from '@/app/stores/session.store'
import Button from '@/shared/ui/components/Button.vue'
import SelectField from '@/shared/ui/components/Select.vue'
import EmptyState from '@/shared/ui/feedback/EmptyState.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import StatusBadge from '@/shared/ui/data-display/StatusBadge.vue'
import { formatSystemDateTime } from '@/shared/formatters/date-time'
import PlatformBaseModelPickerDialog from '../components/PlatformBaseModelPickerDialog.vue'
import TrainingDatasetExportPickerDialog from '../components/TrainingDatasetExportPickerDialog.vue'

const projectStore = useProjectStore()
const sessionStore = useSessionStore()
const { t } = useI18n()

type SelectValue = string | number | boolean | null

interface PickerVersionListItem {
  model_version_id: string
  source_kind: string
  title: string
  subtitle: string
}

const precisionOptions = [
  { label: 'fp32', value: 'fp32' },
  { label: 'fp16', value: 'fp16' },
]

const DEFAULT_TRAINING_RECIPE_ID = 'default'

const detectionTrainingFormatByModelType: Record<string, string> = {
  yolox: 'coco-detection-v1',
  rfdetr: 'coco-detection-v1',
  yolov8: 'yolo-detection-v1',
  yolo11: 'yolo-detection-v1',
  yolo26: 'yolo-detection-v1',
}

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
const selectedModelDetail = ref<PlatformBaseModelDetail | null>(null)
const trainingTasks = ref<ModelTrainingTaskSummary[]>([])
const conversionTasks = ref<ModelConversionTaskSummary[]>([])
const trainingDatasetExports = ref<DatasetExportSummary[]>([])
const loading = ref(false)
const trainingSubmitting = ref(false)
const conversionSubmitting = ref(false)
const errorMessage = ref<string | null>(null)
const lastTrainingSubmission = ref<ModelTrainingTaskSubmissionResponse | null>(null)
const lastConversionSubmission = ref<ModelConversionTaskSubmissionResponse | null>(null)

const selectedTaskType = ref<ModelTaskType>('detection')
const baseModelPickerOpen = ref(false)
const baseModelPickerMode = ref<'training' | 'conversion'>('training')
const trainingDatasetExportPickerOpen = ref(false)
const trainingDatasetExportSearch = ref('')
const trainingDatasetExportBrowseId = ref('')
const trainingSelectedModelId = ref('')
const conversionSelectedModelId = ref('')
const conversionModelType = ref('')
const trainingDatasetExportId = ref('')
const outputModelName = ref('')
const lastSuggestedOutputModelName = ref('')
const warmStartModelVersionId = ref('')
const maxEpochs = ref(100)
const batchSize = ref(1)
const gpuCount = ref(1)
const evaluationInterval = ref(5)
const precision = ref('fp32')
const inputWidth = ref(640)
const inputHeight = ref(640)
const trainingDisplayName = ref('')
const trainingModelParameterValues = reactive<TrainingParameterValues>({})

const conversionSourceModelVersionId = ref('')
const conversionTarget = ref<ConversionTargetKey>('onnx')
const conversionRuntimeProfileId = ref('')
const conversionDisplayName = ref('')

const canWriteTasks = computed(() => sessionStore.hasScopes(['tasks:write']))
const selectedProjectId = computed(() => projectStore.selectedProjectId)
const selectedTrainingDatasetExport = computed(
  () => trainingDatasetExports.value.find((item) => item.dataset_export_id === trainingDatasetExportId.value) ?? null,
)
const trainingSelectedModelSummary = computed(
  () => baseModels.value.find((model) => model.model_id === trainingSelectedModelId.value) ?? null,
)
const conversionSelectedModelSummary = computed(
  () => baseModels.value.find((model) => model.model_id === conversionSelectedModelId.value) ?? null,
)
const resolvedTrainingManifestKey = computed(
  () => selectedTrainingDatasetExport.value?.manifest_object_key?.trim() ?? '',
)
const resolvedTrainingModelType = computed(
  () => trainingSelectedModelSummary.value?.model_type?.trim() ?? '',
)
const resolvedTrainingModelScale = computed(
  () => trainingSelectedModelSummary.value?.model_scale?.trim() ?? '',
)
const trainingTaskSupportsWarmStart = computed(
  () => supportsTrainingWarmStart(selectedTaskType.value),
)
const trainingSupportsGpuCount = computed(() => selectedTaskType.value === 'detection')
const trainingModelParameterFields = computed(
  () => getModelLayerTrainingFields(selectedTaskType.value, resolvedTrainingModelType.value),
)
const trainingModelParameterSectionTitle = computed(() => {
  if (!resolvedTrainingModelType.value) {
    return '高级参数'
  }
  return `${selectedTaskType.value} / ${resolvedTrainingModelType.value} 高级参数`
})
const selectedModelDerivedTrainingVersions = computed<PickerVersionListItem[]>(() => {
  const selectedModel = selectedModelDetail.value
  if (selectedModel === null) {
    return []
  }

  const selectedModelType = selectedModel.model_type.trim().toLowerCase()
  const selectedModelScale = selectedModel.model_scale.trim().toLowerCase()
  const baseVersionIds = new Set(
    (selectedModel.versions ?? selectedModel.available_versions ?? []).map((version) => version.model_version_id),
  )
  const matchedVersions: PickerVersionListItem[] = []
  const seenVersionIds = new Set<string>()

  for (const task of trainingTasks.value) {
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

function selectValueToString(value: SelectValue): string {
  return typeof value === 'string' ? value : String(value ?? '')
}

function normalizeText(value: string | null | undefined): string {
  return String(value ?? '').trim().toLowerCase()
}

function normalizeModelNameSegment(value: string | null | undefined): string {
  return String(value ?? '')
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/-+/g, '-')
    .replace(/^-|-$/g, '')
}

function buildModelNameTimestamp(date = new Date()): string {
  const pad = (value: number) => String(value).padStart(2, '0')
  return [
    date.getFullYear(),
    pad(date.getMonth() + 1),
    pad(date.getDate()),
    pad(date.getHours()),
    pad(date.getMinutes()),
    pad(date.getSeconds()),
  ].join('')
}

function buildSuggestedOutputModelName(model: Pick<PlatformBaseModelDetail, 'model_name' | 'model_type' | 'model_scale'>): string {
  const modelName = normalizeModelNameSegment(model.model_name || model.model_type) || 'model'
  const modelScale = normalizeModelNameSegment(model.model_scale) || 'default'
  return `${modelName}-${modelScale}-${buildModelNameTimestamp()}`
}

function syncSuggestedOutputModelName(model: Pick<PlatformBaseModelDetail, 'model_name' | 'model_type' | 'model_scale'>): void {
  const currentValue = outputModelName.value.trim()
  if (currentValue && currentValue !== lastSuggestedOutputModelName.value) {
    return
  }
  const nextValue = buildSuggestedOutputModelName(model)
  outputModelName.value = nextValue
  lastSuggestedOutputModelName.value = nextValue
}

function resolveExpectedTrainingExportFormat(taskType: ModelTaskType, modelTypeValue: string): string | null {
  if (taskType !== 'detection') {
    return null
  }
  return detectionTrainingFormatByModelType[normalizeText(modelTypeValue)] ?? null
}

function setPrecision(value: SelectValue): void {
  precision.value = selectValueToString(value) === 'fp16' ? 'fp16' : 'fp32'
}

function setTaskType(value: SelectValue): void {
  const nextValue = selectValueToString(value)
  if (taskTypeOptions.value.some((option) => option.value === nextValue)) {
    const nextTaskType = nextValue as ModelTaskType
    selectedTaskType.value = nextTaskType
    selectedModelDetail.value = null
    trainingDatasetExportPickerOpen.value = false
    trainingSelectedModelId.value = ''
    conversionSelectedModelId.value = ''
    conversionModelType.value = ''
    trainingDatasetExportId.value = ''
    trainingDatasetExportBrowseId.value = ''
    outputModelName.value = ''
    lastSuggestedOutputModelName.value = ''
    warmStartModelVersionId.value = ''
    conversionSourceModelVersionId.value = ''
    void refreshPage()
  }
}

function setConversionTarget(value: SelectValue): void {
  const nextValue = selectValueToString(value)
  conversionTarget.value = (nextValue || 'onnx') as ConversionTargetKey
}

function setTrainingModelParameterValue(key: string, value: SelectValue): void {
  trainingModelParameterValues[key] = selectValueToString(value)
}

watch(
  [selectedTaskType, resolvedTrainingModelType],
  ([taskType, modelType]) => {
    const defaultValues = getDefaultTrainingModelParameterValues(taskType, modelType)
    const visibleKeys = new Set(Object.keys(defaultValues))
    for (const key of Object.keys(trainingModelParameterValues)) {
      if (!visibleKeys.has(key)) {
        delete trainingModelParameterValues[key]
      }
    }
    for (const [key, value] of Object.entries(defaultValues)) {
      trainingModelParameterValues[key] = value
    }
    evaluationInterval.value = getDefaultTrainingEvaluationInterval(taskType, modelType)
    if (taskType !== 'detection') {
      gpuCount.value = 1
      warmStartModelVersionId.value = ''
    }
  },
  { immediate: true },
)

onMounted(async () => {
  if (projectStore.projects.length === 0) {
    await projectStore.loadProjects()
  }
  await refreshPage()
})

function statusTone(status: string | null | undefined): 'neutral' | 'success' | 'warning' | 'danger' | 'info' {
  const normalized = String(status ?? '').toLowerCase()
  if (normalized.includes('complete') || normalized.includes('success') || normalized.includes('succeed')) return 'success'
  if (normalized.includes('fail') || normalized.includes('error')) return 'danger'
  if (normalized.includes('queue') || normalized.includes('pending')) return 'warning'
  if (normalized.includes('run') || normalized.includes('process')) return 'info'
  return 'neutral'
}

function progressText(progress: Record<string, unknown>): string {
  const value = progress.percent ?? progress.progress_percent ?? progress.progress
  return typeof value === 'number' && Number.isFinite(value) ? `${Math.round(value)}%` : '-'
}

async function refreshPage(): Promise<void> {
  loading.value = true
  errorMessage.value = null
  try {
    const [models, training, conversion, datasetExports] = await Promise.all([
      listPlatformBaseModels(selectedTaskType.value),
      listModelTrainingTasks(selectedTaskType.value, selectedProjectId.value),
      listModelConversionTasks(selectedTaskType.value, selectedProjectId.value),
      selectedProjectId.value
        ? listProjectDatasetExports(selectedProjectId.value, selectedTaskType.value, 'completed')
        : Promise.resolve<DatasetExportSummary[]>([]),
    ])
    baseModels.value = models
    trainingTasks.value = training
    conversionTasks.value = conversion
    trainingDatasetExports.value = datasetExports
    const selectedModelId = selectedModelDetail.value?.model_id ?? null
    const selectedModelStillVisible = selectedModelId !== null && models.some((model) => model.model_id === selectedModelId)
    if (!selectedModelStillVisible) {
      selectedModelDetail.value = null
    }
    if (!datasetExports.some((item) => item.dataset_export_id === trainingDatasetExportId.value)) {
      trainingDatasetExportId.value = ''
    }
    if (!datasetExports.some((item) => item.dataset_export_id === trainingDatasetExportBrowseId.value)) {
      trainingDatasetExportBrowseId.value = datasetExports[0]?.dataset_export_id ?? ''
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : t('modelOps.messages.loadFailed')
  } finally {
    loading.value = false
  }
}

async function selectBaseModel(modelId: string): Promise<void> {
  try {
    const detail = await getPlatformBaseModelDetail(modelId)
    selectedModelDetail.value = detail
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : t('modelOps.messages.detailFailed')
  }
}

async function openBaseModelPicker(mode: 'training' | 'conversion'): Promise<void> {
  baseModelPickerMode.value = mode
  baseModelPickerOpen.value = true
  if (baseModels.value.length === 0) {
    return
  }
  const preferredModelId = mode === 'training'
    ? trainingSelectedModelId.value || selectedModelDetail.value?.model_id || baseModels.value[0].model_id
    : conversionSelectedModelId.value || selectedModelDetail.value?.model_id || baseModels.value[0].model_id
  if (preferredModelId && selectedModelDetail.value?.model_id !== preferredModelId) {
    await selectBaseModel(preferredModelId)
  }
}

function closeBaseModelPicker(): void {
  baseModelPickerOpen.value = false
}

function openTrainingDatasetExportPicker(): void {
  if (trainingDatasetExports.value.length === 0) {
    return
  }
  trainingDatasetExportPickerOpen.value = true
  trainingDatasetExportSearch.value = ''
  trainingDatasetExportBrowseId.value =
    trainingDatasetExportId.value || trainingDatasetExports.value[0]?.dataset_export_id || ''
}

function closeTrainingDatasetExportPicker(): void {
  trainingDatasetExportPickerOpen.value = false
  trainingDatasetExportSearch.value = ''
}

function selectTrainingDatasetExportBrowse(datasetExportId: string): void {
  trainingDatasetExportBrowseId.value = datasetExportId.trim()
}

function applyTrainingDatasetExport(datasetExport: DatasetExportSummary): void {
  trainingDatasetExportId.value = datasetExport.dataset_export_id
  trainingDatasetExportBrowseId.value = datasetExport.dataset_export_id
  closeTrainingDatasetExportPicker()
}

function applyTrainingModel(model: PlatformBaseModelDetail): void {
  trainingSelectedModelId.value = model.model_id
  warmStartModelVersionId.value = ''
  syncSuggestedOutputModelName(model)
  closeBaseModelPicker()
}

function applyTrainingVersion(payload: {
  model: PlatformBaseModelDetail
  modelVersionId: string
}): void {
  trainingSelectedModelId.value = payload.model.model_id
  warmStartModelVersionId.value = payload.modelVersionId
  syncSuggestedOutputModelName(payload.model)
  closeBaseModelPicker()
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
  closeBaseModelPicker()
}

function validateTrainingSelection(): string | null {
  if (trainingSelectedModelSummary.value === null || !resolvedTrainingModelType.value || !resolvedTrainingModelScale.value) {
    return t('modelOps.messages.selectTrainingBaseModel')
  }

  const datasetExport = selectedTrainingDatasetExport.value
  if (datasetExport === null) {
    return t('modelOps.messages.selectTrainingDatasetExport')
  }
  if (normalizeText(datasetExport.status) !== 'completed') {
    return t('modelOps.messages.trainingExportIncomplete')
  }
  if (normalizeText(datasetExport.task_type) !== normalizeText(selectedTaskType.value)) {
    return t('modelOps.messages.trainingExportTaskMismatch')
  }
  if (!resolvedTrainingManifestKey.value) {
    return t('modelOps.messages.trainingExportManifestMissing')
  }

  const expectedFormatId = resolveExpectedTrainingExportFormat(selectedTaskType.value, resolvedTrainingModelType.value)
  if (expectedFormatId !== null && normalizeText(datasetExport.format_id) !== normalizeText(expectedFormatId)) {
    return t('modelOps.messages.trainingExportFormatMismatch', {
      modelType: resolvedTrainingModelType.value,
      formatId: expectedFormatId,
    })
  }

  return null
}

async function submitTraining(): Promise<void> {
  const validationError = validateTrainingSelection()
  if (validationError) {
    errorMessage.value = validationError
    return
  }
  const parameterError = validateTrainingModelLayerValues(
    selectedTaskType.value,
    resolvedTrainingModelType.value,
    trainingModelParameterValues,
  )
  if (parameterError) {
    errorMessage.value = parameterError
    return
  }
  trainingSubmitting.value = true
  errorMessage.value = null
  try {
    lastTrainingSubmission.value = await createModelTrainingTask({
      taskType: selectedTaskType.value,
      projectId: selectedProjectId.value,
      modelType: resolvedTrainingModelType.value,
      datasetExportId: trainingDatasetExportId.value.trim(),
      datasetExportManifestKey: resolvedTrainingManifestKey.value,
      recipeId: DEFAULT_TRAINING_RECIPE_ID,
      modelScale: resolvedTrainingModelScale.value,
      outputModelName: outputModelName.value.trim(),
      warmStartModelVersionId: trainingTaskSupportsWarmStart.value ? warmStartModelVersionId.value.trim() : '',
      evaluationInterval: evaluationInterval.value,
      maxEpochs: maxEpochs.value,
      batchSize: batchSize.value,
      gpuCount: trainingSupportsGpuCount.value ? gpuCount.value : undefined,
      precision: precision.value,
      inputWidth: inputWidth.value,
      inputHeight: inputHeight.value,
      displayName: trainingDisplayName.value.trim(),
      extraOptions: buildTrainingExtraOptions(
        selectedTaskType.value,
        resolvedTrainingModelType.value,
        trainingModelParameterValues,
      ),
    })
    trainingTasks.value = await listModelTrainingTasks(selectedTaskType.value, selectedProjectId.value)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : t('modelOps.messages.submitTrainingFailed')
  } finally {
    trainingSubmitting.value = false
  }
}

async function submitConversion(): Promise<void> {
  if (!conversionModelType.value.trim()) {
    errorMessage.value = 'model_type 不能为空'
    return
  }
  conversionSubmitting.value = true
  errorMessage.value = null
  try {
    lastConversionSubmission.value = await createModelConversionTask({
      taskType: selectedTaskType.value,
      projectId: selectedProjectId.value,
      modelType: conversionModelType.value.trim(),
      sourceModelVersionId: conversionSourceModelVersionId.value.trim(),
      target: conversionTarget.value,
      runtimeProfileId: conversionRuntimeProfileId.value.trim(),
      displayName: conversionDisplayName.value,
    })
    conversionTasks.value = await listModelConversionTasks(selectedTaskType.value, selectedProjectId.value)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : t('modelOps.messages.submitConversionFailed')
  } finally {
    conversionSubmitting.value = false
  }
}
</script>

<style scoped>
.model-ops-grid {
  align-items: start;
}

.model-ops-form,
.model-ops-form__grid {
  align-content: start;
}

.training-parameter-section {
  display: grid;
  gap: 14px;
  padding: 14px;
  border: 1px solid var(--line);
  border-radius: 12px;
  background: var(--surface);
}

.training-parameter-section__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.training-parameter-section__header h3 {
  margin: 0;
  font-size: 18px;
}

.training-parameter-section__hint {
  color: var(--muted);
  font-size: 12px;
  font-weight: 600;
}

.training-parameter-grid {
  align-content: start;
}

.training-inline-summary {
  display: grid;
  gap: 8px;
  padding: 12px 14px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--summary-bg);
}

.training-inline-summary.is-empty {
  background: var(--surface);
}

.training-inline-summary strong {
  overflow-wrap: anywhere;
}

.training-inline-summary span {
  color: var(--muted);
  font-size: 12px;
}

.training-inline-summary__actions {
  display: flex;
  justify-content: flex-end;
}

.model-picker-field {
  gap: 10px;
}

.model-picker-field__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.model-picker-field__title > span:first-child {
  color: var(--muted);
  font-weight: 600;
}

.model-picker-field__title {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.model-picker-summary {
  display: grid;
  gap: 12px;
  padding: 14px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--summary-bg);
}

.model-picker-summary.is-empty {
  min-height: 120px;
  align-content: center;
}

.model-picker-summary__top {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.model-picker-summary__identity {
  display: grid;
  gap: 4px;
  min-width: 0;
}

.model-picker-summary__identity strong,
.model-picker-summary__identity span,
.model-picker-summary.is-empty strong,
.model-picker-summary.is-empty span {
  overflow-wrap: anywhere;
}

.model-picker-summary__identity span,
.model-picker-summary.is-empty span,
.model-picker-summary__footer {
  color: var(--muted);
  font-size: 12px;
}

.model-picker-summary__grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.model-picker-summary__item {
  display: grid;
  gap: 4px;
  min-width: 0;
  padding: 10px 12px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--surface);
}

.model-picker-summary__item span {
  color: var(--muted);
  font-size: 12px;
  font-weight: 600;
}

.model-picker-summary__item strong {
  overflow-wrap: anywhere;
}

.model-picker-summary__chips {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.model-picker-chip {
  display: inline-flex;
  align-items: center;
  min-height: 26px;
  padding: 0 10px;
  border-radius: 999px;
  color: var(--badge-neutral-text);
  background: var(--badge-neutral-bg);
  font-size: 12px;
  font-weight: 700;
}

@media (max-width: 900px) {
  .training-parameter-section__header {
    flex-direction: column;
    align-items: flex-start;
  }

  .model-picker-field__header {
    justify-content: flex-start;
  }

  .model-picker-summary__top {
    flex-direction: column;
  }

  .model-picker-summary__grid {
    grid-template-columns: 1fr;
  }
}
</style>
