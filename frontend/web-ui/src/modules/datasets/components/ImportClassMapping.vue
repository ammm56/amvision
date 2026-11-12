<template>
  <Button v-if="!expanded" size="sm" class="mapping-add" :aria-expanded="false" @click="expand"><Plus :size="15" />{{ label('添加映射', 'Add mapping') }}</Button>
  <template v-else>
  <div class="mapping-heading"><h2>{{ label('类别映射', 'Class mapping') }}</h2>
    <Button size="sm" variant="ghost" :aria-expanded="true" @click="collapse">{{ label('收起', 'Collapse') }}</Button>
  </div>
  <ResourceTable v-if="rows.length" class="dataset-table" :label="label('类别映射', 'Class mapping')">
    <thead><tr>
      <th v-if="hasIds">{{ label('源类别 ID', 'Source class ID') }}</th>
      <th>{{ label('源类别', 'Source class') }}</th>
      <th>{{ label('目标类别', 'Target class') }}</th>
      <th>{{ label('对象数', 'Objects') }}</th>
    </tr></thead>
    <tbody><tr v-for="row in rows" :key="row.source">
      <td v-if="hasIds">{{ row.id }}</td><td :title="row.name">{{ row.name || '—' }}</td>
      <td><div class="mapping-target">
        <input :value="row.target" :aria-label="label('目标类别', 'Target class') + ' · ' + (row.name || row.source)" @input="update(row.source, ($event.target as HTMLInputElement).value)" />
        <Button v-if="row.manual || row.target !== row.name" size="sm" variant="ghost" icon-only :aria-label="label('移除映射', 'Remove mapping') + ' · ' + row.source" @click="remove(row)"><Trash2 :size="15" /></Button>
      </div></td>
      <td>{{ row.count?.toLocaleString() ?? '—' }}</td>
    </tr></tbody>
  </ResourceTable>
  <div v-if="editing" class="mapping-entry" @keydown.esc.stop.prevent="close">
    <label class="field">{{ sourceLabel }}<input ref="sourceInput" v-model="source" :list="sourceListId" @keydown.enter.prevent="apply" /></label>
    <datalist :id="sourceListId"><option v-for="row in available" :key="row.source" :value="row.source">{{ row.name }}</option></datalist>
    <label class="field">{{ label('目标类别', 'Target class') }}<input v-model="target" @keydown.enter.prevent="apply" /></label>
    <Button size="sm" @click="apply">{{ label('确定', 'Apply') }}</Button>
    <Button size="sm" variant="ghost" @click="close">{{ label('取消', 'Cancel') }}</Button>
    <p v-if="error" role="alert">{{ error }}</p>
  </div>
  <Button v-else-if="allowSupplement" ref="addButton" size="sm" class="mapping-add" @click="open"><Plus :size="15" />{{ label('补录源类别', 'Enter source class') }}</Button>
  </template>
</template>
<script setup lang="ts">
import { computed, nextTick, ref, useId, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Plus, Trash2 } from '@lucide/vue'
import Button from '@/shared/ui/components/Button.vue'
import ResourceTable from '@/shared/ui/data-display/ResourceTable.vue'

export interface ImportMapRow {
  source: string; id: string; name: string; target: string; count: number | null; manual?: boolean
}
const rows = defineModel<ImportMapRow[]>({ required: true })
const available = computed(() => rows.value.filter(row => row.target === row.name && !row.manual))
const sourceListId = useId()
const props = defineProps<{ format: string; allowSupplement: boolean }>()
const emit = defineEmits<{ editing: [value: boolean] }>()
const { locale } = useI18n()
const label = (zh: string, en: string) => locale.value.startsWith('zh') ? zh : en
const numeric = computed(() => ['coco','yolo'].includes(props.format))
const hasIds = computed(() => numeric.value || rows.value.some(row => row.id !== '—'))
const sourceLabel = computed(() => numeric.value ? label('源类别 ID', 'Source class ID') : label('源类别', 'Source class'))
const editing = ref(false), source = ref(''), target = ref(''), error = ref('')
const sourceInput = ref<HTMLInputElement>(), addButton = ref<InstanceType<typeof Button>>()
const expanded = ref(rows.value.some(row => row.manual || row.target !== row.name))
function expand() {
  expanded.value = true
  if (!rows.value.length && props.allowSupplement) void open()
}
function collapse() {
  if (editing.value) void close()
  expanded.value = false
}
watch([source, target], () => { error.value = '' })
async function open() {
  editing.value = true
  emit('editing', true)
  await nextTick()
  sourceInput.value?.focus()
}
async function close() {
  editing.value = false
  emit('editing', false)
  source.value = target.value = error.value = ''
  await nextTick()
  addButton.value?.$el.focus()
}
function update(key: string, value: string) {
  rows.value = rows.value.map(row => row.source === key ? { ...row, target: value } : row)
}
function remove(row: ImportMapRow) {
  if (row.manual) rows.value = rows.value.filter(item => item.source !== row.source)
  else update(row.source, row.name)
}
function apply() {
  const key = source.value.trim(), value = target.value.trim()
  if (!key || !value) { error.value = label('请填写源类别和目标类别。', 'Enter the source and target class.'); return }
  if (numeric.value && !/^(0|[1-9]\d*)$/.test(key)) { error.value = label('请填写整数类别 ID。', 'Enter a numeric class ID.'); return }
  const known = rows.value.find(row => row.source === key)
  if (known) {
    if (known.manual || known.target !== known.name) { error.value = label('该源类别已有映射，请直接编辑表中对应行。', 'This source is already mapped. Edit its row instead.'); return }
    update(key, value)
  } else {
    rows.value = [...rows.value, { source: key, id: numeric.value ? key : '—', name: numeric.value ? '' : key, target: value, count: null, manual: true }]
  }
  void close()
}
</script>
<style scoped>
.mapping-add { justify-self: start; }
.mapping-heading { display: flex; align-items: center; justify-content: space-between; }
.mapping-heading h2 { margin: 0; font-size: 16px; }
.mapping-entry, .mapping-target { display: flex; align-items: end; gap: 8px; }
.mapping-entry { flex-wrap: wrap; }
.mapping-entry .field { flex: 1 1 10rem; min-width: 0; }
.mapping-target { align-items: center; }
.mapping-target input { width: 100%; min-width: 0; }
.mapping-entry p { flex-basis: 100%; margin: 0; color: var(--am-danger-text); }
</style>
