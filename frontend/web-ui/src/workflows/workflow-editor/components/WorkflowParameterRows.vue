<template>
  <div class="parameter-rows">
    <div v-for="(row, index) in rows" :key="index" class="parameter-rows__row">
      <div class="parameter-rows__actions">
        <span>{{ index + 1 }}</span>
        <button type="button" :disabled="disabled || index === 0" aria-label="上移" @click="move(index, -1)">↑</button>
        <button type="button" :disabled="disabled || index === rows.length - 1" aria-label="下移" @click="move(index, 1)">↓</button>
        <button type="button" :disabled="disabled" aria-label="删除行" @click="remove(index)">删除</button>
      </div>
      <label v-for="(property, key) in properties" :key="key">
        <span>{{ property.title || key }}</span>
        <template v-if="key === 'condition' && !advanced[index] && simpleCondition(row[key])">
          <input aria-label="Path" placeholder="Path" :value="condition(row).path ?? ''" :disabled="disabled" @input="setConditionPath(index, $event)" />
          <textarea aria-label="Match Values" placeholder="Match Values · 每行一个值" :rows="Math.min(8, Math.max(3, matchValues(row).split('\n').length))" :value="matchValues(row)" :disabled="disabled" @change="setMatchValues(index, $event)" />
          <button type="button" :disabled="disabled" @click="advanced[index] = true">编辑条件 JSON</button>
        </template>
        <select v-else-if="Array.isArray(property.enum)" :value="row[key] ?? property.default ?? property.enum[0]" :disabled="disabled" @change="set(index, key, ($event.target as HTMLSelectElement).value)">
          <option v-for="option in property.enum" :key="String(option)" :value="String(option)">{{ option }}</option>
        </select>
        <textarea v-else-if="property.type === 'object' || property.type === 'array'" :value="JSON.stringify(row[key] ?? {}, null, 2)" :disabled="disabled" @change="setJson(index, key, $event)" />
        <input v-else :type="property.type === 'integer' ? 'number' : 'text'" :min="Number(property.minimum ?? 0)" :max="property.maximum == null ? undefined : Number(property.maximum)" :value="String(row[key] ?? property.default ?? '')" :disabled="disabled" @input="set(index, key, property.type === 'integer' ? Number(($event.target as HTMLInputElement).value) : ($event.target as HTMLInputElement).value)" />
      </label>
    </div>
    <span v-if="error" role="alert">{{ error }}</span>
    <button type="button" :disabled="disabled || rows.length >= Number(schema.maxItems ?? 64)" @click="add">添加行</button>
  </div>
</template>
<script setup lang="ts">
import { computed, ref } from 'vue'
import type { WorkflowJsonObject } from '../types'
const props = defineProps<{ modelValue: unknown; schema: WorkflowJsonObject; disabled?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: unknown]; 'validity-change': [valid: boolean] }>()
const errors = ref<Record<string, string>>({})
const error = computed(() => Object.values(errors.value)[0] ?? '')
const advanced = ref<Record<number, boolean>>({})
const rows = computed(() => Array.isArray(props.modelValue) ? props.modelValue as WorkflowJsonObject[] : [])
const properties = computed(() => ((props.schema.items as WorkflowJsonObject)?.properties ?? {}) as Record<string, WorkflowJsonObject>)
function set(index: number, key: string, value: unknown) {
  delete errors.value[`${index}:${key}`]
  emit('validity-change', Object.keys(errors.value).length === 0)
  emit('update:modelValue', rows.value.map((row, i) => i === index ? { ...row, [key]: value } : row))
}
function setJson(index: number, key: string, event: Event) {
  try { set(index, key, JSON.parse((event.target as HTMLTextAreaElement).value)) }
  catch { errors.value[`${index}:${key}`] = 'JSON 格式无效，尚未应用此字段'; emit('validity-change', false) }
}
function add() {
  const row: WorkflowJsonObject = {}
  for (const [key, spec] of Object.entries(properties.value)) {
    row[key] = spec.default ?? (Array.isArray(spec.enum) ? spec.enum[0] : key === 'condition' ? { operator: 'in', path: '', right: [] } : spec.type === 'object' ? {} : '')
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
.parameter-rows { display: grid; gap: 8px; min-width: 0; color: var(--am-text); font-family: var(--am-font-sans); }
.parameter-rows__row { border: 1px solid var(--am-border); border-radius: var(--am-radius-sm); padding: 8px; display: grid; gap: 6px; min-width: 0; }
.parameter-rows__actions { display: flex; gap: 6px; align-items: center; }
.parameter-rows__actions span { margin-right: auto; color: var(--am-text-muted); }
.parameter-rows label { display: grid; gap: 4px; min-width: 0; font-size: 12px; }
.parameter-rows input, .parameter-rows select, .parameter-rows textarea { width: 100%; box-sizing: border-box; min-width: 0; padding: 5px; background: var(--am-input); color: var(--am-text); border: 1px solid var(--am-border); border-radius: var(--am-radius-sm); font: inherit; }
.parameter-rows textarea { min-height: 56px; resize: vertical; }
.parameter-rows button { color: var(--am-text); background: var(--am-surface); border: 1px solid var(--am-border); border-radius: var(--am-radius-sm); cursor: pointer; font: inherit; min-height: 28px; }
.parameter-rows [role='alert'] { color: var(--am-danger-text); }
</style>
