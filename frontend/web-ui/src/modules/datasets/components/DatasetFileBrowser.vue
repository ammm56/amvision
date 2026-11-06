<template>
  <div class="dataset-file-browser">
    <div v-if="error" class="dataset-actions">
      <InlineError :message="error" /><Button @click="selectFolder(folder)">{{
        label('重试', 'Retry')
      }}</Button>
    </div>
    <div class="dataset-file-layout">
      <nav
        class="dataset-file-tree"
        :aria-label="label('版本目录树', 'Version folder tree')"
      >
        <div class="dataset-tree-heading"><h2 class="dataset-tree-title">{{ label('版本资产', 'Version assets') }}</h2><button :title="label('收起目录', 'Collapse folders')" :aria-label="label('收起目录', 'Collapse folders')" @click="expanded = new Set([''])"><ChevronsLeft :size="16" /></button></div>
        <div
          v-for="row in treeRows"
          :key="row.path"
          class="dataset-tree-row"
          :style="{ paddingLeft: `${Math.min(row.depth, 6) * 12}px` }"
          :class="{ 'is-selected': (row.directory ? folder : selectedFile) === row.path }"
        >
          <button
            :aria-expanded="row.leaf ? undefined : expanded.has(row.path)"
            :class="{ 'dataset-tree-leaf': row.leaf }"
            :disabled="row.leaf"
            :aria-hidden="row.leaf || undefined"
            :aria-label="`${expanded.has(row.path) ? label('收起', 'Collapse') : label('展开', 'Expand')} ${row.name}`"
            @click="toggle(row.path)"
          >
            <ChevronDown
              v-if="expanded.has(row.path)"
              :size="14"
            /><ChevronRight v-else :size="14" />
          </button>
          <button
            class="dataset-tree-name"
            :title="row.path || '/'"
            :aria-current="folder === row.path ? 'location' : undefined"
            @click="row.directory ? selectFolder(row.path) : openFile(row)"
          >
            <component :is="row.directory ? Folder : FileText" :size="16" /><span>{{ row.name }}</span>
          </button>
          <button
            v-if="row.more"
            class="dataset-tree-more"
            :title="label('加载更多', 'Load more')"
            @click="loadTree(row.path, true)"
          >
            …
          </button>
        </div>
      </nav>
      <div class="dataset-file-content" :aria-busy="busy" :inert="busy">
    <div class="dataset-toolbar dataset-file-toolbar">
      <Button icon-only :aria-label="label('上一级', 'Parent')" :disabled="!folder" @click="selectFolder(parent)"
        ><ArrowUp :size="16" /></Button
      >
      <span class="dataset-file-path" :title="folder || '/'">{{
        folder || '/'
      }}</span>
    </div>
        <span
          v-if="busy && page.items.length"
          class="dataset-folder-loading"
          role="status"
          >{{ text('loading') }}</span
        >
        <ResourceTable class="dataset-table" :label="text('structure')">
          <thead>
            <tr>
              <th>{{ text('fileName') }}</th>
              <th style="width: 90px">{{ label('类型', 'Type') }}</th>
              <th style="width: 90px">{{ label('大小', 'Size') }}</th>
              <th style="width: 84px">{{ text('actions') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="item in page.items"
              :key="item.path"
              @dblclick="openFile(item)"
            >
              <td>
                <button
                  class="dataset-file-entry"
                  :title="item.name"
                  @click="openFile(item)"
                >
                  <component
                    :is="item.directory ? Folder : FileText"
                    :size="16"
                  /><span>{{ item.name }}</span>
                </button>
              </td>
              <td>{{ item.directory ? label('文件夹', 'Folder') : item.name.split('.').pop()?.toUpperCase() || '—' }}</td>
              <td>
                {{
                  item.size == null
                    ? '—'
                    : `${(item.size / 1024).toFixed(1)} KB`
                }}
              </td>
              <td>
                <Button
                  v-if="canPreview(item)"
                  size="sm"
                  @click="openFile(item)"
                  >{{ text('view') }}</Button
                >
              </td>
            </tr>
          </tbody>
        </ResourceTable>
        <div v-if="!page.items.length && !error" class="dataset-empty" role="status">
          {{ busy ? text('loading') : label('空文件夹', 'Empty folder') }}
        </div>
        <div v-if="page.next_cursor || cursors.length" class="dataset-actions">
          <Button :disabled="busy || !cursors.length" @click="previous">{{
            label('上一页', 'Previous')
          }}</Button
          ><Button :disabled="busy || !page.next_cursor" @click="next">{{
            label('下一页', 'Next')
          }}</Button>
        </div>
      </div>
    </div>
    <SideDrawer
      :open="previewOpen"
      :title="previewName"
      :close-label="text('close')"
      @close="previewOpen = false"
      @after-leave="clearPreview"
    >
      <p v-if="previewBusy" role="status">{{ text('loading') }}</p>
      <InlineError v-if="previewError" :message="previewError" />
      <img
        v-if="imageUrl"
        class="dataset-file-image"
        :src="imageUrl"
        :alt="previewName"
      />
      <p v-if="previewText?.truncated">
        {{ label('仅显示前 256 KB', 'Showing the first 256 KB') }}
      </p>
      <pre v-if="previewText" class="dataset-json">{{
        previewText.content
      }}</pre>
    </SideDrawer>
  </div>
</template>
<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  ArrowUp,
  ChevronDown,
  ChevronsLeft,
  ChevronRight,
  Folder,
  FileText,
} from '@lucide/vue'
import Button from '@/shared/ui/components/Button.vue'
import SideDrawer from '@/shared/ui/components/SideDrawer.vue'
import ResourceTable from '@/shared/ui/data-display/ResourceTable.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import { datasetError, useDatasetText } from '../dataset-workspace'
import {
  getDatasetFiles,
  getDatasetTextFile,
  getDatasetFileImage,
  type DatasetFile,
  type DatasetWorkspace,
} from '../services/dataset-workspace.service'
const props = defineProps<{ workspace: DatasetWorkspace }>()
const text = useDatasetText(),
  { locale } = useI18n()
const label = (zh: string, en: string) =>
  locale.value.startsWith('zh') ? zh : en
type Page = { items: DatasetFile[]; next_cursor: string | null }
const emptyPage = (): Page => ({ items: [], next_cursor: null })
const selectedFile = ref('')
const folder = ref(''),
  after = ref(''),
  cursors = ref<string[]>([]),
  busy = ref(false),
  error = ref('')
const page = ref<Page>(emptyPage()),
  expanded = ref(new Set<string>([''])),
  tree = ref<Record<string, Page>>({})
const pendingPages = new Map<string, Promise<Page>>()
const cache = new Map<string, Page>(),
  treePending = new Set<string>()
let controller = new AbortController(),
  generation = 0,
  selectionGeneration = 0
const parent = computed(() => folder.value.split('/').slice(0, -1).join('/'))
const treeRows = computed(() => {
  const rows: {
    directory: boolean
    size: number | null
    path: string
    name: string
    depth: number
    more: boolean
    leaf: boolean
  }[] = []
  function visit(
    path: string,
    name: string,
    depth: number,
    directory = true,
    hasChildren?: boolean | null,
    size: number | null = null,
  ) {
    rows.push({
      path,
      name,
      directory,
      size,
      depth,
      leaf:
        !directory || hasChildren === false ||
        (!!tree.value[path] &&
          !tree.value[path].items.length &&
          !tree.value[path].next_cursor),
      more: expanded.value.has(path) && !!tree.value[path]?.next_cursor,
    })
    if (expanded.value.has(path))
      for (const child of tree.value[path]?.items || [])
        visit(child.path, child.name, depth + 1, child.directory, child.has_children, child.size)
  }
  visit('', `${props.workspace.dataset?.display_name || text('datasets')} · v${props.workspace.version_number}`, 0)
  return rows
})
// 树与表格读取同一目录时复用请求；已访问页缓存有上限，版本切换统一失效。
function readPage(path: string, after: string): Promise<Page> {
  const key = `${path}\0${after}`, epoch = generation
  const found = cache.get(key)
  if (found) return Promise.resolve(found)
  const pending = pendingPages.get(key)
  if (pending) return pending
  const request = getDatasetFiles(props.workspace.dataset_id, props.workspace.dataset_version_id, path, after, controller.signal)
    .then(result => {
      if (epoch === generation) {
        if (cache.size >= 64) cache.delete(cache.keys().next().value!)
        cache.set(key, result)
      }
      return result
    }).finally(() => { if (pendingPages.get(key) === request) pendingPages.delete(key) })
  pendingPages.set(key, request)
  return request
}
async function loadTree(path: string, more = false) {
  if (treePending.has(path) || (tree.value[path] && !more)) return
  const epoch = generation
  treePending.add(path)
  try {
    const result = await readPage(path, more ? tree.value[path]?.next_cursor || '' : '')
    if (epoch !== generation) return
    tree.value[path] = {
      ...result,
      items: [...(more ? tree.value[path]?.items || [] : []), ...result.items],
    }
  } catch (e) {
    if (epoch === generation && !controller.signal.aborted)
      error.value = datasetError(e)
  } finally {
    if (epoch === generation) treePending.delete(path)
  }
}
function toggle(path: string) {
  const values = new Set(expanded.value)
  if (values.has(path)) values.delete(path)
  else {
    values.add(path)
    void loadTree(path)
  }
  expanded.value = values
}
async function loadPage() {
  const request = ++selectionGeneration,
    epoch = generation,
    key = `${folder.value}\0${after.value}`
  error.value = ''
  if (cache.has(key)) {
    page.value = cache.get(key)!
    busy.value = false
    return
  }
  busy.value = true
  // 保留上一目录的尺寸并暂时阻止操作，避免异步切换时表格反复塌缩。
  try {
    const result = await readPage(folder.value, after.value)
    if (epoch !== generation) return
    if (request === selectionGeneration) page.value = result
  } catch (e) {
    if (
      epoch === generation &&
      request === selectionGeneration &&
      !controller.signal.aborted
    ) {
      page.value = emptyPage()
      error.value = datasetError(e)
    }
  } finally {
    if (epoch === generation && request === selectionGeneration)
      busy.value = false
  }
}
function selectFolder(path: string) {
  selectedFile.value = ''
  folder.value = path
  after.value = ''
  cursors.value = []
  expanded.value = new Set([...expanded.value, path])
  void loadTree(path)
  void loadPage()
}
function next() {
  if (!page.value.next_cursor) return
  cursors.value.push(after.value)
  after.value = page.value.next_cursor
  void loadPage()
}
function previous() {
  after.value = cursors.value.pop() || ''
  void loadPage()
}
const isImage = (item: DatasetFile) =>
  /\.(jpe?g|png|webp|bmp)$/i.test(item.name)
const canPreview = (item: DatasetFile) =>
  item.directory ||
  isImage(item) ||
  /\.(jsonl?|txt|ya?ml|xml|csv)$/i.test(item.name)
const previewOpen = ref(false),
  previewBusy = ref(false),
  previewName = ref(''),
  previewError = ref(''),
  imageUrl = ref('')
const previewText = ref<Awaited<ReturnType<typeof getDatasetTextFile>> | null>(
  null,
)
let previewGeneration = 0
function clearPreview() {
  previewGeneration++
  if (imageUrl.value) URL.revokeObjectURL(imageUrl.value)
  imageUrl.value = ''
  previewText.value = null
}
async function openFile(item: DatasetFile) {
  if (item.directory) {
    selectFolder(item.path)
    return
  }
  if (!canPreview(item)) return
  selectedFile.value = item.path
  clearPreview()
  const request = ++previewGeneration
  previewName.value = item.name
  previewError.value = ''
  previewBusy.value = true
  previewOpen.value = true
  try {
    if (isImage(item)) {
      const blob = await getDatasetFileImage(
        props.workspace.dataset_id,
        props.workspace.dataset_version_id,
        item.path,
        controller.signal,
      )
      if (request === previewGeneration)
        imageUrl.value = URL.createObjectURL(blob)
    } else {
      const result = await getDatasetTextFile(
        props.workspace.dataset_id,
        props.workspace.dataset_version_id,
        item.path,
        controller.signal,
      )
      if (request === previewGeneration) previewText.value = result
    }
  } catch (e) {
    if (request === previewGeneration) previewError.value = datasetError(e)
  } finally {
    if (request === previewGeneration) previewBusy.value = false
  }
}
watch(
  () => props.workspace,
  () => {
    generation++
    controller.abort()
    controller = new AbortController()
    cache.clear()
    pendingPages.clear()
    treePending.clear()
    tree.value = {}
    expanded.value = new Set([''])
    previewOpen.value = false
    clearPreview()
    selectFolder('')
  },
  { immediate: true },
)
onBeforeUnmount(() => {
  generation++
  controller.abort()
  clearPreview()
})
</script>
<style scoped>
.dataset-file-browser,
.dataset-file-content {
  display: grid;
  gap: 16px;
  min-width: 0;
  align-content: start;
}
.dataset-file-layout {
  display: grid;
  grid-template-columns: 280px minmax(0, 1fr);
  gap: 16px;
  min-height: 520px;
}
.dataset-file-content {
  position: relative;
}

.dataset-folder-loading {
  position: absolute;
  top: 70px;
  left: 0;
  right: 0;
  text-align: center;
  z-index: 1;
}
.dataset-file-tree {
  padding: 68px 12px 16px;
  border: 1px solid var(--am-border);
  border-radius: var(--am-radius-md);
  background: var(--am-surface);
  align-self: stretch;
  min-height: 520px;
  min-width: 0;
}
.dataset-tree-title { margin: 6px 8px 12px; font-size: 14px; font-weight: 600; }
.dataset-tree-row {
  display: flex;
  align-items: center;
  border-radius: var(--am-radius-sm);
  min-width: 0;
}
.dataset-tree-row:hover {
  background: var(--am-hover-surface);
}
.dataset-tree-row.is-selected {
  background: var(--am-row-selected);
  color: var(--am-brand-primary);
}
.dataset-tree-row button,
.dataset-file-entry {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 9px 4px;
  border: 0;
  color: inherit;
  background: transparent;
  cursor: pointer;
  min-width: 0;
  text-align: left;
}
.dataset-tree-leaf {
  visibility: hidden;
}
.dataset-tree-name {
  flex: 1;
}
.dataset-tree-name span,
.dataset-file-entry span,
.dataset-file-path {
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
  min-width: 0;
}
.dataset-tree-row svg,
.dataset-file-entry svg {
  flex-shrink: 0;
}
.dataset-file-path {
  flex: 1;
  font-size: 13px;
  color: var(--am-text-muted);
}
.dataset-file-entry {
  width: 100%;
  padding: 0;
}
.dataset-file-image {
  display: block;
  max-width: 100%;
  max-height: 70vh;
  object-fit: contain;
  margin: auto;
}
@media (max-width: 1200px) {
  .dataset-file-layout {
    grid-template-columns: 220px minmax(0, 1fr);
  }
}
</style>

<style scoped>
.dataset-tree-heading { display:flex; align-items:center; justify-content:space-between; padding:4px 4px 12px; }
.dataset-tree-heading .dataset-tree-title { margin:0; }
.dataset-tree-heading > button { display:grid; place-items:center; background:none; border:0; color:var(--am-text-muted); padding:4px; cursor:pointer; border-radius:var(--am-radius-sm); }
.dataset-tree-heading > button:hover { background:var(--am-hover-surface); }
.dataset-file-toolbar { padding:8px 12px; background:var(--am-surface); border:1px solid var(--am-border); border-radius:var(--am-radius-md); }
.dataset-file-tree { max-height:680px; overflow-y:auto; }
</style>
