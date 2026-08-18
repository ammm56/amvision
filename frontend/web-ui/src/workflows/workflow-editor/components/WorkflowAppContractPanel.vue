<template>
  <div class="workflow-graph-app-contract">
    <div class="workflow-graph-panel__header workflow-graph-panel__header--compact">
      <h2>{{ t('workflowEditor.editor.applicationInputs') }}</h2>
      <StatusBadge tone="neutral">{{ inputBindings.length }} / {{ outputBindings.length }}</StatusBadge>
    </div>
    <section class="workflow-graph-contract-section">
      <div class="workflow-graph-contract-actions">
        <Button size="sm" variant="secondary" type="button" @click="emit('add-request-image-ref')">
          <Plus :size="14" />
          request_image_ref
        </Button>
        <Button size="sm" variant="secondary" type="button" @click="emit('add-request-image-base64')">
          <Plus :size="14" />
          request_image_base64
        </Button>
      </div>
      <div v-for="binding in inputBindings" :key="`contract-input-${binding.binding_id}`" class="workflow-graph-contract-binding">
        <div>
          <strong>{{ binding.binding_id }}</strong>
        </div>
        <small>{{ binding.required ? t('workflowEditor.editor.required') : t('workflowEditor.editor.optional') }}</small>
      </div>
    </section>
    <section class="workflow-graph-contract-section">
      <h3>{{ t('workflowEditor.editor.applicationOutputs') }}</h3>
      <div v-for="binding in outputBindings" :key="`contract-output-${binding.binding_id}`" class="workflow-graph-contract-binding">
        <div>
          <strong>{{ binding.binding_id }}</strong>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { Plus } from '@lucide/vue'
import { useI18n } from 'vue-i18n'

import Button from '@/shared/ui/components/Button.vue'
import StatusBadge from '@/shared/ui/data-display/StatusBadge.vue'
import type { FlowApplicationBinding } from '../types'

defineProps<{
  inputBindings: FlowApplicationBinding[]
  outputBindings: FlowApplicationBinding[]
}>()

const emit = defineEmits<{
  'add-request-image-ref': []
  'add-request-image-base64': []
}>()

const { t } = useI18n()
</script>
