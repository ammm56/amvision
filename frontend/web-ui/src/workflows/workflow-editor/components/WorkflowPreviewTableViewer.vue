<template>
  <Teleport to="body">
    <div v-if="open && table" class="workflow-preview-table-viewer" @click.self="emit('close')">
      <div class="workflow-preview-table-viewer__panel" role="dialog" aria-modal="true">
        <div class="workflow-preview-table-viewer__toolbar">
          <div class="workflow-preview-table-viewer__title">
            <strong>{{ table.title }}</strong>
            <span>{{ t('workflowEditor.editor.tableDimensions', { columns: table.columns.length, rows: table.rowCount ?? table.rows.length }) }}</span>
          </div>
          <Button size="sm" variant="secondary" type="button" :title="t('common.close')" :aria-label="t('workflowEditor.editor.closeTableViewer')" @click="emit('close')">
            <X :size="17" />
          </Button>
        </div>
        <div class="workflow-preview-table-viewer__viewport">
          <WorkflowPreviewTable
            :columns="table.columns"
            :rows="table.rows"
            :empty-text="table.emptyText"
            :max-rows="0"
            selectable :selected-index="selected" @select="selected=$event"
          />
          <details v-if="selected!==null && table.rows[selected]"><summary>JSON</summary><pre>{{ JSON.stringify(table.rows[selected],null,2) }}</pre></details>
        </div>
        <div class="workflow-preview-table-viewer__status">
          <span>{{ t('workflowEditor.editor.loadedRows', { count: table.rows.length }) }}</span>
          <span>{{ t('workflowEditor.editor.totalRows', { count: table.rowCount ?? table.rows.length }) }}</span>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { X } from '@lucide/vue'
import { useTranslation } from '@/platform/i18n'
import {ref,watch} from 'vue'
import type {ResultColumn as PreviewTableColumnView} from '@/shared/ui/image-viewer/result-format'

import Button from '@/shared/ui/components/Button.vue'

import WorkflowPreviewTable from './WorkflowPreviewTable.vue'

const { t } = useTranslation()

type PreviewTableRow = Record<string, unknown>

interface PreviewTableView {
  title: string
  columns: PreviewTableColumnView[]
  rows: PreviewTableRow[]
  rowCount: number | null
  emptyText?: string | null
}

const props=defineProps<{
  open: boolean
  table: PreviewTableView | null
}>()
const selected=ref<number|null>(null)
watch(()=>props.table,()=>{selected.value=null})

const emit = defineEmits<{
  close: []
}>()
</script>

<style scoped>
.workflow-preview-table-viewer {
  position: fixed;
  inset: 0;
  z-index: 80;
  display: grid;
  padding: 24px;
  background: rgb(13 16 18 / 0.92);
}

.workflow-preview-table-viewer__panel {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr) auto;
  min-width: 0;
  min-height: 0;
  border: 1px solid var(--am-border);
  border-radius: 12px;
  overflow: hidden;
  color: var(--am-text);
  background: var(--am-surface);
  box-shadow: 0 18px 40px rgb(0 0 0 / 0.34);
}

.workflow-preview-table-viewer__toolbar,
.workflow-preview-table-viewer__status {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  min-width: 0;
  padding: 10px 12px;
  background: var(--am-surface);
}

.workflow-preview-table-viewer__toolbar {
  border-bottom: 1px solid var(--am-border);
}

.workflow-preview-table-viewer__status {
  border-top: 1px solid var(--am-border);
  color: var(--am-text-muted);
  font-size: 12px;
}

.workflow-preview-table-viewer__title {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.workflow-preview-table-viewer__title strong,
.workflow-preview-table-viewer__title span,
.workflow-preview-table-viewer__status span {
  overflow-wrap: anywhere;
}

.workflow-preview-table-viewer__title span {
  color: var(--am-text-muted);
  font-size: 12px;
}

.workflow-preview-table-viewer__viewport {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
  min-height: 0;
  padding: 12px;
  overflow: hidden;
  background: var(--am-surface-soft);
}

.workflow-preview-table-viewer__viewport :deep(.workflow-preview-table) {
  flex: 1;
  min-height: 0;
}

.workflow-preview-table-viewer__viewport details { flex: 0 0 auto; max-height: 30%; overflow: auto; }
.workflow-preview-table-viewer__viewport pre { white-space: pre-wrap; overflow-wrap: anywhere; }

.workflow-preview-table-viewer__viewport :deep(.workflow-preview-table__scroller) {
  height: 100%;
  max-height: none;
}

@media (max-width: 900px) {
  .workflow-preview-table-viewer {
    padding: 12px;
  }

  .workflow-preview-table-viewer__toolbar,
  .workflow-preview-table-viewer__status {
    flex-wrap: wrap;
  }
}
</style>
