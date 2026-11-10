<template>
  <section class="resource-section dataset-record-files">
    <h2>
      {{
        cleaned
          ? l('历史文件清单', 'Historical files')
          : l('导出文件结构', 'Export file structure')
      }}
    </h2>
    <InlineError v-if="error" :message="error" /><Button
      v-if="error"
      @click="load(failedPath)"
      >{{ l('重试', 'Retry') }}</Button
    >
    <ResourceTable class="dataset-table" :label="l('文件清单', 'Files')">
      <thead>
        <tr>
          <th width="48%">{{ l('文件名', 'Name') }}</th>
          <th>{{ l('类型', 'Type') }}</th>
          <th>{{ l('大小', 'Size') }}</th>
          <th>{{ l('状态', 'Status') }}</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="row.key">
          <template v-if="row.file"
            ><td
              :style="{ paddingInlineStart: 12 + row.depth * 16 + 'px' }"
              :title="row.file.path"
            >
              <button
                v-if="row.file.directory && !cleaned"
                type="button"
                class="tree-entry"
                :aria-expanded="expanded.has(row.file.path)"
                @click="toggle(row.file.path)"
              >
                <ChevronRight
                  :size="14"
                  :class="{ turned: expanded.has(row.file.path) }"
                /><Folder :size="16" /><span>{{ row.file.name }}</span>
              </button>
              <button
                v-else-if="
                  !cleaned &&
                  /\.(json|txt|xml|yaml|yml|csv|jsonl)$/i.test(row.file.name)
                "
                type="button"
                class="tree-entry"
                @click="$emit('preview', row.file)"
              >
                <FileText :size="16" /><span>{{ row.file.name }}</span>
              </button>
              <span v-else class="tree-entry"
                ><component
                  :is="row.file.directory ? Folder : FileText"
                  :size="16"
                /><span>{{ row.file.name }}</span></span
              >
            </td>
            <td>
              {{
                row.file.directory
                  ? l('目录', 'Directory')
                  : row.file.name.split('.').at(-1)?.toUpperCase()
              }}
            </td>
            <td>{{ row.file.directory ? '—' : formatBytes(row.file.size) }}</td>
            <td>
              <span class="file-state" :class="{ cleaned }"
                ><component
                  :is="cleaned ? TriangleAlert : CircleCheck"
                  :size="14"
                />{{
                  cleaned ? l('已清理', 'Cleaned') : l('可用', 'Available')
                }}</span
              >
            </td></template
          >
          <td v-else colspan="4">
            <Button
              size="sm"
              :loading="pending.has(row.folder)"
              @click="load(row.folder)"
              >{{ l('显示更多', 'Show more') }}</Button
            >
          </td>
        </tr>
      </tbody>
    </ResourceTable>
    <small v-if="cleaned && !history.length">{{
      l(
        '此记录未保存历史文件清单',
        'No historical list was saved for this record',
      )
    }}</small>
    <small v-if="cleaned && truncated">{{
      l('仅保留前 100 个顶层条目', 'First 100 top-level entries retained')
    }}</small>
  </section>
</template>
<script setup lang="ts">
import { computed, ref, onMounted, onBeforeUnmount } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  Folder,
  FileText,
  ChevronRight,
  CircleCheck,
  TriangleAlert,
} from '@lucide/vue'
import { apiRequest } from '@/shared/api/http-client'
import Button from '@/shared/ui/components/Button.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import ResourceTable from '@/shared/ui/data-display/ResourceTable.vue'
import { datasetError } from '../dataset-workspace'
import type { DatasetFile } from '../services/dataset-workspace.service'
const props = defineProps<{
  id: string
  cleaned: boolean
  history: DatasetFile[]
  truncated: boolean
  formatBytes: (n: number | null) => string
}>()
defineEmits<{ preview: [file: DatasetFile] }>()
const { locale } = useI18n(),
  l = (zh: string, en: string) => (locale.value.startsWith('zh') ? zh : en)
type Page = { items: DatasetFile[]; next_cursor: string | null }
const pages = ref(new Map<string, Page>()),
  expanded = ref(new Set<string>()),
  pending = ref(new Set<string>()),
  controller = new AbortController(),
  error = ref(''),
  failedPath = ref('')
const rows = computed(() => {
  const list: {
    key: string
    folder: string
    depth: number
    file?: DatasetFile
  }[] = []
  function append(folder: string, depth: number) {
    const page = pages.value.get(folder)
    for (const file of props.cleaned ? props.history : page?.items || []) {
      list.push({ key: 'file:' + file.path, folder, depth, file })
      if (!props.cleaned && file.directory && expanded.value.has(file.path))
        append(file.path, depth + 1)
    }
    if (!props.cleaned && page?.next_cursor)
      list.push({ key: 'page:' + folder, folder, depth })
  }
  append('', 0)
  return list
})
async function load(folder: string) {
  if (props.cleaned || pending.value.has(folder)) return
  error.value = ''
  pending.value.add(folder)
  const previous = pages.value.get(folder)
  try {
    const page = await apiRequest<Page>(
      '/datasets/exports/' + encodeURIComponent(props.id) + '/files',
      {
        query: { path: folder, after: previous?.next_cursor || '' },
        signal: controller.signal,
      },
    )
    if (!controller.signal.aborted)
      pages.value.set(folder, {
        items: [...(previous?.items || []), ...page.items],
        next_cursor: page.next_cursor,
      })
  } catch (e) {
    if (!controller.signal.aborted) {
      failedPath.value = folder
      error.value = datasetError(e)
    }
  } finally {
    pending.value.delete(folder)
  }
}
function toggle(path: string) {
  if (expanded.value.has(path)) expanded.value.delete(path)
  else {
    expanded.value.add(path)
    if (!pages.value.has(path)) void load(path)
  }
}
onMounted(() => load(''))
onBeforeUnmount(() => controller.abort())
</script>
<style scoped>
.tree-entry,
.file-state {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  max-width: 100%;
  color: inherit;
}
.tree-entry svg {
  flex-shrink: 0;
}
.tree-entry span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
button.tree-entry {
  cursor: pointer;
  padding: 4px;
  border-radius: 4px;
}
button.tree-entry:hover {
  background: var(--am-surface-muted);
}
.turned {
  transform: rotate(90deg);
}
.file-state svg {
  color: var(--am-success-icon);
}
.file-state.cleaned svg {
  color: var(--am-warning-icon);
}
</style>
