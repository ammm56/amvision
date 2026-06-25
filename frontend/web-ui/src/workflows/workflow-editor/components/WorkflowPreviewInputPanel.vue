<template>
  <div class="workflow-graph-preview-inputs">
    <div class="workflow-graph-panel__header">
      <h2>Preview 输入</h2>
      <div class="workflow-graph-panel__tools">
        <InfoHint
          v-if="helpText"
          :text="helpText"
        />
        <StatusBadge :tone="blockingMessages.length ? 'danger' : 'success'">
          {{ blockingMessages.length ? '缺少输入' : '就绪' }}
        </StatusBadge>
      </div>
    </div>
    <section v-for="binding in bindings" :key="binding.binding_id" class="workflow-graph-preview-binding">
      <div class="workflow-graph-preview-binding__header">
        <span class="workflow-graph-preview-binding__summary">
          <strong>{{ binding.binding_id }}</strong>
          <small>{{ getPayloadTypeId(binding) || 'unknown' }}</small>
        </span>
        <div class="workflow-graph-preview-binding__tools">
          <InfoHint :text="readBindingHelpText(binding)" />
          <StatusBadge :tone="binding.required ? 'warning' : 'neutral'">{{ binding.required ? '必填' : '可选' }}</StatusBadge>
        </div>
      </div>
      <template v-if="states[binding.binding_id] && getPayloadTypeId(binding) === 'value.v1'">
        <div class="workflow-graph-value-fields">
          <label v-for="field in states[binding.binding_id].valueFields" :key="field.id" class="workflow-graph-value-field">
            <input v-model="field.key" placeholder="字段名" />
            <input v-model="field.value" placeholder="字段值" />
            <button type="button" title="删除字段" @click="emit('remove-value-field', binding.binding_id, field.id)">
              <Trash2 :size="14" />
            </button>
          </label>
        </div>
        <Button size="sm" variant="secondary" type="button" @click="emit('add-value-field', binding.binding_id)">
          <Plus :size="14" />
          添加字段
        </Button>
      </template>
      <template v-else-if="states[binding.binding_id] && getPayloadTypeId(binding) === 'image-base64.v1'">
        <FilePicker
          v-model="states[binding.binding_id].file"
          icon="image"
          accept="image/*"
          label="图片文件"
        />
        <label class="workflow-graph-preview-field">
          <span>media_type</span>
          <input v-model="states[binding.binding_id].mediaType" placeholder="自动使用文件类型" />
        </label>
      </template>
      <template v-else-if="states[binding.binding_id] && getPayloadTypeId(binding) === 'image-ref.v1'">
        <label class="workflow-graph-preview-field">
          <span>引用来源</span>
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
          <span>输入值</span>
          <input v-model="states[binding.binding_id].plainValue" placeholder="按字符串值提交" />
        </label>
      </template>
    </section>
  </div>
</template>

<script setup lang="ts">
import { Plus, Trash2 } from '@lucide/vue'

import Button from '@/shared/ui/components/Button.vue'
import FilePicker from '@/shared/ui/components/FilePicker.vue'
import InfoHint from '@/shared/ui/components/InfoHint.vue'
import SelectField from '@/shared/ui/components/Select.vue'
import StatusBadge from '@/shared/ui/data-display/StatusBadge.vue'
import type { FlowApplicationBinding } from '../types'
import type { PreviewInputState, PreviewSelectOption, PreviewSelectValue } from '../preview/useWorkflowPreviewInputs'

defineProps<{
  bindings: FlowApplicationBinding[]
  states: Record<string, PreviewInputState>
  blockingMessages: string[]
  helpText: string
  imageRefTransportKindOptions: PreviewSelectOption[]
  getPayloadTypeId: (binding: FlowApplicationBinding) => string
  readBindingHelpText: (binding: FlowApplicationBinding) => string
}>()

const emit = defineEmits<{
  'add-value-field': [bindingId: string]
  'remove-value-field': [bindingId: string, fieldId: string]
  'set-image-ref-transport-kind': [bindingId: string, value: PreviewSelectValue]
}>()
</script>
