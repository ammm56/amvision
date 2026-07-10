<template>
  <form class="form-panel model-ops-form" @submit.prevent="$emit('submit')">
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
          <Button
            size="sm"
            variant="secondary"
            type="button"
            :disabled="loading || baseModelsCount === 0"
            @click="$emit('open-base-model-picker')"
          >
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
                <span class="model-picker-chip">
                  {{ t('modelOps.columns.scale') }} · {{ conversionSelectedModelSummary.model_scale }}
                </span>
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
        <input
          :value="conversionModelType"
          placeholder="yolox / yolov8 / yolo11 / yolo26 / rfdetr"
          :readonly="Boolean(conversionSelectedModelSummary)"
          :aria-readonly="Boolean(conversionSelectedModelSummary)"
          required
          @input="emitString('update:conversionModelType', $event)"
        />
      </label>
      <label class="field field--wide">
        <span>{{ t('modelOps.fields.sourceModelVersionId') }}</span>
        <input
          :value="conversionSourceModelVersionId"
          :readonly="Boolean(conversionSelectedModelSummary)"
          :aria-readonly="Boolean(conversionSelectedModelSummary)"
          required
          @input="emitString('update:conversionSourceModelVersionId', $event)"
        />
      </label>
      <label class="field">
        <span>{{ t('modelOps.fields.targetFormat') }}</span>
        <SelectField
          :model-value="conversionTarget"
          :options="conversionTargetOptions"
          @update:model-value="$emit('update:conversionTarget', normalizeSelectValue($event) || 'onnx')"
        />
      </label>
      <label class="field">
        <span>{{ t('modelOps.fields.conversionRuntimeProfileId') }}</span>
        <input :value="conversionRuntimeProfileId" @input="emitString('update:conversionRuntimeProfileId', $event)" />
      </label>
      <label class="field field--wide">
        <span>{{ t('modelOps.fields.conversionDisplayName') }}</span>
        <input :value="conversionDisplayName" @input="emitString('update:conversionDisplayName', $event)" />
      </label>
    </div>
    <div class="form-actions">
      <Button
        variant="primary"
        type="submit"
        :disabled="!canWriteTasks || conversionSubmitting || !conversionSelectedModelSummary || !conversionSourceModelVersionId.trim()"
      >
        <Wand2 :size="16" />
        {{ conversionSubmitting ? t('modelOps.actions.submitting') : t('modelOps.actions.submitConversion') }}
      </Button>
    </div>
    <p v-if="lastConversionSubmission" class="result-note">
      {{ t('modelOps.messages.conversionSubmitted') }}
      <RouterLink :to="`/tasks/${lastConversionSubmission.task_id}`">{{ lastConversionSubmission.task_id }}</RouterLink>
    </p>
  </form>
</template>

<script setup lang="ts">
import { Wand2 } from '@lucide/vue'
import { RouterLink } from 'vue-router'
import { useI18n } from 'vue-i18n'

import type {
  ConversionTargetKey,
  ModelConversionTaskSubmissionResponse,
  ModelTaskType,
  PlatformBaseModelSummary,
} from '../services/model.service'
import Button from '@/shared/ui/components/Button.vue'
import SelectField from '@/shared/ui/components/Select.vue'

type SelectValue = string | number | boolean | null
type UpdateStringEvent =
  | 'update:conversionModelType'
  | 'update:conversionSourceModelVersionId'
  | 'update:conversionRuntimeProfileId'
  | 'update:conversionDisplayName'

defineProps<{
  selectedTaskType: ModelTaskType
  loading: boolean
  baseModelsCount: number
  conversionSelectedModelSummary: PlatformBaseModelSummary | null
  conversionModelType: string
  conversionSourceModelVersionId: string
  conversionTarget: ConversionTargetKey
  conversionTargetOptions: Array<{ label: string; value: string }>
  conversionRuntimeProfileId: string
  conversionDisplayName: string
  canWriteTasks: boolean
  conversionSubmitting: boolean
  lastConversionSubmission: ModelConversionTaskSubmissionResponse | null
}>()

const emit = defineEmits<{
  submit: []
  'open-base-model-picker': []
  'update:conversionModelType': [value: string]
  'update:conversionSourceModelVersionId': [value: string]
  'update:conversionTarget': [value: string]
  'update:conversionRuntimeProfileId': [value: string]
  'update:conversionDisplayName': [value: string]
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
  if (eventName === 'update:conversionModelType') {
    emit('update:conversionModelType', value)
    return
  }
  if (eventName === 'update:conversionSourceModelVersionId') {
    emit('update:conversionSourceModelVersionId', value)
    return
  }
  if (eventName === 'update:conversionRuntimeProfileId') {
    emit('update:conversionRuntimeProfileId', value)
    return
  }
  emit('update:conversionDisplayName', value)
}
</script>

<style scoped>
.model-ops-form,
.model-ops-form__grid {
  align-content: start;
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
  .model-picker-field__header {
    justify-content: flex-start;
  }

  .model-picker-summary__top {
    flex-direction: column;
  }
}
</style>
