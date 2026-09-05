<template>
  <form class="app-mode-inputs" @submit.prevent="emit('run')">
    <header>
      <div>
        <h2>{{ t('workflowEditor.appMode.inputs') }}</h2>
        <small>{{ t('workflowEditor.appMode.emptyInputsOmitted') }}</small>
      </div>
      <Button type="submit" variant="primary" :loading="running" :disabled="disabled">
        <Play :size="16" />
        {{ t('workflowEditor.appMode.run') }}
      </Button>
    </header>

    <p v-if="inputs.length === 0" class="app-mode-inputs__empty">{{ t('workflowEditor.appMode.noInputs') }}</p>
    <div v-for="input in inputs" :key="input.binding_id" class="app-mode-inputs__field">
      <div class="app-mode-inputs__label">
        <strong>{{ input.binding_id }}</strong>
        <small>{{ input.payload_type_id }}</small>
      </div>

      <template v-if="states[input.binding_id]">
        <template v-if="input.payload_type_id === 'image-ref.v1'">
          <Select
            v-if="input.transports.includes('multipart-upload') && input.transports.includes('json-reference')"
            v-model="states[input.binding_id].imageRefTransport"
            :options="imageRefOptions"
            fit-options
          />
          <FilePicker
            v-if="states[input.binding_id].imageRefTransport === 'upload'"
            v-model="states[input.binding_id].file"
            :label="input.binding_id"
            :accept="accept(input)"
            icon="image"
          />
          <textarea
            v-else
            v-model="states[input.binding_id].json"
            rows="5"
            :placeholder="t('workflowEditor.appMode.imageReferencePlaceholder')"
          />
        </template>
        <FilePicker
          v-else-if="input.payload_type_id === 'image-base64.v1'"
          v-model="states[input.binding_id].file"
          :label="input.binding_id"
          :accept="accept(input) || 'image/*'"
          icon="image"
        />
        <FilePicker
          v-else-if="input.payload_type_id === 'file-ref.v1'"
          v-model="states[input.binding_id].file"
          :label="input.binding_id"
          :accept="accept(input)"
        />
        <FilePicker
          v-else-if="input.payload_type_id === 'file-refs.v1'"
          v-model="states[input.binding_id].files"
          :label="input.binding_id"
          :accept="accept(input)"
          multiple
        />
        <textarea
          v-else-if="input.payload_type_id === 'text.v1'"
          v-model="states[input.binding_id].text"
          rows="3"
          :placeholder="t('workflowEditor.appMode.textPlaceholder')"
        />
        <textarea
          v-else
          v-model="states[input.binding_id].json"
          rows="5"
          :placeholder="t('workflowEditor.appMode.jsonPlaceholder')"
        />
      </template>
    </div>
  </form>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { Play } from '@lucide/vue'
import { useI18n } from 'vue-i18n'

import Button from '@/shared/ui/components/Button.vue'
import FilePicker from '@/shared/ui/components/FilePicker.vue'
import Select from '@/shared/ui/components/Select.vue'
import type { WorkflowAppContractInput } from '../app-mode/workflow-app-mode'
import type { WorkflowAppModeInputState } from '../app-mode/useWorkflowAppModeInputs'

const props = defineProps<{
  inputs: WorkflowAppContractInput[]
  states: Record<string, WorkflowAppModeInputState>
  running: boolean
  disabled: boolean
}>()

const emit = defineEmits<{ run: [] }>()
const { t } = useI18n()
const imageRefOptions = computed(() => [
  { value: 'upload', label: t('workflowEditor.appMode.upload') },
  { value: 'reference', label: t('workflowEditor.appMode.reference') },
])

function accept(input: WorkflowAppContractInput): string {
  return input.allowed_media_types.join(',')
}
</script>

<style scoped>
.app-mode-inputs { display: grid; align-content: start; gap: 14px; min-width: 300px; padding: 18px; border: 1px solid var(--border-color, #d6dfd9); border-radius: 12px; background: var(--surface-primary, #fff); }
.app-mode-inputs > header { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.app-mode-inputs h2 { margin: 0; font-size: 17px; }
.app-mode-inputs header small, .app-mode-inputs__label small { display: block; color: var(--text-secondary, #69776e); }
.app-mode-inputs__empty { margin: 0; color: var(--text-secondary, #69776e); }
.app-mode-inputs__field { display: grid; gap: 7px; }
.app-mode-inputs__label { display: flex; align-items: baseline; justify-content: space-between; gap: 10px; }
.app-mode-inputs textarea { width: 100%; min-height: 74px; resize: vertical; padding: 9px 10px; border: 1px solid var(--border-color, #d6dfd9); border-radius: 8px; background: var(--surface-primary, #fff); color: inherit; font: 12px/1.5 ui-monospace, SFMono-Regular, Consolas, monospace; }
</style>
