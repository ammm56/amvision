<template>
  <div class="workflow-graph-inspector-body">
    <div class="workflow-graph-panel__header workflow-graph-panel__header--compact">
      <div>
        <h2>{{ title }}</h2>
      </div>
      <StatusBadge tone="neutral">{{ bindings.length }}</StatusBadge>
    </div>
    <EmptyState
      v-if="bindings.length === 0"
      :title="t('workflowEditor.editor.emptyPublicBindings')"
      :description="t('workflowEditor.editor.emptyPublicBindingsHint')"
    />
    <section
      v-for="binding in bindings"
      :key="`public-binding-editor-${binding.direction}-${binding.binding_id}`"
      class="workflow-graph-public-binding-editor"
    >
      <div class="workflow-graph-public-binding-editor__title">
        <strong>{{ binding.binding_id }}</strong>
      </div>
      <label class="workflow-graph-preview-field">
        <span>{{ t('workflowEditor.editor.publicId') }}</span>
        <input :value="binding.binding_id" @change="emit('update-binding-id', binding, $event)" />
      </label>
      <label class="workflow-graph-preview-field">
        <span>{{ t('workflowEditor.editor.displayName') }}</span>
        <input :value="readDisplayName(binding)" @input="emit('update-display-name', binding, $event)" />
      </label>
      <label class="workflow-graph-preview-field">
        <span>{{ t('workflowEditor.editor.bindingType') }}</span>
        <SelectField
          :model-value="binding.binding_kind"
          :options="readKindOptions(binding)"
          @update:model-value="emit('update-kind', binding, $event)"
        />
      </label>
      <label class="workflow-graph-preview-field">
        <span>{{ t('workflowEditor.editor.payloadType') }}</span>
        <input :value="getPayloadTypeId(binding)" readonly />
      </label>
      <label class="workflow-graph-preview-field">
        <span>{{ t('workflowEditor.editor.formDescription') }}</span>
        <textarea
          :value="readBindingDescription(binding)"
          rows="2"
          @change="emit('update-description', binding, $event)"
        />
      </label>
      <template v-if="binding.direction === 'input'">
        <label v-if="getPayloadTypeId(binding) === 'value.v1'" class="workflow-graph-preview-field">
          <span>{{ t('workflowEditor.editor.requestSchema') }}</span>
          <textarea
            :value="readRequestSchema(binding)"
            rows="6"
            placeholder="{ &quot;type&quot;: &quot;object&quot; }"
            spellcheck="false"
            @change="emit('update-request-schema', binding, $event)"
          />
        </label>
        <label v-if="getPayloadTypeId(binding) === 'text.v1'" class="workflow-graph-preview-field">
          <span>{{ t('workflowEditor.editor.charset') }}</span>
          <input
            :value="readConfigText(binding, 'charset')"
            placeholder="utf-8"
            @change="emit('update-charset', binding, $event)"
          />
        </label>
        <label v-if="showsMediaPolicy(binding)" class="workflow-graph-preview-field">
          <span>{{ t('workflowEditor.editor.allowedMediaTypes') }}</span>
          <input
            :value="readAllowedMediaTypes(binding)"
            placeholder="image/*, application/json"
            @change="emit('update-media-types', binding, $event)"
          />
        </label>
        <label v-if="showsInlineLimit(binding)" class="workflow-graph-preview-field">
          <span>{{ t('workflowEditor.editor.maxInlineBytes') }}</span>
          <input
            type="number"
            min="1"
            step="1"
            :value="readConfigNumber(binding, 'max_inline_bytes')"
            :placeholder="t('workflowEditor.editor.platformDefault')"
            @change="emit('update-positive-limit', binding, 'max_inline_bytes', $event)"
          />
        </label>
        <label v-if="showsFilePolicy(binding)" class="workflow-graph-preview-field">
          <span>{{ t('workflowEditor.editor.maxFileBytes') }}</span>
          <input
            type="number"
            min="1"
            step="1"
            :value="readConfigNumber(binding, 'max_file_bytes')"
            :placeholder="t('workflowEditor.editor.platformDefault')"
            @change="emit('update-positive-limit', binding, 'max_file_bytes', $event)"
          />
        </label>
        <label v-if="getPayloadTypeId(binding) === 'file-refs.v1'" class="workflow-graph-preview-field">
          <span>{{ t('workflowEditor.editor.maxFiles') }}</span>
          <input
            type="number"
            min="1"
            step="1"
            :value="readConfigNumber(binding, 'max_files')"
            :placeholder="t('workflowEditor.editor.platformDefault')"
            @change="emit('update-positive-limit', binding, 'max_files', $event)"
          />
        </label>
        <div class="workflow-graph-preview-field">
          <span>{{ t('workflowEditor.editor.supportedTransports') }}</span>
          <small>{{ readTransportSummary(binding) }}</small>
        </div>
      </template>
      <label v-if="binding.direction === 'input'" class="workflow-graph-public-binding-editor__checkbox">
        <WorkflowGraphCheckbox
          :checked="binding.required"
          :aria-label="t('workflowEditor.editor.requiredInput')"
          @change="emit('update-required', binding, $event)"
        />
        <span>{{ t('workflowEditor.editor.requiredInput') }}</span>
      </label>
      <Button variant="danger" type="button" @click="emit('delete-binding', binding)">
        <Trash2 :size="16" />
        {{ t('workflowEditor.editor.deletePublicBinding') }}
      </Button>
    </section>
  </div>
</template>

<script setup lang="ts">
import { Trash2 } from '@lucide/vue'
import { useTranslation } from '@/platform/i18n'

import Button from '@/shared/ui/components/Button.vue'
import SelectField from '@/shared/ui/components/Select.vue'
import StatusBadge from '@/shared/ui/data-display/StatusBadge.vue'
import EmptyState from '@/shared/ui/feedback/EmptyState.vue'
import type { FlowApplicationBinding } from '../types'
import WorkflowGraphCheckbox from './WorkflowGraphCheckbox.vue'

const { t } = useTranslation()

type SelectValue = string | number | boolean | null

interface SelectOption {
  label: string
  value: SelectValue
  description?: string
}

const props = defineProps<{
  title: string
  bindings: FlowApplicationBinding[]
  readDisplayName: (binding: FlowApplicationBinding) => string
  readKindOptions: (binding: FlowApplicationBinding) => SelectOption[]
  getPayloadTypeId: (binding: FlowApplicationBinding) => string
}>()

const emit = defineEmits<{
  'update-binding-id': [binding: FlowApplicationBinding, event: Event]
  'update-display-name': [binding: FlowApplicationBinding, event: Event]
  'update-kind': [binding: FlowApplicationBinding, value: SelectValue]
  'update-required': [binding: FlowApplicationBinding, event: Event]
  'update-description': [binding: FlowApplicationBinding, event: Event]
  'update-request-schema': [binding: FlowApplicationBinding, event: Event]
  'update-media-types': [binding: FlowApplicationBinding, event: Event]
  'update-charset': [binding: FlowApplicationBinding, event: Event]
  'update-positive-limit': [binding: FlowApplicationBinding, fieldName: 'max_inline_bytes' | 'max_file_bytes' | 'max_files', event: Event]
  'delete-binding': [binding: FlowApplicationBinding]
}>()

function readBindingDescription(binding: FlowApplicationBinding): string {
  return typeof binding.metadata.description === 'string' ? binding.metadata.description : ''
}

function readRequestSchema(binding: FlowApplicationBinding): string {
  const schema = binding.config.request_schema
  if (!schema || typeof schema !== 'object' || Array.isArray(schema)) return ''
  return JSON.stringify(schema, null, 2)
}

function readAllowedMediaTypes(binding: FlowApplicationBinding): string {
  const values = binding.config.allowed_media_types
  return Array.isArray(values) ? values.map(String).join(', ') : ''
}

function readConfigText(binding: FlowApplicationBinding, fieldName: string): string {
  const value = binding.config[fieldName]
  return typeof value === 'string' ? value : ''
}

function readConfigNumber(binding: FlowApplicationBinding, fieldName: string): string {
  const value = binding.config[fieldName]
  return typeof value === 'number' && Number.isFinite(value) ? String(value) : ''
}

function showsMediaPolicy(binding: FlowApplicationBinding): boolean {
  return ['image-ref.v1', 'image-base64.v1', 'text.v1', 'file-ref.v1', 'file-refs.v1'].includes(props.getPayloadTypeId(binding))
}

function showsFilePolicy(binding: FlowApplicationBinding): boolean {
  return ['image-ref.v1', 'file-ref.v1', 'file-refs.v1'].includes(props.getPayloadTypeId(binding))
}

function showsInlineLimit(binding: FlowApplicationBinding): boolean {
  return ['value.v1', 'text.v1', 'image-base64.v1'].includes(props.getPayloadTypeId(binding))
}

function readTransportSummary(binding: FlowApplicationBinding): string {
  const configured = binding.config.transports
  if (Array.isArray(configured) && configured.length > 0) return configured.map(String).join(', ')
  if (['image-ref.v1', 'file-ref.v1', 'file-refs.v1'].includes(props.getPayloadTypeId(binding))) {
    return 'JSON reference / multipart upload'
  }
  return 'JSON'
}
</script>
