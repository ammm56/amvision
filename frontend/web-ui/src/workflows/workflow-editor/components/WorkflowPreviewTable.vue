<template>
  <div class="workflow-preview-table" :class="{ 'workflow-preview-table--compact': compact }">
    <div v-if="displayRows.length === 0" class="workflow-preview-table__empty">{{ emptyText || t('workflowEditor.editor.noData') }}</div>
    <div v-else class="workflow-preview-table__scroller">
      <table>
        <thead>
          <tr>
            <th v-for="column in columns" :key="column.key">{{ column.label }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(row, rowIndex) in displayRows" :key="`row-${rowIndex}`" :tabindex="selectable?0:undefined" :role="selectable?'button':undefined" :aria-pressed="selectable?selectedIndex===rowIndex+rowOffset:undefined" :class="{selected:selectedIndex===rowIndex+rowOffset}" @click="selectable&&emit('select',rowIndex+rowOffset)" @keydown.enter="selectable&&emit('select',rowIndex+rowOffset)" @keydown.space.prevent="selectable&&emit('select',rowIndex+rowOffset)">
            <td v-for="column in columns" :key="`${rowIndex}-${column.key}`" :title="String(row[column.key]??'')">{{ formatResultCell(row[column.key],column.format,locale==='zh-CN',reasonLabels) }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <small v-if="truncatedCount > 0" class="workflow-preview-table__summary">
      {{ t('workflowEditor.editor.tableTruncated', { shown: displayRows.length, total: rows.length }) }}
    </small>
    <PaginationControls v-if="maxRows<=0 && rows.length>100" :offset="offset" :limit="100" :item-count="displayRows.length" :total-count="rows.length" @previous="offset-=100" @next="offset+=100" />
  </div>
</template>

<script setup lang="ts">
import { computed,ref,watch,inject } from 'vue'
import PaginationControls from '@/shared/ui/components/PaginationControls.vue'
import { useTranslation } from '@/platform/i18n'
import {useI18n} from 'vue-i18n'
import {formatResultCell,resultReasonLabelsKey,type ResultColumn as PreviewTableColumnView} from '@/shared/ui/image-viewer/result-format'

type PreviewTableRow = Record<string, unknown>

const props = withDefaults(defineProps<{
  columns: PreviewTableColumnView[]
  rows: PreviewTableRow[]
  emptyText?: string | null
  maxRows?: number
  compact?: boolean
  selectable?:boolean
  selectedIndex?:number|null
}>(), {
  emptyText: '',
  maxRows: 20,
  compact: false,
})

const { t } = useTranslation()
const {locale}=useI18n()
const reasonLabels=inject(resultReasonLabelsKey,{})
const emit=defineEmits<{select:[index:number]}>()
const offset=ref(0)
watch(()=>props.rows,()=>{offset.value=0})
const displayRows = computed(() => props.maxRows > 0 ? props.rows.slice(0, props.maxRows) : props.rows.slice(offset.value,offset.value+100))
const truncatedCount = computed(() => props.maxRows>0?Math.max(props.rows.length - displayRows.value.length, 0):0)
const rowOffset=computed(()=>props.maxRows>0?0:offset.value)

</script>

<style scoped>
.workflow-preview-table {
  display: grid;
  gap: 6px;
  min-height: 0;
  --workflow-preview-table-line: var(--am-graph-node-border);
  --workflow-preview-table-surface: var(--am-graph-panel);
  --workflow-preview-table-surface-soft: var(--am-graph-panel-soft);
  --workflow-preview-table-header-color: var(--am-graph-text-strong);
  --workflow-preview-table-cell-color: var(--am-graph-text);
  --workflow-preview-table-muted: var(--am-graph-text-muted);
}

.workflow-preview-table__scroller {
  min-width: 0;
  overflow: auto;
  border: 1px solid var(--workflow-preview-table-line);
  border-radius: 8px;
  background: var(--workflow-preview-table-surface);
}

.workflow-preview-table table {
  width: 100%;
  border-collapse: collapse;
  table-layout: fixed;
  font-size: 12px;
}

.workflow-preview-table th,
.workflow-preview-table td {
  padding: 6px 8px;
  border-bottom: 1px solid var(--workflow-preview-table-line);
  text-align: left;
  vertical-align: top;
  overflow-wrap: anywhere;
}
.workflow-preview-table tr[role=button] { cursor:pointer; }
.workflow-preview-table tr[role=button]:hover { background:var(--am-surface-soft); }
.workflow-preview-table tr.selected { background:color-mix(in srgb,var(--am-brand-primary) 12%,var(--am-surface)); }

.workflow-preview-table th {
  position: sticky;
  top: 0;
  background: var(--workflow-preview-table-surface-soft);
  color: var(--workflow-preview-table-header-color);
  font-weight: 600;
}

.workflow-preview-table td {
  color: var(--workflow-preview-table-cell-color);
}

.workflow-preview-table__empty,
.workflow-preview-table__summary {
  color: var(--workflow-preview-table-muted);
  font-size: 11px;
}

.workflow-preview-table__empty {
  display: grid;
  min-height: 72px;
  place-items: center;
  border: 1px dashed color-mix(in srgb, var(--workflow-preview-table-line) 72%, transparent);
  border-radius: 8px;
  padding: 10px;
  text-align: center;
  background: color-mix(in srgb, var(--workflow-preview-table-surface-soft) 72%, transparent);
}

.workflow-preview-table--compact table {
  font-size: 11px;
}

.workflow-preview-table--compact th,
.workflow-preview-table--compact td {
  padding: 5px 6px;
}

.workflow-preview-table--compact .workflow-preview-table__scroller {
  max-height: 132px;
}
</style>
