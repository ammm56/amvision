<template>
  <Teleport to="body">
    <div v-if="open && table" class="workflow-preview-table-viewer" @click.self="emit('close')">
      <div class="workflow-preview-table-viewer__panel" role="dialog" aria-modal="true">
        <div class="workflow-preview-table-viewer__toolbar">
          <div class="workflow-preview-table-viewer__title">
            <strong>{{ table.title }}</strong>
            <span>{{ table.columns.length }} 列 / {{ table.rowCount ?? table.rows.length }} 行</span>
          </div>
          <Button size="sm" variant="secondary" type="button" title="关闭" aria-label="关闭表格查看器" @click="emit('close')">
            <X :size="17" />
          </Button>
        </div>
        <div class="workflow-preview-table-viewer__viewport">
          <WorkflowPreviewTable
            :columns="table.columns"
            :rows="table.rows"
            :empty-text="table.emptyText"
            :max-rows="0"
          />
        </div>
        <div class="workflow-preview-table-viewer__status">
          <span>已加载 {{ table.rows.length }} 行</span>
          <span>总计 {{ table.rowCount ?? table.rows.length }} 行</span>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { X } from '@lucide/vue'

import Button from '@/shared/ui/components/Button.vue'

import WorkflowPreviewTable from './WorkflowPreviewTable.vue'

interface PreviewTableColumnView {
  key: string
  label: string
}

type PreviewTableRow = Record<string, unknown>

interface PreviewTableView {
  title: string
  columns: PreviewTableColumnView[]
  rows: PreviewTableRow[]
  rowCount: number | null
  emptyText?: string | null
}

defineProps<{
  open: boolean
  table: PreviewTableView | null
}>()

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
  border: 1px solid rgb(255 255 255 / 0.14);
  border-radius: 12px;
  overflow: hidden;
  color: #eef3f6;
  background: #1d2225;
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
  background: #1d2225;
}

.workflow-preview-table-viewer__toolbar {
  border-bottom: 1px solid rgb(255 255 255 / 0.14);
}

.workflow-preview-table-viewer__status {
  border-top: 1px solid rgb(255 255 255 / 0.14);
  color: #b9c6cc;
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
  color: #b9c6cc;
  font-size: 12px;
}

.workflow-preview-table-viewer__viewport {
  min-width: 0;
  min-height: 0;
  padding: 12px;
  overflow: hidden;
  background: #161a1d;
}

.workflow-preview-table-viewer__viewport :deep(.workflow-preview-table) {
  height: 100%;
}

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