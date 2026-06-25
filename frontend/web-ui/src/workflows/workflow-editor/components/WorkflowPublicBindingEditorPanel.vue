<template>
  <div class="workflow-graph-inspector-body">
    <div class="workflow-graph-panel__header workflow-graph-panel__header--compact">
      <div>
        <p>Public IO</p>
        <h2>{{ title }}</h2>
      </div>
      <StatusBadge tone="info">{{ bindings.length }}</StatusBadge>
    </div>
    <EmptyState v-if="bindings.length === 0" title="暂无公开接口" description="右键节点端口后选择公开为应用输入或应用输出。" />
    <section
      v-for="binding in bindings"
      :key="`public-binding-editor-${binding.direction}-${binding.binding_id}`"
      class="workflow-graph-public-binding-editor"
    >
      <div class="workflow-graph-public-binding-editor__title">
        <strong>{{ binding.binding_id }}</strong>
        <small>{{ readEndpointText(binding) }}</small>
      </div>
      <label class="workflow-graph-preview-field">
        <span>公开 id</span>
        <input :value="binding.binding_id" @change="emit('update-binding-id', binding, $event)" />
      </label>
      <label class="workflow-graph-preview-field">
        <span>显示名称</span>
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
        <span>必填输入</span>
      </label>
      <div class="workflow-graph-inspector-row">
        <span>payload type</span>
        <strong>{{ getPayloadTypeId(binding) || 'unknown' }}</strong>
      </div>
      <Button variant="danger" type="button" @click="emit('delete-binding', binding)">
        <Trash2 :size="16" />
        删除公开接口
      </Button>
    </section>
  </div>
</template>

<script setup lang="ts">
import { Trash2 } from '@lucide/vue'

import Button from '@/shared/ui/components/Button.vue'
import SelectField from '@/shared/ui/components/Select.vue'
import StatusBadge from '@/shared/ui/data-display/StatusBadge.vue'
import EmptyState from '@/shared/ui/feedback/EmptyState.vue'
import type { FlowApplicationBinding } from '../types'

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
