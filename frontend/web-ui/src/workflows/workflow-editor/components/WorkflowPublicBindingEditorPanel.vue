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
        <small>{{ readEndpointText(binding) }} · {{ getPayloadTypeId(binding) || 'unknown' }}</small>
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
        <span>binding kind</span>
        <SelectField
          :model-value="binding.binding_kind"
          :options="readKindOptions(binding)"
          @update:model-value="emit('update-kind', binding, $event)"
        />
      </label>
      <label v-if="binding.direction === 'input'" class="workflow-graph-public-binding-editor__checkbox">
        <input type="checkbox" :checked="binding.required" @change="emit('update-required', binding, $event)" />
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

const { t } = useTranslation()

type SelectValue = string | number | boolean | null

interface SelectOption {
  label: string
  value: SelectValue
  description?: string
}

defineProps<{
  title: string
  bindings: FlowApplicationBinding[]
  readEndpointText: (binding: FlowApplicationBinding) => string
  readDisplayName: (binding: FlowApplicationBinding) => string
  readKindOptions: (binding: FlowApplicationBinding) => SelectOption[]
  getPayloadTypeId: (binding: FlowApplicationBinding) => string
}>()

const emit = defineEmits<{
  'update-binding-id': [binding: FlowApplicationBinding, event: Event]
  'update-display-name': [binding: FlowApplicationBinding, event: Event]
  'update-kind': [binding: FlowApplicationBinding, value: SelectValue]
  'update-required': [binding: FlowApplicationBinding, event: Event]
  'delete-binding': [binding: FlowApplicationBinding]
}>()
</script>
