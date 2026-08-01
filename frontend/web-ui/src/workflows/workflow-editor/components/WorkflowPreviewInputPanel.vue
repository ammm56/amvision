<template>
  <div class="workflow-graph-preview-inputs">
    <div class="workflow-graph-panel__header">
      <h2>{{ t('workflowEditor.editor.previewInputs') }}</h2>
      <StatusBadge v-if="blockingMessages.length" tone="danger">
        {{ t('workflowEditor.editor.missingInputs') }}
      </StatusBadge>
    </div>
    <div v-if="blockingMessages.length" class="workflow-graph-preview-errors" role="alert">
      <p>{{ blockingMessages[0] }}</p>
    </div>
    <section v-for="binding in bindings" :key="binding.binding_id" class="workflow-graph-preview-binding">
      <div class="workflow-graph-preview-binding__header">
        <span class="workflow-graph-preview-binding__summary">
          <strong>{{ binding.binding_id }}</strong>
          <small>{{ getPayloadTypeId(binding) || 'unknown' }}</small>
        </span>
        <div class="workflow-graph-preview-binding__tools">
          <StatusBadge :tone="binding.required ? 'warning' : 'neutral'">
            {{ binding.required ? t('workflowEditor.editor.required') : t('workflowEditor.editor.optional') }}
          </StatusBadge>
        </div>
      </div>
      <template v-if="states[binding.binding_id] && getPayloadTypeId(binding) === 'value.v1'">
        <div class="workflow-graph-value-fields">
          <label v-for="field in states[binding.binding_id].valueFields" :key="field.id" class="workflow-graph-value-field">
            <input v-model="field.key" :placeholder="t('workflowEditor.editor.fieldName')" />
            <input v-model="field.value" :placeholder="t('workflowEditor.editor.fieldValue')" />
            <button type="button" :title="t('workflowEditor.editor.deleteField')" @click="emit('remove-value-field', binding.binding_id, field.id)">
              <Trash2 :size="14" />
            </button>
          </label>
        </div>
        <Button size="sm" variant="secondary" type="button" @click="emit('add-value-field', binding.binding_id)">
          <Plus :size="14" />
          {{ t('workflowEditor.editor.addField') }}
        </Button>
      </template>
      <template v-else-if="states[binding.binding_id] && getPayloadTypeId(binding) === 'image-base64.v1'">
        <FilePicker
          v-model="states[binding.binding_id].file"
          icon="image"
          accept="image/*"
          :label="t('workflowEditor.editor.imageFile')"
        />
        <label class="workflow-graph-preview-field">
          <span>media_type</span>
          <input v-model="states[binding.binding_id].mediaType" :placeholder="t('workflowEditor.editor.autoFileType')" />
        </label>
      </template>
      <template v-else-if="states[binding.binding_id] && getPayloadTypeId(binding) === 'image-ref.v1'">
        <label class="workflow-graph-preview-field">
          <span>{{ t('workflowEditor.editor.referenceSource') }}</span>
          <SelectField
            :model-value="states[binding.binding_id].imageRefTransportKind"
            :options="imageRefTransportKindOptions"
            @update:model-value="emit('set-image-ref-transport-kind', binding.binding_id, $event)"
          />
        </label>
        <label v-if="states[binding.binding_id].imageRefTransportKind === 'storage'" class="workflow-graph-preview-field">
          <span>object_key</span>
          <input v-model="states[binding.binding_id].objectKey" placeholder="project/files/image.jpg" />
        </label>
        <label v-else class="workflow-graph-preview-field">
          <span>image_handle</span>
          <input v-model="states[binding.binding_id].imageHandle" placeholder="execution-scoped image handle" />
        </label>
        <label class="workflow-graph-preview-field">
          <span>media_type</span>
          <input v-model="states[binding.binding_id].mediaType" placeholder="image/jpeg" />
        </label>
      </template>
      <template v-else-if="states[binding.binding_id]">
        <label class="workflow-graph-preview-field">
          <span>{{ t('workflowEditor.editor.inputValue') }}</span>
          <input v-model="states[binding.binding_id].plainValue" :placeholder="t('workflowEditor.editor.submitAsString')" />
        </label>
      </template>
    </section>
  </div>
</template>

<script setup lang="ts">
import { Plus, Trash2 } from '@lucide/vue'
import { useI18n } from 'vue-i18n'

import Button from '@/shared/ui/components/Button.vue'
import FilePicker from '@/shared/ui/components/FilePicker.vue'
import SelectField from '@/shared/ui/components/Select.vue'
import StatusBadge from '@/shared/ui/data-display/StatusBadge.vue'
import type { FlowApplicationBinding } from '../types'
import type { PreviewInputState, PreviewSelectOption, PreviewSelectValue } from '../preview/useWorkflowPreviewInputs'

defineProps<{
  bindings: FlowApplicationBinding[]
  states: Record<string, PreviewInputState>
  blockingMessages: string[]
  imageRefTransportKindOptions: PreviewSelectOption[]
  getPayloadTypeId: (binding: FlowApplicationBinding) => string
}>()

const emit = defineEmits<{
  'add-value-field': [bindingId: string]
  'remove-value-field': [bindingId: string, fieldId: string]
  'set-image-ref-transport-kind': [bindingId: string, value: PreviewSelectValue]
}>()

const { t } = useI18n()
</script>
