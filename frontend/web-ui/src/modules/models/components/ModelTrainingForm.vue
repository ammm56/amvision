<template>
  <form class="form-panel model-ops-form" @submit.prevent="$emit('submit')">
    <div>
      <h2>{{ t('modelOps.trainingTitle') }}</h2>
    </div>
    <div class="form-grid model-ops-form__grid">
      <div class="field field--wide model-picker-field">
        <div class="model-picker-field__header">
          <div class="model-picker-field__title">
            <span>{{ t('modelOps.fields.trainingBaseModel') }}</span>
            <span class="model-picker-chip">{{ selectedTaskType }}</span>
          </div>
          <Button
            size="sm"
            variant="secondary"
            type="button"
            :disabled="loading || baseModelsCount === 0"
            @click="$emit('open-base-model-picker')"
          >
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
                <span class="model-picker-chip">
                  {{ t('modelOps.columns.scale') }} · {{ trainingSelectedModelSummary.model_scale }}
                </span>
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
            :disabled="loading || trainingDatasetExportsCount === 0"
            @click="$emit('open-training-dataset-export-picker')"
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
            <h3>通用参数</h3>
          </div>
        </div>
        <div class="form-grid training-parameter-grid">
          <label class="field">
            <span>{{ t('modelOps.fields.outputModelName') }}</span>
            <input :value="outputModelName" required @input="emitString('update:outputModelName', $event)" />
          </label>
          <label class="field">
            <span>{{ t('modelOps.fields.maxEpochs') }}</span>
            <input :value="maxEpochs" type="number" min="1" @input="emitNumber('update:maxEpochs', $event)" />
          </label>
          <label class="field">
            <span>{{ t('modelOps.fields.batchSize') }}</span>
            <input :value="batchSize" type="number" min="1" @input="emitNumber('update:batchSize', $event)" />
          </label>
          <label class="field">
            <span>{{ t('modelOps.fields.precision') }}</span>
            <SelectField :model-value="precision" :options="precisionOptions" @update:model-value="$emit('update:precision', normalizeSelectValue($event) === 'fp16' ? 'fp16' : 'fp32')" />
          </label>
          <label class="field">
            <span>{{ t('modelOps.fields.inputWidth') }}</span>
            <input :value="inputWidth" type="number" min="32" step="32" @input="emitNumber('update:inputWidth', $event)" />
          </label>
          <label class="field">
            <span>{{ t('modelOps.fields.inputHeight') }}</span>
            <input :value="inputHeight" type="number" min="32" step="32" @input="emitNumber('update:inputHeight', $event)" />
          </label>
          <label class="field">
            <span>{{ t('modelOps.fields.evaluationInterval') }}</span>
            <input :value="evaluationInterval" type="number" min="1" @input="emitNumber('update:evaluationInterval', $event)" />
          </label>
          <label class="field">
            <span>训练设备</span>
            <SelectField
              :model-value="trainingDevice"
              :options="trainingDeviceOptions"
              @update:model-value="$emit('update:trainingDevice', normalizeSelectValue($event))"
            />
          </label>
          <label v-if="trainingSupportsGpuCount" class="field">
            <span>{{ t('modelOps.fields.gpuCount') }}</span>
            <input :value="gpuCount" type="number" min="1" step="1" @input="emitNumber('update:gpuCount', $event)" />
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
                  @click="$emit('clear-training-warm-start')"
                >
                  {{ t('common.filePicker.clear') }}
                </Button>
              </div>
            </div>
          </div>
          <label class="field field--wide">
            <span>{{ t('modelOps.fields.trainingDisplayName') }}</span>
            <input :value="trainingDisplayName" @input="emitString('update:trainingDisplayName', $event)" />
          </label>
        </div>
      </section>

      <section v-if="trainingModelParameterFields.length > 0" class="training-parameter-section field field--wide">
        <div class="training-parameter-section__header">
          <div>
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
              @update:model-value="$emit('update:trainingModelParameterValue', field.key, normalizeSelectValue($event))"
            />
            <input
              v-else
              :value="trainingModelParameterValues[field.key] ?? ''"
              :type="field.inputKind"
              :min="field.min"
              :max="field.max"
              :step="field.step"
              :placeholder="field.placeholder"
              @input="emitModelParameterValue(field.key, $event)"
            />
          </label>
        </div>
      </section>

      <section
        v-if="trainingSupportsAugmentationToggle"
        class="training-parameter-section field field--wide"
      >
        <div class="training-parameter-section__header">
          <div>
            <h3>数据增强参数</h3>
          </div>
          <label class="training-augmentation-switch">
            <input
              type="checkbox"
              :checked="trainingAugmentationEnabled"
              @change="emitBoolean('update:trainingAugmentationEnabled', $event)"
            />
            <span>{{ trainingAugmentationEnabled ? '启用数据增强' : '已关闭数据增强' }}</span>
          </label>
        </div>
        <p class="training-parameter-section__description">
          默认开启。关闭后提交训练时会按当前模型任务关闭对应的数据增强。
        </p>
        <div
          class="form-grid training-parameter-grid"
          :class="{ 'training-parameter-grid--disabled': !trainingAugmentationEnabled }"
        >
          <label
            v-for="field in trainingAugmentationParameterFields"
            :key="field.key"
            class="field"
            :class="{ 'field--wide': field.wide }"
          >
            <span>{{ field.label }}</span>
            <SelectField
              v-if="field.inputKind === 'select'"
              :model-value="trainingModelParameterValues[field.key] ?? ''"
              :options="field.options ?? []"
              :disabled="!trainingAugmentationEnabled"
              @update:model-value="$emit('update:trainingModelParameterValue', field.key, normalizeSelectValue($event))"
            />
            <input
              v-else
              :value="trainingModelParameterValues[field.key] ?? ''"
              :type="field.inputKind"
              :min="field.min"
              :max="field.max"
              :step="field.step"
              :placeholder="field.placeholder"
              :disabled="!trainingAugmentationEnabled"
              @input="emitModelParameterValue(field.key, $event)"
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
</template>

<script setup lang="ts">
import { Play } from '@lucide/vue'
import { RouterLink } from 'vue-router'
import { useI18n } from 'vue-i18n'

import type { DatasetExportSummary } from '@/modules/datasets/services/dataset.service'
import type {
  ModelTaskType,
  ModelTrainingTaskSubmissionResponse,
  PlatformBaseModelSummary,
} from '../services/model.service'
import type {
  TrainingParameterField,
  TrainingParameterFieldOption,
  TrainingParameterValues,
} from '../training-parameter-support'
import { formatSystemDateTime } from '@/shared/formatters/date-time'
import Button from '@/shared/ui/components/Button.vue'
import SelectField from '@/shared/ui/components/Select.vue'

type SelectValue = string | number | boolean | null
type UpdateNumberEvent =
  | 'update:maxEpochs'
  | 'update:batchSize'
  | 'update:gpuCount'
  | 'update:evaluationInterval'
  | 'update:inputWidth'
  | 'update:inputHeight'
type UpdateStringEvent =
  | 'update:outputModelName'
  | 'update:trainingDisplayName'
type UpdateBooleanEvent = 'update:trainingAugmentationEnabled'

defineProps<{
  selectedTaskType: ModelTaskType
  loading: boolean
  baseModelsCount: number
  trainingDatasetExportsCount: number
  trainingSelectedModelSummary: PlatformBaseModelSummary | null
  selectedTrainingDatasetExport: DatasetExportSummary | null
  trainingDeviceOptions: TrainingParameterFieldOption[]
  outputModelName: string
  maxEpochs: number
  batchSize: number
  gpuCount: number
  trainingDevice: string
  evaluationInterval: number
  precision: string
  inputWidth: number
  inputHeight: number
  trainingDisplayName: string
  warmStartModelVersionId: string
  trainingSupportsGpuCount: boolean
  trainingTaskSupportsWarmStart: boolean
  trainingModelParameterFields: TrainingParameterField[]
  trainingAugmentationParameterFields: TrainingParameterField[]
  trainingAugmentationEnabled: boolean
  trainingSupportsAugmentationToggle: boolean
  trainingModelParameterValues: TrainingParameterValues
  trainingModelParameterSectionTitle: string
  precisionOptions: Array<{ label: string; value: string }>
  canWriteTasks: boolean
  trainingSubmitting: boolean
  lastTrainingSubmission: ModelTrainingTaskSubmissionResponse | null
}>()

const emit = defineEmits<{
  submit: []
  'open-base-model-picker': []
  'open-training-dataset-export-picker': []
  'clear-training-warm-start': []
  'update:outputModelName': [value: string]
  'update:maxEpochs': [value: number]
  'update:batchSize': [value: number]
  'update:gpuCount': [value: number]
  'update:trainingDevice': [value: string]
  'update:evaluationInterval': [value: number]
  'update:precision': [value: string]
  'update:inputWidth': [value: number]
  'update:inputHeight': [value: number]
  'update:trainingDisplayName': [value: string]
  'update:trainingModelParameterValue': [key: string, value: string]
  'update:trainingAugmentationEnabled': [value: boolean]
}>()

const { t } = useI18n()

function normalizeSelectValue(value: SelectValue): string {
  return typeof value === 'string' ? value : String(value ?? '')
}

function getInputValue(event: Event): string {
  const input = event.target
  return input instanceof HTMLInputElement ? input.value : ''
}

function emitString(eventName: UpdateStringEvent, event: Event): void {
  const value = getInputValue(event)
  if (eventName === 'update:outputModelName') {
    emit('update:outputModelName', value)
    return
  }
  emit('update:trainingDisplayName', value)
}

function emitNumber(eventName: UpdateNumberEvent, event: Event): void {
  const value = Number(getInputValue(event))
  const normalizedValue = Number.isFinite(value) ? value : 0
  if (eventName === 'update:maxEpochs') {
    emit('update:maxEpochs', normalizedValue)
    return
  }
  if (eventName === 'update:batchSize') {
    emit('update:batchSize', normalizedValue)
    return
  }
  if (eventName === 'update:gpuCount') {
    emit('update:gpuCount', normalizedValue)
    return
  }
  if (eventName === 'update:evaluationInterval') {
    emit('update:evaluationInterval', normalizedValue)
    return
  }
  if (eventName === 'update:inputWidth') {
    emit('update:inputWidth', normalizedValue)
    return
  }
  emit('update:inputHeight', normalizedValue)
}

function emitBoolean(eventName: UpdateBooleanEvent, event: Event): void {
  const input = event.target
  const value = input instanceof HTMLInputElement && input.checked
  emit(eventName, value)
}

function emitModelParameterValue(key: string, event: Event): void {
  emit('update:trainingModelParameterValue', key, getInputValue(event))
}
</script>

<style scoped>
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

.training-parameter-section__description {
  margin: 0;
  color: var(--muted);
  font-size: 13px;
  line-height: 1.6;
}

.training-parameter-grid {
  align-content: start;
}

.training-parameter-grid--disabled {
  opacity: 0.72;
}

.training-augmentation-switch {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-height: 34px;
  padding: 0 12px;
  border: 1px solid var(--line);
  border-radius: 999px;
  background: var(--summary-bg);
  color: var(--text);
  font-size: 13px;
  font-weight: 700;
  cursor: pointer;
}

.training-augmentation-switch input {
  width: 16px;
  height: 16px;
  accent-color: var(--accent);
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
