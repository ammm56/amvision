<template>
  <form class="form-panel" @submit.prevent="$emit('submit')">
    <div>
      <h2>{{ t('datasetOps.importTitle') }}</h2>
    </div>
    <div class="form-grid">
      <label class="field">
        <span>{{ t('datasetOps.fields.projectId') }}</span>
        <input :value="selectedProjectId" disabled />
      </label>
      <label class="field">
        <span>{{ t('datasetOps.fields.datasetId') }}</span>
        <input :value="datasetId" required @input="$emit('update:datasetId', ($event.target as HTMLInputElement).value)" />
      </label>
      <label class="field">
        <span>{{ t('datasetOps.fields.formatType') }}</span>
        <SelectField :model-value="formatType" :options="formatTypeOptions" @update:model-value="$emit('update:formatType', $event)" />
      </label>
      <label class="field">
        <span>{{ t('datasetOps.fields.taskType') }}</span>
        <SelectField :model-value="taskType" :options="taskTypeOptions" @update:model-value="$emit('update:taskType', $event)" />
      </label>
      <label class="field">
        <span>{{ t('datasetOps.fields.splitStrategy') }}</span>
        <SelectField :model-value="splitStrategy" :options="splitStrategyOptions" @update:model-value="$emit('update:splitStrategy', $event)" />
      </label>
      <FilePicker
        v-model="importFileModel"
        class="field--wide"
        icon="archive"
        accept=".zip,application/zip"
        :label="t('datasetOps.fields.package')"
        :description="t('datasetOps.filePickerDescription')"
        :disabled="submittingImport"
      />
      <label class="field field--wide">
        <span>{{ t('datasetOps.fields.classMap') }}</span>
        <textarea
          :value="classMapJson"
          rows="3"
          placeholder='{"old": "new"}'
          @input="$emit('update:classMapJson', ($event.target as HTMLTextAreaElement).value)"
        />
      </label>
    </div>
    <div class="form-actions">
      <Button variant="primary" type="submit" :disabled="!canWriteDatasets || submittingImport">
        <UploadCloud :size="16" />
        {{ submittingImport ? t('datasetOps.actions.submitting') : t('datasetOps.actions.submitImport') }}
      </Button>
    </div>
    <p v-if="lastImportSubmission" class="result-note">
      {{ t('datasetOps.messages.importSubmitted') }}
      <RouterLink v-if="lastImportSubmission.task_id" :to="`/tasks/${lastImportSubmission.task_id}`">
        {{ lastImportSubmission.task_id }}
      </RouterLink>
      <span v-else>{{ lastImportSubmission.dataset_import_id }}</span>
    </p>
  </form>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { UploadCloud } from '@lucide/vue'
import { RouterLink } from 'vue-router'
import { useI18n } from 'vue-i18n'

import type { DatasetImportSubmissionResponse } from '../services/dataset.service'
import type { DatasetSelectOption, DatasetSelectValue } from '../composables/useDatasetFormatCapabilities'
import Button from '@/shared/ui/components/Button.vue'
import FilePicker from '@/shared/ui/components/FilePicker.vue'
import SelectField from '@/shared/ui/components/Select.vue'

const props = defineProps<{
  selectedProjectId: string
  datasetId: string
  formatType: string
  taskType: string
  splitStrategy: string
  classMapJson: string
  importFile: File | null
  formatTypeOptions: DatasetSelectOption[]
  taskTypeOptions: DatasetSelectOption[]
  splitStrategyOptions: DatasetSelectOption[]
  canWriteDatasets: boolean
  submittingImport: boolean
  lastImportSubmission: DatasetImportSubmissionResponse | null
}>()

const emit = defineEmits<{
  submit: []
  'update:datasetId': [value: string]
  'update:formatType': [value: DatasetSelectValue]
  'update:taskType': [value: DatasetSelectValue]
  'update:splitStrategy': [value: DatasetSelectValue]
  'update:classMapJson': [value: string]
  'update:importFile': [value: File | null]
}>()

const { t } = useI18n()
const importFileModel = computed({
  get: () => props.importFile,
  set: (value: File | null) => emit('update:importFile', value),
})
</script>
