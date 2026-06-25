<template>
  <div class="workflow-graph-app-contract">
    <div class="workflow-graph-panel__header workflow-graph-panel__header--compact">
      <h2>应用输入</h2>
      <StatusBadge tone="info">{{ inputBindings.length }} / {{ outputBindings.length }}</StatusBadge>
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
          <span>{{ getPayloadTypeId(binding) || 'unknown' }}</span>
        </div>
        <small>{{ binding.required ? '必填' : '可选' }} / {{ binding.binding_kind }}</small>
      </div>
    </section>
    <section class="workflow-graph-contract-section">
      <h3>应用输出</h3>
      <div v-for="binding in outputBindings" :key="`contract-output-${binding.binding_id}`" class="workflow-graph-contract-binding">
        <div>
          <strong>{{ binding.binding_id }}</strong>
          <span>{{ getPayloadTypeId(binding) || 'unknown' }}</span>
        </div>
        <small>{{ binding.binding_kind }}</small>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { Plus } from '@lucide/vue'

import Button from '@/shared/ui/components/Button.vue'
import StatusBadge from '@/shared/ui/data-display/StatusBadge.vue'
import type { FlowApplicationBinding } from '../types'

defineProps<{
  inputBindings: FlowApplicationBinding[]
  outputBindings: FlowApplicationBinding[]
  getPayloadTypeId: (binding: FlowApplicationBinding) => string
}>()

const emit = defineEmits<{
  'add-request-image-ref': []
  'add-request-image-base64': []
}>()
</script>
