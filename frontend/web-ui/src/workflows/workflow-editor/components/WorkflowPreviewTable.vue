<template>
  <div class="workflow-preview-table" :class="{ 'workflow-preview-table--compact': compact }">
    <div v-if="displayRows.length === 0" class="workflow-preview-table__empty">{{ emptyText || '暂无数据' }}</div>
    <div v-else class="workflow-preview-table__scroller">
      <table>
        <thead>
          <tr>
            <th v-for="column in columns" :key="column.key">{{ column.label }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(row, rowIndex) in displayRows" :key="`row-${rowIndex}`">
            <td v-for="column in columns" :key="`${rowIndex}-${column.key}`">{{ formatCell(row[column.key]) }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <small v-if="truncatedCount > 0" class="workflow-preview-table__summary">仅显示前 {{ displayRows.length }} 行，共 {{ rows.length }} 行</small>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

interface PreviewTableColumnView {
  key: string
  label: string
}

type PreviewTableRow = Record<string, unknown>

const props = withDefaults(defineProps<{
  columns: PreviewTableColumnView[]
  rows: PreviewTableRow[]
  emptyText?: string | null
  maxRows?: number
  compact?: boolean
}>(), {
  emptyText: '暂无数据',
  maxRows: 20,
  compact: false,
})

const displayRows = computed(() => props.maxRows > 0 ? props.rows.slice(0, props.maxRows) : props.rows)
const truncatedCount = computed(() => Math.max(props.rows.length - displayRows.value.length, 0))

function formatCell(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—'
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  return JSON.stringify(value)
}
</script>

<style scoped>
.workflow-preview-table {
  display: grid;
  gap: 6px;
  min-height: 0;
  --workflow-preview-table-line: var(--graph-line, rgb(208 220 226 / 0.92));
  --workflow-preview-table-surface: var(--graph-panel, #ffffff);
  --workflow-preview-table-surface-soft: var(--graph-panel-soft, rgb(238 243 245 / 0.96));
  --workflow-preview-table-header-color: var(--graph-text-strong, rgb(23 34 40 / 0.94));
  --workflow-preview-table-cell-color: var(--graph-text, rgb(31 42 48 / 0.9));
  --workflow-preview-table-muted: var(--graph-muted, rgb(96 113 124 / 0.86));
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
