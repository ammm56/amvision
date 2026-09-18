<template>
  <div class="state-colors">
    <div v-for="(row, index) in rows" :key="row.id" class="state-colors__row">
      <input v-model="row.key" aria-label="State" placeholder="State" :disabled="disabled" @input="commit" />
      <WorkflowDisplayColor v-model="row.color" label="State Color" presets :disabled="disabled" @update:model-value="commit" @validity-change="row.valid = $event; commit()" />
      <button type="button" :aria-label="t('workflowDisplay.deleteState')" :disabled="disabled" @click="rows.splice(index, 1); commit()"><Trash2 :size="16" /></button>
    </div>
    <small v-if="error" role="alert">{{ t(error) }}</small>
    <button type="button" :disabled="disabled || rows.length >= 64" @click="rows.push({ id: nextId++, key: '', color: null, valid: true }); commit()">{{ t('workflowDisplay.addState') }}</button>
  </div>
</template>
<script setup lang="ts">
import { useTranslation } from '@/platform/i18n'
const { t } = useTranslation()
import { ref, toRaw, watch } from 'vue'
import { Trash2 } from '@lucide/vue'
import WorkflowDisplayColor from './WorkflowDisplayColor.vue'
const props = defineProps<{ modelValue: unknown; disabled?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: Record<string, string>]; 'validity-change': [valid: boolean] }>()
let nextId = 0
const rows = ref(Object.entries((props.modelValue || {}) as Record<string, string>).map(([key, color]) => ({ id: nextId++, key, color: color as string | null, valid: true })))
const error = ref('')
let submitted: unknown
watch(() => props.modelValue, value => {
  if (toRaw(value) === submitted) return
  rows.value = Object.entries((value || {}) as Record<string, string>).map(([key, color]) => ({ id: nextId++, key, color, valid: true }))
  error.value = ''
})
function commit() {
  const keys = rows.value.map(row => row.key)
  error.value = keys.some(key => !key.trim() || key.length > 128) ? 'workflowDisplay.invalidState' : new Set(keys).size !== keys.length ? 'workflowDisplay.duplicateState' : ''
  const valid = !error.value && rows.value.every(row => row.valid)
  emit('validity-change', valid)
  if (valid) {
    const value = Object.fromEntries(rows.value.map(row => [row.key, row.color || 'neutral']))
    submitted = value
    emit('update:modelValue', value)
  }
}
</script>
<style scoped>
.state-colors { display: grid; gap: 8px; }
.state-colors__row { display: grid; grid-template-columns: minmax(80px, 1fr) minmax(180px, 2fr) auto; gap: 8px; align-items: start; }
.state-colors input { min-width: 0; width: 100%; padding: 8px; border: 1px solid var(--am-border-strong); border-radius: var(--am-radius-sm); background: var(--am-input); color: var(--am-text); font: inherit; }
.state-colors button { justify-self: start; padding: 6px; border: 1px solid var(--am-border); border-radius: var(--am-radius-sm); background: var(--am-surface); color: var(--am-text); cursor: pointer; }
.state-colors small { color: var(--am-danger-text); }
@media (max-width: 540px) { .state-colors__row { grid-template-columns: minmax(0, 1fr) auto; } .state-colors__row > input { grid-column: 1 / -1; } }
</style>
