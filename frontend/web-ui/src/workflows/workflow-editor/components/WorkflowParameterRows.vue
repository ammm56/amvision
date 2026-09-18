<template>
  <div class="parameter-rows">
    <div v-for="(row, index) in rows" :key="index" class="parameter-rows__row" :class="{ 'parameter-rows__row--reducer': isReducer, 'parameter-rows__row--count': isReducer && row.operation === 'count' }">
      <div class="parameter-rows__actions">
        <span>{{ index + 1 }}</span>
        <button type="button" :disabled="disabled || index === 0" :aria-label="t('workflowDisplay.moveUp')" :title="t('workflowDisplay.moveUp')" @click="move(index, -1)"><ArrowUp :size="16" /></button>
        <button type="button" :disabled="disabled || index === rows.length - 1" :aria-label="t('workflowDisplay.moveDown')" :title="t('workflowDisplay.moveDown')" @click="move(index, 1)"><ArrowDown :size="16" /></button>
        <button type="button" :disabled="disabled" :aria-label="t('workflowDisplay.deleteRow')" :title="t('workflowDisplay.deleteRow')" @click="remove(index)"><Trash2 :size="16" /></button>
      </div>
      <label v-for="(property, key) in visibleProperties(row)" :key="key" :class="{ 'parameter-rows__field--wide': property.type === 'object' || property.type === 'array' }">
        <span>{{ property.title || key }}</span>
        <WorkflowDisplayColor v-if="property['x-ui-widget'] === 'display-color'" :model-value="row[key]" :label="String(property.title || key)" :disabled="disabled" :default-color="key === 'label_color' ? 'var(--am-text-muted)' : 'var(--am-text)'" @update:model-value="set(index, key, $event)" @validity-change="setValidity(index, key, $event)" />
        <WorkflowStateColors v-else-if="property['x-ui-widget'] === 'state-colors'" :model-value="row[key]" :disabled="disabled" @update:model-value="set(index, key, $event)" @validity-change="setValidity(index, key, $event)" />
        <template v-else-if="key === 'condition' && !advanced[index] && simpleCondition(row[key])">
          <input aria-label="Path" placeholder="Path" :value="condition(row).path ?? ''" :disabled="disabled" @input="setConditionPath(index, $event)" />
          <textarea aria-label="Match Values" :placeholder="t('workflowDisplay.matchValues')" :rows="Math.min(8, Math.max(3, matchValues(row).split('\n').length))" :value="matchValues(row)" :disabled="disabled" @change="setMatchValues(index, $event)" />
          <button type="button" :disabled="disabled" @click="advanced[index] = true">{{ t('workflowDisplay.editCondition') }}</button>
        </template>
        <Select v-else-if="Array.isArray(property.enum)" floating
          :model-value="String(row[key] ?? property.default ?? property.enum[0])"
          :options="property.enum.map(option => ({ value: String(option), label: optionLabel(key, option) }))"
          :aria-label="String(property.title || key)" :disabled="disabled"
          @update:model-value="set(index, key, $event)" />
        <textarea v-else-if="property.type === 'object' || property.type === 'array'" :value="JSON.stringify(row[key] ?? {}, null, 2)" :disabled="disabled" @change="setJson(index, key, $event)" />
        <input v-else :type="property.type === 'integer' ? 'number' : 'text'" :min="Number(property.minimum ?? 0)" :max="property.maximum == null ? undefined : Number(property.maximum)" :value="String(row[key] ?? property.default ?? '')" :disabled="disabled" @input="set(index, key, property.type === 'integer' ? Number(($event.target as HTMLInputElement).value) : ($event.target as HTMLInputElement).value)" />
      </label>
    </div>
    <span v-if="error" role="alert">{{ t(error) }}</span>
    <button type="button" class="parameter-rows__add" :disabled="disabled || rows.length >= Number(schema.maxItems ?? 64)" @click="add"><Plus :size="16" />{{ t('workflowDisplay.addRow') }}</button>
  </div>
</template>
<script setup lang="ts">
import { useTranslation } from '@/platform/i18n'
const { t } = useTranslation()
import { computed, ref } from 'vue'
import { ArrowDown, ArrowUp, Plus, Trash2 } from '@lucide/vue'
import Select from '@/shared/ui/components/Select.vue'
import WorkflowDisplayColor from './WorkflowDisplayColor.vue'
import WorkflowStateColors from './WorkflowStateColors.vue'
import type { WorkflowJsonObject } from '../types'
const props = defineProps<{ modelValue: unknown; schema: WorkflowJsonObject; disabled?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: unknown]; 'validity-change': [valid: boolean] }>()
const errors = ref<Record<string, string>>({})
const error = computed(() => Object.values(errors.value)[0] ?? '')
const advanced = ref<Record<number, boolean>>({})
const rows = computed(() => Array.isArray(props.modelValue) ? props.modelValue as WorkflowJsonObject[] : [])
const properties = computed(() => ((props.schema.items as WorkflowJsonObject)?.properties ?? {}) as Record<string, WorkflowJsonObject>)
// 仅识别归约配置的结构，不把生产字段或模型分类写入通用编辑器。
const isReducer = computed(() => Boolean(properties.value.output_key && properties.value.source_path && properties.value.operation))
function visibleProperties(row: WorkflowJsonObject) {
  return Object.fromEntries(Object.entries(properties.value).filter(([key]) => {
    if (properties.value.states?.['x-ui-widget'] === 'state-colors') {
      if (key === 'states') return row.format === 'status'
      if (key === 'precision') return ['number', 'percent'].includes(String(row.format))
    }
    if (!isReducer.value) return true
    if (row.operation === 'count') return !['source_path', 'numeric_type', 'missing_policy'].includes(key)
    return row.operation !== 'last' || key !== 'numeric_type'
  }))
}
function optionLabel(key: string, value: unknown): string {
  if (!isReducer.value) return String(value)
  const labels: Record<string, Record<string, string>> = {
    operation: { sum: 'Sum', count: 'Count', min: 'Minimum', max: 'Maximum', last: 'Last Value' },
    numeric_type: { integer: 'Integer', number: 'Number' },
    missing_policy: { error: 'Report Error', skip: 'Skip Missing' },
  }
  return labels[key]?.[String(value)] ?? String(value)
}
function set(index: number, key: string, value: unknown) {
  if (key === 'format') { delete errors.value[`${index}:states`]; delete errors.value[`${index}:precision`] }
  delete errors.value[`${index}:${key}`]
  emit('validity-change', Object.keys(errors.value).length === 0)
  emit('update:modelValue', rows.value.map((row, i) => i === index ? { ...row, [key]: value } : row))
}
function setValidity(index: number, key: string, valid: boolean) {
  if (valid) delete errors.value[`${index}:${key}`]
  else errors.value[`${index}:${key}`] = 'workflowDisplay.invalidConfig'
  emit('validity-change', Object.keys(errors.value).length === 0)
}
function setJson(index: number, key: string, event: Event) {
  try { set(index, key, JSON.parse((event.target as HTMLTextAreaElement).value)) }
  catch { errors.value[`${index}:${key}`] = 'workflowDisplay.invalidJson'; emit('validity-change', false) }
}
function add() {
  const row: WorkflowJsonObject = {}
  for (const [key, spec] of Object.entries(properties.value)) {
    row[key] = spec['x-ui-widget'] === 'display-color' ? null : spec.default ?? (Array.isArray(spec.enum) ? spec.enum[0] : key === 'condition' ? { operator: 'in', path: '', right: [] } : spec.type === 'object' ? {} : '')
  }
  emit('update:modelValue', [...rows.value, row])
}
function reorderErrors(order: number[]) {
  errors.value = Object.fromEntries(Object.entries(errors.value).flatMap(([key, message]) => {
    const split = key.indexOf(':'); const newIndex = order.indexOf(Number(key.slice(0, split)))
    return newIndex < 0 ? [] : [[`${newIndex}${key.slice(split)}`, message]]
  }))
  emit('validity-change', Object.keys(errors.value).length === 0)
}
function remove(index: number) {
  reorderErrors(rows.value.map((_, i) => i).filter(i => i !== index))
  advanced.value = {}; emit('update:modelValue', rows.value.filter((_, i) => i !== index))
}
function move(index: number, direction: number) {
  const next = [...rows.value]; const target = index + direction
  ;[next[index], next[target]] = [next[target]!, next[index]!]
  const order = rows.value.map((_, i) => i)
  ;[order[index], order[target]] = [order[target]!, order[index]!]
  reorderErrors(order)
  advanced.value = {}; emit('update:modelValue', next)
}
function simpleCondition(value: unknown) { return !value || (typeof value === 'object' && (value as WorkflowJsonObject).operator === 'in') }
function condition(row: WorkflowJsonObject) { return (row.condition ?? { operator: 'in', right: [] }) as WorkflowJsonObject }
function matchValues(row: WorkflowJsonObject) {
  const values = condition(row).right
  return Array.isArray(values) ? values.map(value => typeof value === 'string' ? JSON.stringify(value) : String(value)).join('\n') : ''
}
function setConditionPath(index: number, event: Event) { set(index, 'condition', { ...condition(rows.value[index]!), path: (event.target as HTMLInputElement).value }) }
function setMatchValues(index: number, event: Event) {
  const right = (event.target as HTMLTextAreaElement).value.split('\n').filter(line => line.trim()).map(line => {
    try { return JSON.parse(line) } catch { return line.trim() }
  })
  set(index, 'condition', { ...condition(rows.value[index]!), right })
}
</script>
<style scoped>
.parameter-rows { display: grid; gap: 12px; min-width: 0; color: var(--am-text); font-family: var(--am-font-sans); }
.parameter-rows__row { border: 1px solid var(--am-border); border-radius: var(--am-radius-md); padding: 12px; display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; min-width: 0; align-items: start; }
.parameter-rows__actions, .parameter-rows__field--wide { grid-column: 1 / -1; }
.parameter-rows__row--reducer { grid-template-columns: repeat(6, minmax(0, 1fr)); }
.parameter-rows__row--reducer > label { grid-column: span 2; }
.parameter-rows__row--reducer > label:nth-of-type(-n+2), .parameter-rows__row--count > label { grid-column: span 3; }
.parameter-rows__actions { display: flex; gap: 6px; align-items: center; }
.parameter-rows__actions span { margin-right: auto; color: var(--am-text-muted); }
.parameter-rows label { display: grid; gap: 6px; min-width: 0; font-size: 13px; font-weight: 500; }
.parameter-rows input, .parameter-rows select, .parameter-rows textarea { width: 100%; box-sizing: border-box; min-width: 0; min-height: 36px; padding: 8px 10px; background: var(--am-input); color: var(--am-text); border: 1px solid var(--am-border-strong); border-radius: var(--am-radius-sm); font: inherit; font-weight: 400; }
.parameter-rows :deep(.ui-select__button) { min-height: 36px; padding: 8px 10px; font: inherit; font-weight: 400; }
.parameter-rows textarea { min-height: 56px; resize: vertical; }
.parameter-rows button { display: inline-flex; align-items: center; justify-content: center; gap: 6px; padding: 6px 8px; color: var(--am-text); background: var(--am-surface); border: 1px solid var(--am-border); border-radius: var(--am-radius-sm); cursor: pointer; font: inherit; min-height: 32px; }
.parameter-rows button:hover:not(:disabled) { background: var(--am-surface-soft); }
.parameter-rows :is(input, select, textarea, button):focus-visible { outline: 2px solid var(--am-focus-ring); outline-offset: 2px; }
.parameter-rows :disabled { opacity: .5; cursor: default; }
.parameter-rows__add { justify-self: start; }
.parameter-rows [role='alert'] { color: var(--am-danger-text); }
@media (max-width: 540px) { .parameter-rows__row { grid-template-columns: minmax(0, 1fr); } .parameter-rows__row > label { grid-column: 1 / -1; } }
</style>
