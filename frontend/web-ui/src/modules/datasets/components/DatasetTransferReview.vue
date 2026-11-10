<template>
  <div class="transfer-review">
    <section v-if="$slots.comparison"><slot name="comparison" /></section>
    <details v-else class="transfer-files" :open="wide">
      <summary>
        <ChevronRight class="tree-chevron" :size="14" /><Folder :size="16" />{{
          fileTitle
        }}
      </summary>
      <nav v-if="files.length" :aria-label="fileTitle">
        <template v-for="item in visibleRows" :key="item.path">
          <button
            v-if="item.directory"
            type="button"
            :title="item.path"
            :aria-expanded="expanded.has(item.path)"
            :style="{ paddingInlineStart: item.depth * 12 + 'px' }"
            @click="toggle(item.path)"
          >
            <ChevronRight
              :size="13"
              :class="{ turned: expanded.has(item.path) }"
            /><Folder :size="15" />{{ item.name }}
          </button>
          <div
            v-else
            :title="item.path"
            :style="{ paddingInlineStart: item.depth * 12 + 16 + 'px' }"
          >
            <FileText :size="15" />{{ item.name }}
          </div>
        </template>
      </nav>
      <p v-else>—</p>
      <small v-if="note">{{ note }}</small>
    </details>
    <section>
      <h3>{{ title }}</h3>
      <ResourceTable class="dataset-table" :label="title"
        ><thead>
          <tr>
            <th>{{ l('检查项', 'Check') }}</th>
            <th>{{ l('状态', 'Status') }}</th>
            <th>{{ l('说明', 'Details') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in checks" :key="row.name">
            <td>{{ row.name }}</td>
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
                  :size="15"
                />{{
                  row.state === 'pass'
                    ? l('通过', 'Passed')
                    : row.state === 'error'
                      ? l('阻止', 'Blocked')
                      : l('说明', 'Info')
                }}</span
              >
            </td>
            <td :title="row.value">{{ row.value }}</td>
          </tr>
        </tbody>
      </ResourceTable>
      <slot />
    </section>
  </div>
</template>
<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useMediaQuery } from '@vueuse/core'
import { useI18n } from 'vue-i18n'
import {
  ChevronRight,
  Folder,
  FileText,
  CircleCheck,
  CircleX,
  Info,
} from '@lucide/vue'
import ResourceTable from '@/shared/ui/data-display/ResourceTable.vue'
const props = defineProps<{
  files: string[]
  fileTitle: string
  title: string
  note?: string
  checks: { name: string; state: string; value: string }[]
}>()
const wide = useMediaQuery('(min-width: 1200px) and (min-height: 800px)')
const { locale } = useI18n(),
  l = (zh: string, en: string) => (locale.value.startsWith('zh') ? zh : en)
type TreeRow = { name: string; path: string; depth: number; directory: boolean }
const expanded = ref(new Set<string>())
const rows = computed(() => {
  const entries = new Map<string, TreeRow>()
  for (const file of props.files) {
    const parts = file.split('/').filter(Boolean)
    let path = ''
    for (const [depth, name] of parts.entries()) {
      path = path ? path + '/' + name : name
      if (!entries.has(path))
        entries.set(path, {
          name,
          path,
          depth,
          directory: depth + 1 < parts.length || file.endsWith('/'),
        })
    }
  }
  return [...entries.values()].sort((a, b) => a.path.localeCompare(b.path))
})
watch(
  rows,
  (items) => {
    expanded.value = new Set(
      items
        .filter((item) => item.directory && item.depth < 2)
        .map((item) => item.path),
    )
  },
  { immediate: true },
)
const visibleRows = computed(() =>
  rows.value.filter((item) => {
    const parts = item.path.split('/')
    parts.pop()
    while (parts.length) {
      if (!expanded.value.has(parts.join('/'))) return false
      parts.pop()
    }
    return true
  }),
)
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
.transfer-files nav > * {
  max-width: 100%;
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
</style>
