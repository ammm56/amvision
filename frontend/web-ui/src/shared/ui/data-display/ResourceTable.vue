<template>
  <div class="resource-table" :class="{ 'resource-table--embedded': embedded }">
    <table :aria-label="label"><slot /></table>
  </div>
</template>

<script setup lang="ts">
// 沿用资源列表的公共样式；嵌入面板时由面板提供边框，并适配可用宽度。
withDefaults(defineProps<{ label?: string; embedded?: boolean }>(), { embedded: false })
</script>

<style scoped>
.resource-table table { border-collapse: separate; border-spacing: 0; }
.resource-table--embedded { border: 0; border-radius: 0; }
.resource-table--embedded table { min-width: 0; }
.resource-table--embedded :deep(th),
.resource-table--embedded :deep(td) { border-bottom: 0; }
.resource-table :deep(tr.is-clickable) { cursor: pointer; }
.resource-table :deep(tbody tr) { border-radius: var(--am-radius-sm); }
.resource-table :deep(tbody td) { transition: background-color var(--am-motion-fast) var(--am-ease-standard); }
.resource-table :deep(tbody td:first-child) { border-radius: var(--am-radius-sm) 0 0 var(--am-radius-sm); }
.resource-table :deep(tbody td:last-child) { border-radius: 0 var(--am-radius-sm) var(--am-radius-sm) 0; }
.resource-table :deep(tbody tr:hover:not(.is-selected)) { background: transparent; }
.resource-table :deep(tbody tr:hover:not(.is-selected) > td),
.resource-table :deep(tr:has([data-row-action]:focus-visible) > td) { background: var(--am-row-hover); }
.resource-table :deep(tr:has([data-row-action]:focus-visible)) {
  outline: 2px solid var(--am-focus-ring);
  outline-offset: -2px;
}
.resource-table :deep(.resource-table__row-action) {
  display: block;
  width: 100%;
  border: 0;
  padding: 0;
  background: transparent;
  color: var(--am-text-strong);
  font: inherit;
  font-weight: 500;
  text-align: left;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  cursor: pointer;
}
.resource-table :deep(.resource-table__row-action:focus-visible) { outline: none; }
</style>
