<template>
  <section class="dataset-workspace dataset-catalog">
    <div class="dataset-heading">
      <div class="dataset-tabs" role="tablist">
        <button
          v-for="item in tabs"
          :key="item"
          role="tab"
          :aria-selected="tab === item"
          @click="changeTab(item)"
        >
          {{ text(item) }}
        </button>
      </div>
      <Button
        v-if="canWrite"
        variant="primary"
        @click="router.push(tab === 'exports' ? '/datasets/export' : '/datasets/import')"
        ><Download v-if="tab === 'exports'" :size="16" /><Upload v-else :size="16" />{{ text(tab === 'exports' ? 'export' : 'import') }}</Button
      >
    </div>
    <div class="dataset-toolbar">
      <form class="input-with-icon dataset-search" @submit.prevent="search">
        <Search :size="18" /><input
          v-model="q"
          :aria-label="text('search')"
          :placeholder="text(tab === 'imports' || tab === 'exports' ? 'searchRecords' : 'searchName')"
          @input="scheduleSearch"
        />
      </form>
      <label
        v-if="tab === 'datasets' || tab === 'versions'"
        class="dataset-filter"
        ><span>{{ text('task') }}</span
        ><SelectField
          v-model="taskType"
          :options="taskOptions"
          @update:model-value="search" /></label
      ><label class="dataset-filter"
        ><span>{{ text(tab === 'datasets' || tab === 'versions' ? 'state' : 'status') }}</span
        ><SelectField
          v-model="availability"
          :options="stateOptions"
          @update:model-value="search" /></label
      ><label v-if="tab === 'imports'" class="dataset-filter"><span>{{ text('timeRange') }}</span><SelectField v-model="period" :options="periodOptions" @update:model-value="search" /></label>
      <label v-if="tab === 'exports'" class="dataset-filter"><span>{{ text('fileState') }}</span><SelectField v-model="fileState" :options="fileOptions" @update:model-value="search" /></label>
      <Button :loading="loading" @click="load"
        ><RefreshCw :size="16" />{{ text('refresh') }}</Button
      >
    </div>
    <InlineError v-if="error" :message="error" />
    <ResourceCleanupPanel
      v-if="project.selectedProjectId && canWrite"
      :project-id="project.selectedProjectId"
      @settled="load"
    />
    <ResourceTable
      v-if="rows.length"
      :aria-busy="loading"
      :inert="rowsTab !== tab"
      class="dataset-table dataset-catalog-table"
      :class="`dataset-catalog-table--${rowsTab}`"
      :label="text(rowsTab)"
    >
      <colgroup v-if="rowsTab === 'datasets'">
        <col class="catalog-col-name" />
        <col class="catalog-col-task" />
        <col class="catalog-col-version" />
        <col class="catalog-col-samples" />
        <col class="catalog-col-split" />
        <col class="catalog-col-time" />
        <col class="catalog-col-actions" />
      </colgroup>
      <colgroup v-else>
        <col class="record-col-name" />
        <col class="record-col-primary" />
        <col class="record-col-secondary" />
        <col v-if="rowsTab !== 'exports'" class="record-col-samples" />
        <col class="record-col-source" />
        <col v-if="rowsTab === 'exports'" class="record-col-file" />
        <col class="record-col-time" />
        <col v-if="rowsTab === 'versions'" class="record-col-state" />
        <col class="catalog-col-actions" />
      </colgroup>
      <thead>
        <tr>
          <th scope="col" class="dataset-name-column">{{ text(rowsTab === 'versions' ? 'datasets' : rowsTab === 'imports' ? 'targetDataset' : rowsTab === 'exports' ? 'sourceDataset' : 'name') }}</th>
          <th scope="col" :class="{ 'dataset-version-cell': rowsTab === 'versions' || rowsTab === 'exports' }">
            {{
              text(
                rowsTab === 'datasets'
                  ? 'taskColumn'
                  : rowsTab === 'versions'
                    ? 'version'
                    : rowsTab === 'imports' ? 'sourcePackage' : 'version',
              )
            }}
          </th>
          <th scope="col" :class="{ 'dataset-version-cell': rowsTab === 'datasets' }">
            {{
              text(
                rowsTab === 'datasets'
                  ? 'version'
                  : rowsTab === 'versions'
                    ? 'taskColumn'
                    : rowsTab === 'imports' ? 'status' : 'format',
              )
            }}
          </th>
          <th v-if="rowsTab !== 'exports'" scope="col">
            {{ text('samples') }}<template v-if="rowsTab === 'datasets'"> / {{ text('classes') }}</template>
          </th>
          <th v-if="rowsTab === 'datasets'" scope="col">{{ text('splits') }}</th>
          <th v-else scope="col">{{ text(rowsTab === 'versions' ? 'source' : rowsTab === 'imports' ? 'importedVersion' : 'status') }}</th>
          <th v-if="rowsTab === 'exports'" scope="col">{{ text('file') }}</th>
          <th scope="col" class="dataset-time-column">
            {{ text(rowsTab === 'datasets' ? 'updated' : rowsTab === 'imports' ? 'submitted' : 'created') }}
          </th>
          <th v-if="rowsTab === 'versions'" scope="col">{{ text('status') }}</th>
          <th scope="col" class="dataset-action-column">{{ text('actions') }}</th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="row in rows"
          :key="rowId(row)"
          :class="{
            'is-selected': selected === rowId(row),
            'is-clickable': true,
          }"
          @click="selected = rowId(row)"
        >
          <td>
            <strong :title="rowName(row)">{{ rowName(row) }}</strong>
          </td>
          <template v-if="isDataset(row)"
            ><td :title="row.task_type">{{ isMediaTask(row.task_type) ? text(row.task_type) : row.task_type }}</td>
            <td class="dataset-version-cell">
              <span :title="row.latest_version?.dataset_version_id">{{
                row.latest_version
                  ? `v${row.latest_version.version_number}`
                  : text('emptyVersion')
              }}</span>
            </td>
            <td><DatasetCounts :items="sampleColumns(row.latest_version?.sample_count, row.latest_version?.category_count)" summary /></td>
            <td><DatasetCounts :items="splitColumns(row.latest_version?.split_counts)" summary /></td>
          </template>
          <template v-else-if="isVersion(row)"
            ><td class="dataset-version-cell">
              <span :title="row.dataset_version_id">{{
                `v${row.version_number}`
              }}</span>
            </td>
            <td :title="text(row.task_type)">{{ isMediaTask(row.task_type) ? text(row.task_type) : row.task_type }}</td>
            <td><DatasetCounts :items="sampleColumns(row.sample_count, null).slice(0, 1)" summary /></td>
            <td :title="versionSource(row)">{{ versionSource(row) }}</td></template
          >
          <template v-else-if="'dataset_import_id' in row">
            <td :title="row.source_file_name || ''">{{ row.source_file_name || '—' }}</td>
            <td class="dataset-record-status"><TaskStateBadge :state="row.status" appearance="icon" /></td>
            <td><DatasetCounts :items="sampleColumns(row.sample_count, null).slice(0, 1)" summary /></td>
            <td class="dataset-version-cell"><Button v-if="row.version_number && row.dataset_version_id" size="sm" variant="ghost" class="dataset-catalog-view" @click.stop="openRecordVersion(row)">{{ `v${row.version_number}` }}</Button><span v-else>—</span></td>
          </template>
          <template v-else>
            <td class="dataset-version-cell">{{ row.version_number ? `v${row.version_number}` : '—' }}</td>
            <td :title="row.format_id">{{ row.format_id }}</td>
            <td class="dataset-record-status"><TaskStateBadge :state="row.status" appearance="icon" /></td>
            <td :title="[exportFileLabel(row), row.package_file_name].filter(Boolean).join('\n')">{{ exportFileLabel(row) }}</td>
          </template>
          <td
            :title="
              datasetDate('updated_at' in row ? row.updated_at : row.created_at)
            "
          >
            {{
              datasetDate('updated_at' in row ? row.updated_at : row.created_at)
            }}
          </td>
          <td v-if="isVersion(row)" class="dataset-availability" :title="text(`availabilityReason_${row.availability?.reason || 'unchecked'}`)">
            <StatusBadge with-dot :status="row.availability?.state || 'unknown'" :label="text(`versionState_${row.availability?.state || 'unknown'}`)" />
          </td>
          <td @click.stop>
            <div class="dataset-actions">
              <Button
                size="sm"
                variant="ghost"
                class="dataset-catalog-view"
                :disabled="isDataset(row) && !row.latest_version"
                @click="view(row)"
                >{{
                  text(isDataset(row) || isVersion(row) ? 'view' : 'details')
                }}</Button
              ><Button v-if="isExport(row) && canDownload(row)" size="sm" variant="ghost" class="dataset-record-download" :loading="downloading === row.dataset_export_id" :disabled="!!downloading" @click="downloadRow(row)"><Download :size="14" />{{ text('download') }}</Button><ResourceMenu
                :label="text('more')"
                :items="menu(row)"
                @action="action($event, row)"
              />
            </div>
          </td>
        </tr>
      </tbody>
    </ResourceTable>
    <div v-else-if="!error" class="dataset-empty">
      <Database :size="32" />
      <p>
        {{
          text(
            loading
              ? 'loading'
              : q || taskType || availability || period || fileState
                ? 'noMatches'
                : tab === 'imports' || tab === 'exports' ? 'noRecords' : 'noData',
          )
        }}
      </p>
      <Button v-if="q || taskType || availability || period || fileState" @click="clearFilters">{{
        text('clear')
      }}</Button>
    </div>
    <PaginationControls
      v-if="total > limit || offset > 0"
      :offset="offset"
      :limit="limit"
      :item-count="rows.length"
      :total-count="total"
      :disabled="loading"
      @previous="page(-limit)"
      @next="page(limit)"
    />
    <DatasetInfoDrawer
      v-if="drawer"
      :key="drawer.info.dataset_id"
      v-bind="drawer"
      :editable="canWrite"
      @close="drawer = null"
      @saved="afterSaved"
    />
    <DatasetRecordConfirm v-if="removal && ('dataset_import_id' in removal || 'dataset_export_id' in removal)" :importing="'dataset_import_id' in removal" :clean="cleanupOnly" :name="rowName(removal)" :version="removal.version_number ? 'v'+removal.version_number : undefined" :file="'dataset_import_id' in removal ? removal.source_file_name : removal.package_file_name" :busy="deleting" @confirm="remove" @cancel="removal = null" />
    <ConfirmDialog
      v-else-if="removal"
      :title="text(cleanupOnly ? 'cleanup' : 'remove')"
      :message="deleteMessage"
      :confirm-label="text(cleanupOnly ? 'cleanup' : 'remove')"
      :cancel-label="text('cancel')"
      :busy="deleting"
      @confirm="remove"
      @cancel="removal = null"
    />
  </section>
</template>
<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  Database,
  Download,
  Info,
  Pencil,
  RefreshCw,
  Search,
  Trash2,
  Upload,
} from '@lucide/vue'
import { useProjectStore } from '@/app/stores/project.store'
import { useSessionStore } from '@/app/stores/session.store'
import { useFeedbackStore } from '@/app/stores/feedback.store'
import Button from '@/shared/ui/components/Button.vue'
import SelectField from '@/shared/ui/components/Select.vue'
import ResourceMenu from '@/shared/ui/components/ResourceMenu.vue'
import {isMediaTask} from '../sample-media'
import ResourceTable from '@/shared/ui/data-display/ResourceTable.vue'
import TaskStateBadge from '@/modules/tasks/components/TaskStateBadge.vue'
import StatusBadge from '@/shared/ui/data-display/StatusBadge.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import PaginationControls from '@/shared/ui/components/PaginationControls.vue'
import ConfirmDialog from '@/shared/ui/components/ConfirmDialog.vue'
import DatasetRecordConfirm from '../components/DatasetRecordConfirm.vue'
import ResourceCleanupPanel from '@/shared/ui/components/ResourceCleanupPanel.vue'
import DatasetInfoDrawer from '../components/DatasetInfoDrawer.vue'
import DatasetCounts from '../components/DatasetCounts.vue'
import { useDatasetCounts } from '../dataset-counts'
import { datasetDate, datasetError, useDatasetText } from '../dataset-workspace'
import {
  listDatasetCatalog,
  listDatasetVersionPage,
  listDatasetRecordPage,
  getDatasetInfo,
  type DatasetItem,
  type DatasetVersion,
  type DatasetInfo,
} from '../services/dataset-workspace.service'
import {
  deleteDatasetImport,
  deleteDatasetExport,
  downloadDatasetExport,
  type DatasetImportSummary,
  type DatasetExportSummary,
} from '../services/dataset.service'
import { submitResourceDeletion } from '@/shared/api/resource-deletion'
import '../dataset-workspace.css'
const tabs = ['datasets', 'versions', 'imports', 'exports'] as const
type Tab = (typeof tabs)[number]
type Row =
  DatasetItem | DatasetVersion | DatasetImportSummary | DatasetExportSummary
const router = useRouter(),
  route = useRoute(),
  project = useProjectStore(),
  session = useSessionStore(),
  text = useDatasetText()
const tab = ref<Tab>('datasets'),
  rowsTab = ref<Tab>('datasets'),
  q = ref(''),
  taskType = ref(''),
  availability = ref(''),
  offset = ref(0),
  limit = 20,
  total = ref(0),
  rows = ref<Row[]>([]),
  loading = ref(false),
  error = ref(''),
  selected = ref(''),
  drawer = ref<{ mode: 'info' | 'edit'; info: DatasetInfo } | null>(null),
  removal = ref<Row | null>(null),
  deleting = ref(false)
const canWrite = computed(() => session.hasScopes(['datasets:write']))
const feedback = useFeedbackStore()
const period = ref(''), fileState = ref(''), downloading = ref('')
const periodOptions = computed(() => [{ value: '', label: text('all') }, { value: '7', label: text('last7Days') }, { value: '30', label: text('last30Days') }])
const fileOptions = computed(() => [{ value: '', label: text('all') }, ...Object.entries({ ready: 'fileReady', generating: 'fileGenerating', not_generated: 'fileNotGenerated', cleaned: 'cleaned' }).map(([value, key]) => ({ value, label: text(key) }))])
const isExport = (row: Row): row is DatasetExportSummary => 'dataset_export_id' in row
const canDownload = (row: DatasetExportSummary) => row.status === 'completed' && !row.metadata.files_cleaned_at
function exportFileLabel(row: DatasetExportSummary) {
  if (row.metadata.files_cleaned_at) return text('cleaned')
  if (row.status !== 'completed') return text(['queued', 'running'].includes(row.status) ? 'fileGenerating' : 'fileNotGenerated')
  const size = row.package_size
  const sizeLabel = size == null ? '' : size >= 1048576 ? `${(size / 1048576).toFixed(1)} MB` : `${(size / 1024).toFixed(1)} KB`
  return `${text('fileReady')}${sizeLabel ? ` · ${sizeLabel}` : ''}`
}
function openRecordVersion(row: DatasetImportSummary) {
  if (row.dataset_version_id) void router.push(`/datasets/${encodeURIComponent(row.dataset_id)}/versions/${encodeURIComponent(row.dataset_version_id)}`)
}
async function downloadRow(row: DatasetExportSummary) {
  if (downloading.value || !canDownload(row)) return
  downloading.value = row.dataset_export_id
  error.value = ''
  try {
    const blob = await downloadDatasetExport(row.dataset_export_id)
    const url = URL.createObjectURL(blob), anchor = document.createElement('a')
    anchor.href = url
    anchor.download = row.package_file_name || `${row.dataset_export_id}.zip`
    anchor.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
    feedback.info(text('downloadStarted'))
    await load()
  } catch (e) { error.value = datasetError(e) }
  finally { downloading.value = '' }
}
const taskOptions = computed(() => [
  { value: '', label: text('all') },
  ...(
    (session.bootstrap?.capabilities.dataset_import?.implemented_task_types ||
      []) as string[]
  ).map((value) => ({ value, label: text(value) })),
])
const stateOptions = computed(() => [
  { value: '', label: text('all') },
  ...(tab.value === 'datasets'
    ? [
        { value: 'available', label: text('available') },
        { value: 'empty', label: text('emptyVersion') },
      ]
    : tab.value === 'versions'
      ? ['available', 'missing', 'unavailable', 'updating', 'empty'].map((value) => ({ value, label: text(`versionState_${value}`) }))
    : (tab.value === 'imports'
        ? ([
            'completed',
            'failed',
            'cancelled',
            'received',
            'extracted',
            'validated',
          ] as const)
        : (['completed', 'failed', 'cancelled', 'queued', 'running'] as const)
      ).map((value) => ({ value, label: text(value) }))),
])
const isDataset = (row: Row): row is DatasetItem => 'latest_version' in row
const isVersion = (row: Row): row is DatasetVersion => 'split_counts' in row
const versionSource = (row: DatasetVersion) => text(row.metadata.parent_version_id ? 'derived' : row.metadata.source_import_id || row.metadata.format_type ? 'imported' : '—')
const rowId = (row: Row) =>
  isDataset(row)
    ? row.dataset_id
    : 'dataset_import_id' in row
      ? row.dataset_import_id
      : 'dataset_export_id' in row
        ? row.dataset_export_id
        : row.dataset_version_id
const rowName = (row: Row) =>
  row.display_name || row.dataset_id
const { sampleColumns, splitColumns } = useDatasetCounts()
let controller: AbortController | undefined,
  timer: ReturnType<typeof setTimeout> | undefined,
  generation = 0
async function load() {
  if (!project.selectedProjectId) return
  controller?.abort()
  controller = new AbortController()
  const request = ++generation
  const requestedTab = tab.value
  loading.value = true
  error.value = ''
  try {
    const query = {
      project_id: project.selectedProjectId,
      q: q.value,
      offset: offset.value,
      limit,
      task_type: taskType.value,
      state: availability.value,
      days: tab.value === 'imports' ? Number(period.value || 0) : undefined,
      file_state: tab.value === 'exports' ? fileState.value : undefined,
      status:
        tab.value === 'imports' || tab.value === 'exports'
          ? availability.value
          : undefined,
    }
    const result = await (tab.value === 'datasets'
      ? listDatasetCatalog(query, controller.signal)
      : tab.value === 'versions'
        ? listDatasetVersionPage(query, controller.signal)
        : listDatasetRecordPage(tab.value, query, controller.signal))
    if (request !== generation || tab.value !== requestedTab) return
    rowsTab.value = requestedTab
    rows.value = result.items
    total.value = result.total
    if (offset.value && rows.value.length === 0) {
      offset.value = Math.max(0, offset.value - limit)
      await sync()
    }
  } catch (e) {
    if (
      request === generation &&
      !(e instanceof DOMException && e.name === 'AbortError')
    ) {
      error.value = datasetError(e)
      if (rowsTab.value !== requestedTab) { rows.value = []; total.value = 0 }
    }
  } finally {
    if (request === generation) loading.value = false
  }
}
function sync() {
  return router.replace({
    path: '/datasets',
    query: {
      tab: tab.value === 'datasets' ? undefined : tab.value,
      q: q.value || undefined,
      task: taskType.value || undefined,
      state: availability.value || undefined,
      days: period.value || undefined,
      file_state: fileState.value || undefined,
      offset: offset.value || undefined,
    },
  })
}
function changeTab(value: Tab) {
  if (tab.value === value) return
  tab.value = value
  offset.value = 0
  taskType.value = ''
  availability.value = ''
  period.value = ''
  fileState.value = ''
  void sync()
}
function search() {
  offset.value = 0
  void sync()
}
function scheduleSearch() {
  clearTimeout(timer)
  timer = setTimeout(search, 250)
}
function page(delta: number) {
  offset.value = Math.max(0, offset.value + delta)
  void sync()
}
function view(row: Row) {
  if (isDataset(row)) {
    if (row.latest_version)
      void router.push(
        `/datasets/${encodeURIComponent(row.dataset_id)}/versions/${encodeURIComponent(row.latest_version.dataset_version_id)}`,
      )
  } else if (isVersion(row))
    void router.push(
      `/datasets/${encodeURIComponent(row.dataset_id)}/versions/${encodeURIComponent(row.dataset_version_id)}`,
    )
  else
    void router.push(
      `/datasets/${'dataset_import_id' in row ? 'imports' : 'exports'}/${encodeURIComponent(rowId(row))}`,
    )
}
function menu(row: Row) {
  if (isDataset(row))
    return [
      { id: 'info', label: text('details'), icon: Info },
      ...(canWrite.value
        ? [
            { id: 'edit', label: text('editShort'), icon: Pencil },
            { id: 'import', label: text('importShort'), icon: Upload },
            {
              id: 'export',
              label: text('exportShort'),
              icon: Download,
              disabled: !row.latest_version,
            },
          ]
        : []),
    ]
  return canWrite.value
    ? [
        ...(isVersion(row)
          ? [{ id: 'export', label: text('exportShort'), icon: Download }]
          : []),
        ...('dataset_export_id' in row && !row.metadata.files_cleaned_at
          ? [
              {
                id: 'cleanup',
                label: text('cleanup'),
                icon: Trash2,
                danger: true,
                disabled: !['completed', 'failed', 'cancelled'].includes(
                  row.status,
                ),
              },
            ]
          : []),
        {
          id: 'delete',
          label: text('remove'),
          icon: Trash2,
          danger: true,
          disabled:
            !isVersion(row) &&
            (!['completed', 'failed', 'cancelled'].includes(row.status) ||
              ('dataset_export_id' in row && !row.metadata.files_cleaned_at)),
        },
      ]
    : [{ id: 'info', label: text('details'), icon: Info }]
}
async function action(id: string, row: Row) {
  if (id !== 'info' && !canWrite.value) return
  error.value = ''
  if (id === 'delete' || id === 'cleanup') {
    cleanupOnly.value = id === 'cleanup'
    removal.value = row
    return
  }
  if (id === 'import') {
    void router.push({
      path: '/datasets/import',
      query: { dataset: row.dataset_id },
    })
    return
  }
  if (id === 'export') {
    void router.push({
      path: '/datasets/export',
      query: {
        dataset: row.dataset_id,
        version: isDataset(row)
          ? row.latest_version?.dataset_version_id
          : row.dataset_version_id,
      },
    })
    return
  }
  if (!isDataset(row)) {
    view(row)
    return
  }
  try {
    drawer.value = {
      mode: id === 'edit' ? 'edit' : 'info',
      info: await getDatasetInfo(row.project_id, row.dataset_id),
    }
  } catch (e) {
    error.value = datasetError(e)
  }
}
const cleanupOnly = ref(false)
const deleteMessage = computed(() =>
  !removal.value
    ? ''
    : cleanupOnly.value
      ? '清理导出文件和 ZIP？保留记录、报告和来源版本。'
      : isVersion(removal.value)
        ? '删除此版本及其图片、标注和关联记录？存在外部引用时将阻止删除。'
        : 'dataset_import_id' in removal.value
          ? '删除导入记录及上传附件？已生成的数据集版本、图片和标注将保留。'
          : '删除这条已清理的导出记录？来源数据集版本将保留。',
)
async function remove() {
  if (!canWrite.value || !removal.value || deleting.value) return
  deleting.value = true
  try {
    const row = removal.value
    if (isVersion(row))
      await submitResourceDeletion(
        'dataset-version',
        row.dataset_version_id,
        row.project_id,
      )
    else if ('dataset_import_id' in row)
      await deleteDatasetImport(row.dataset_import_id)
    else if ('dataset_export_id' in row) {
      if (cleanupOnly.value)
        await submitResourceDeletion(
          'dataset-export-files',
          row.dataset_export_id,
          row.project_id,
        )
      else await deleteDatasetExport(row.dataset_export_id)
    }
    removal.value = null
    await load()
  } catch (e) {
    error.value = datasetError(e)
    removal.value = null
  } finally {
    deleting.value = false
  }
}
watch(
  () => project.selectedProjectId,
  () => {
    generation++
    controller?.abort()
    loading.value = false
    rows.value = []
    total.value = 0
    removal.value = null
    // 编辑抽屉保留输入；身份由抽屉打开时的项目固定，不能写到新项目。
  },
)
watch(
  () => [
    route.query.tab,
    route.query.q,
    route.query.offset,
    route.query.task,
    route.query.state,
    route.query.days,
    route.query.file_state,
    project.selectedProjectId,
  ],
  () => {
    tab.value = tabs.includes(route.query.tab as Tab)
      ? (route.query.tab as Tab)
      : 'datasets'
    q.value = String(route.query.q || '')
    taskType.value = String(route.query.task || '')
    availability.value = String(route.query.state || '')
    period.value = ['7', '30'].includes(String(route.query.days)) ? String(route.query.days) : ''
    fileState.value = ['ready', 'generating', 'not_generated', 'cleaned'].includes(String(route.query.file_state)) ? String(route.query.file_state) : ''
    offset.value = Math.min(
      10000000,
      Math.max(0, Math.floor(Number(route.query.offset) || 0)),
    )
    void load()
  },
  { immediate: true },
)
onBeforeUnmount(() => {
  generation++
  controller?.abort()
  clearTimeout(timer)
})
function clearFilters() {
  q.value = ''
  taskType.value = ''
  availability.value = ''
  period.value = ''
  fileState.value = ''
  search()
}
function afterSaved() {
  drawer.value = null
  void load()
}
</script>
