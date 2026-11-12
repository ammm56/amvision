<template>
  <div class="transfer-review" :class="{ 'transfer-review--embedded': embedded, 'transfer-review--export': variant === 'export' }">
    <section v-if="$slots.comparison"><slot name="comparison" /></section>
    <details v-else class="transfer-files" :class="{ 'import-file-tree': embedded && variant !== 'export' }" :open="embedded ? roomy : wide">
      <summary>
        <Folder class="tree-heading-icon" :size="16" /><span class="tree-title">{{ fileTitle }}</span>
        <span class="tree-disclosure"><ChevronsRight v-if="embedded && variant !== 'export'" class="rail-chevron" :size="18" /><ChevronRight v-else class="tree-chevron" :size="14" /><span class="when-closed">{{ l('展开', 'Expand') }}</span><span class="when-open">{{ l('收起', 'Collapse') }}</span></span>
      </summary>
      <ResourceTable v-if="variant === 'export'" embedded class="dataset-table planned-table" :label="fileTitle">
        <thead><tr><th>{{ l('名称','Name') }}</th><th>{{ l('类型','Type') }}</th><th>{{ l('文件数','Files') }}</th></tr></thead>
        <tbody><tr v-for="item in visibleRows" :key="item.path"><td :title="item.path">
          <button v-if="item.more" type="button" :aria-label="moreLabel(item)" :title="moreLabel(item)" @click="showMore(item.parent)">…</button>
          <button v-else-if="item.directory && parents.has(item.path)" type="button" :style="{ paddingInlineStart: item.depth * 14 + 'px' }" :aria-expanded="expanded.has(item.path)" @click="toggle(item.path)"><ChevronRight :size="13" :class="{ turned: expanded.has(item.path) }" /><Folder :size="15" /><span>{{ item.name }}</span></button>
          <span v-else class="planned-entry" :style="{ paddingInlineStart: 15 + item.depth * 14 + 'px' }"><component :is="item.directory ? Folder : FileText" :size="15" /><span>{{ item.name }}</span></span>
        </td><td>{{ item.more ? '—' : item.directory ? l('文件夹','Folder') : l('文件','File') }}</td><td>{{ item.more ? '—' : totals.get(item.path)?.toLocaleString() ?? '—' }}</td></tr></tbody>
      </ResourceTable>
      <nav v-else-if="files.length" :aria-label="fileTitle">
        <button v-if="rootLabel" type="button" :title="rootLabel" :aria-expanded="rootOpen" @click="rootOpen = !rootOpen"><ChevronRight :size="14" :class="{ turned: rootOpen }" /><Folder :size="15" /><span>{{ rootLabel }}</span></button>
        <template v-for="item in (rootLabel && !rootOpen ? [] : visibleRows)" :key="item.path">
          <button v-if="item.more" type="button" :aria-label="moreLabel(item)" :title="moreLabel(item)" :style="{ paddingInlineStart: (item.depth + Number(!!rootLabel)) * 14 + 20 + 'px' }" @click="showMore(item.parent)">
            …
          </button>
          <button
            v-else-if="item.directory && parents.has(item.path)"
            type="button"
            :title="item.path"
            :aria-expanded="expanded.has(item.path)"
            :style="{ paddingInlineStart: (item.depth + Number(!!rootLabel)) * 14 + 'px' }"
            @click="toggle(item.path)"
          >
            <ChevronRight
              :size="13"
              :class="{ turned: expanded.has(item.path) }"
            /><Folder :size="15" /><span>{{ item.name }}</span><small v-if="item.count">({{ item.count.toLocaleString() }})</small>
          </button>
          <div
            v-else
            :title="item.path"
            :style="{ paddingInlineStart: (item.depth + Number(!!rootLabel)) * 14 + 20 + 'px' }"
          >
            <component :is="item.directory ? Folder : FileText" :size="15" /><span>{{ item.name }}</span>
          </div>
        </template>
      </nav>
      <p v-else>—</p>
      <small v-if="note">{{ note }}</small>
    </details>
    <section>
      <h3>{{ title }}</h3>
      <slot name="before" />
      <ResourceTable class="dataset-table check-table" :embedded="embedded" :label="title"
        ><thead>
          <tr>
            <th>{{ l('检查项', 'Check') }}</th>
            <th>{{ l('结果', 'Result') }}</th>
            <th>{{ l('详情', 'Details') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in checks" :key="row.name">
            <td><span class="check-name"><component :is="row.state === 'pass' ? CircleCheck : row.state === 'error' ? CircleX : Info" :class="['tone-icon-' + row.state, { 'status-disc': row.state === 'pass' }]" :size="16" />{{ row.name }}</span></td>
            <td>
              <span class="check-state" :class="'tone-' + row.state"
                ><component
                  :is="
                    row.state === 'pass'
                      ? CircleCheck
                      : row.state === 'error'
                        ? CircleX
                        : Info
                  "
                  :class="{ 'status-disc': row.state === 'pass' }"
                  :size="15"
                />{{
                  row.result || (row.state === 'pass'
                    ? l('通过', 'Passed')
                    : row.state === 'error'
                      ? l('阻止', 'Blocked')
                      : l('说明', 'Info'))
                }}</span
              >
            </td>
            <td :title="row.value">{{ row.value }}</td>
          </tr>
        </tbody>
      </ResourceTable>
      <slot />
      <slot v-if="roomy" name="statistics" />
    </section>
    <slot v-if="!roomy" name="statistics" />
  </div>
</template>
<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useMediaQuery } from '@vueuse/core'
import { useI18n } from 'vue-i18n'
import {
  ChevronsRight,
  ChevronRight,
  Folder,
  FileText,
  CircleCheck,
  CircleX,
  Info,
} from '@lucide/vue'
import ResourceTable from '@/shared/ui/data-display/ResourceTable.vue'
const props = defineProps<{
  rootLabel?: string
  files: string[]
  fileTitle: string
  title: string
  variant?: 'export'
  fileCounts?: Record<string, number>
  embedded?: boolean
  note?: string
  checks: { name: string; state: string; value: string; result?: string }[]
}>()
const wide = useMediaQuery('(min-width: 1200px) and (min-height: 800px)')
const roomy = useMediaQuery('(min-width: 1100px) and (min-height: 780px)')
const { locale } = useI18n(),
  l = (zh: string, en: string) => (locale.value.startsWith('zh') ? zh : en)
type TreeRow = { name: string; path: string; parent: string; depth: number; directory: boolean; count: number; more?: number }
const rootOpen = ref(true)
const expanded = ref(new Set<string>())
const rows = computed(() => {
  const entries = new Map<string, TreeRow>()
  for (const file of props.files) {
    const parts = file.split('/').filter(Boolean)
    let path = ''
    for (const [depth, name] of parts.entries()) {
      const parent = path
      path = path ? path + '/' + name : name
      if (!entries.has(path))
        entries.set(path, {
          name,
          path,
          parent,
          count: 0,
          depth,
          directory: depth + 1 < parts.length || file.endsWith('/'),
        })
      if (depth + 1 < parts.length && !file.endsWith('/')) entries.get(path)!.count++
    }
  }
  return [...entries.values()].sort((a, b) => a.path.localeCompare(b.path))
})
watch(
  rows,
  (items) => {
    expanded.value = new Set(
      items
        .filter((item) => item.directory && item.depth < 3)
        .map((item) => item.path),
    )
  },
  { immediate: true },
)
const parents = computed(() => new Set(rows.value.map(row => row.parent)))
const totals = computed(() => {
  const result = new Map<string, number>(), unknown = new Set<string>()
  for (const path of props.files) {
    const count = props.fileCounts?.[path]
    const components = path.split('/').filter(Boolean)
    while (components.length) {
      const key = components.join('/')
      if (count == null) unknown.add(key)
      else result.set(key, (result.get(key) ?? 0) + count)
      components.pop()
    }
  }
  for (const key of unknown) result.delete(key)
  return result
})
const fileLimits = ref(new Map<string, number>())
const visibleRows = computed(() => {
  const visible = rows.value.filter((item) => {
    const parts = item.path.split('/')
    parts.pop()
    while (parts.length) {
      if (!expanded.value.has(parts.join('/'))) return false
      parts.pop()
    }
    return true
  })
  const seen = new Map<string, number>()
  const totals = new Map<string, number>()
  for (const row of visible) if (!row.directory) totals.set(row.parent, (totals.get(row.parent) || 0) + 1)
  return visible.flatMap((row): TreeRow[] => {
    if (row.directory) return [row]
    const index = seen.get(row.parent) || 0
    seen.set(row.parent, index + 1)
    const limit = fileLimits.value.get(row.parent) ?? 3
    if (index < limit) return [row]
    return index === limit ? [{ ...row, more: totals.get(row.parent)! - index }] : []
  })
})
function showMore(parent: string) {
  fileLimits.value.set(parent, (fileLimits.value.get(parent) ?? 3) + 50)
}
function moreLabel(item: TreeRow) {
  return `${l('显示更多文件', 'Show more files')} (${item.more}) · ${item.parent}`
}
function toggle(path: string) {
  if (expanded.value.has(path)) expanded.value.delete(path)
  else expanded.value.add(path)
}
</script>
<style scoped>
.transfer-review {
  display: grid;
  grid-template-columns: minmax(190px, 28%) minmax(0, 1fr);
  gap: 20px;
}
.transfer-review h3,
.transfer-files summary {
  margin: 0 0 12px;
  font-size: 15px;
  font-weight: 600;
}
.transfer-files {
  min-width: 0;
  border-inline-end: 1px solid var(--am-border);
  padding-inline-end: 15px;
}
.transfer-files summary,
.transfer-files nav > * {
  display: flex;
  align-items: center;
  gap: 7px;
}
.transfer-files nav {
  max-height: 44vh;
  overflow: auto;
}
.tree-disclosure { margin-inline-start: auto; display: inline-flex; align-items: center; gap: 4px; color: var(--am-text-muted); font-size: 13px; font-weight: 400; }
.transfer-files[open] .when-closed, .transfer-files:not([open]) .when-open { display: none; }
.check-table .check-name { display: flex; align-items: center; gap: 10px; }
.check-name svg { flex: none; }
.tone-icon-pass { color: var(--am-brand-primary); }
.tone-icon-error { color: var(--am-danger-text); }
.tone-icon-info { color: var(--am-text-muted); }
.check-table .tone-pass svg, .check-name .tone-icon-pass { fill: var(--am-brand-primary); stroke: white; }
.transfer-files nav > * > span { min-width: 0; text-align: start; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.transfer-files nav small { flex: none; white-space: nowrap; font-variant-numeric: tabular-nums; }
.transfer-files summary { list-style: none; }
.transfer-files summary::-webkit-details-marker { display: none; }
.transfer-review--embedded .check-table th:first-child { width: 30%; }
.transfer-review--embedded .check-table th:nth-child(2) { width: 19%; }
.transfer-review--embedded .check-table .check-state { display: inline-flex; align-items: center; }
.transfer-review--embedded .tone-pass { color: var(--am-success-text); }
.transfer-review--embedded .tone-info { color: var(--am-text-muted); }
.transfer-files nav > * {
  width: 100%;
  min-width: 0;
  text-align: start;
  padding: 5px 4px;
  color: inherit;
  overflow-wrap: anywhere;
}
.transfer-files button,
.transfer-files summary {
  cursor: pointer;
}
.transfer-files svg,
.check-state svg {
  flex-shrink: 0;
}
.transfer-files button:hover {
  background: var(--am-surface-soft);
}
.transfer-files small {
  color: var(--am-text-muted);
}
.check-state {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.tone-pass svg {
  color: var(--am-brand-primary);
}
.tone-error {
  color: var(--am-danger-text);
}
@media (max-width: 1199px), (max-height: 799px) {
  .transfer-review {
    grid-template-columns: minmax(0, 1fr);
    gap: 14px;
  }
  .transfer-files {
    border: 0;
  }
  .transfer-files summary {
    margin: 0;
    padding: 8px;
    background: var(--am-surface-soft);
  }
}
.turned,
.transfer-files[open] .tree-chevron {
  transform: rotate(90deg);
}
@media (min-width: 1100px) and (min-height: 780px) {
  .transfer-review--embedded:has(.transfer-files[open]) { grid-template-columns: minmax(180px, 28%) minmax(0, 1fr); }
}
.transfer-review--embedded:has(.transfer-files:not([open])) { grid-template-columns: minmax(0, 1fr); }
@media (min-width: 1024px) {
  .transfer-review--embedded:has(.import-file-tree) { transition: grid-template-columns 180ms var(--am-ease-standard); }
  .transfer-review--embedded:has(.import-file-tree[open]) { grid-template-columns: 28% minmax(0, 1fr); }
  .transfer-review--embedded:has(.import-file-tree:not([open])) { grid-template-columns: 44px minmax(0, 1fr); }
  .import-file-tree { overflow: hidden; }
  .import-file-tree .rail-chevron { transition: transform 180ms var(--am-ease-standard); }
  .import-file-tree[open] .rail-chevron { transform: rotate(180deg); }
  .import-file-tree summary { position: relative; padding: 0; min-height: 28px; }
  .import-file-tree .tree-heading-icon { display: none; }
  .import-file-tree:not([open]) summary { justify-content: center; min-height: 42px; margin: 0; }
  .import-file-tree:not([open]) .tree-disclosure { margin: 0; }
  .import-file-tree .tree-disclosure > span,
  .import-file-tree:not([open]) .tree-title { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); }
  .import-file-tree summary:hover .rail-chevron { color: var(--am-text); }
}
.planned-table th:first-child { width: 57%; }
@media (prefers-reduced-motion: reduce) {
  .transfer-review--embedded:has(.import-file-tree), .import-file-tree .rail-chevron { transition: none; }
}
.planned-table button, .planned-entry { display: inline-flex; align-items: center; gap: 5px; max-width: 100%; background: transparent; color: inherit; border: 0; font: inherit; }
.planned-table td > .planned-entry { display: inline-flex; }
.planned-table svg { flex: none; }
.planned-table td span span, .planned-table button span { overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
@media (min-width: 1100px) and (min-height: 780px) {
  .transfer-review--embedded.transfer-review--export:not(:has(.transfer-files:not([open]))) { grid-template-columns: minmax(0,.94fr) minmax(0,1.06fr); }
}
</style>
