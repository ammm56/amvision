<template>
  <section class="dataset-workspace dataset-record" :class="{ 'dataset-record--export': !importing }">
    <div class="dataset-heading">
      <div class="dataset-actions">
        <Button @click="back"
          ><ArrowLeft :size="16" />{{ text('back') }}</Button
        >
        <h1 class="dataset-title" :title="name">
          <template v-if="name">{{ name }} · </template>
          {{
            label(
              importing ? '导入详情' : '导出详情',
              importing ? 'Import details' : 'Export details',
            )
          }}
        </h1>
      </div>
      <div class="dataset-actions">
        <Button :loading="loading" @click="load"
          ><RefreshCw :size="16" />{{ text('refresh') }}</Button
        ><ResourceMenu
          v-if="detail && canWrite"
          :label="text('more')"
          :items="actions"
          @action="confirmAction = $event"
        />
      </div>
    </div>
    <InlineError v-if="error" :message="error" />
    <div v-if="!detail && loading" role="status">{{ text('loading') }}</div>
    <template v-if="detail">
      <div class="dataset-record-heading">
        <TaskStateBadge :state="detail.status" /><strong class="dataset-record-subject" :title="importDetail ? sourceFileName : format">{{ importDetail ? sourceFileName : format }}</strong
        ><StatusBadge v-if="cleaned" tone="neutral" :label="text('cleaned')" />
        <div class="dataset-actions">
          <Button
            v-if="detail.task_id && session.hasScopes(['tasks:read'])"
            @click="router.push(`/tasks/${detail.task_id}`)"
            ><Activity :size="16" />{{
              label('任务详情', 'Task details')
            }}</Button
          ><Button v-if="!importing && workspace" @click="viewVersion"
            ><FolderOpen :size="16" />{{
              label('查看版本', 'View version')
            }}</Button
          ><Button
            v-if="exportDetail?.status === 'completed' && !cleaned"
            variant="primary"
            :loading="busy"
            @click="download"
            ><Download :size="16" />{{
              label('下载 ZIP', 'Download ZIP')
            }}</Button
          >
        </div>
      </div>
      <InlineError
        v-if="detail.error_message"
        :message="detail.error_message"
      />
      <p v-if="cancelRequested && !terminal" role="status">
        {{
          label(
            '取消请求已发送，正在确认任务结果。',
            'Cancellation requested. Checking the final task state.',
          )
        }}
      </p>
      <ResourceCleanupPanel
        v-if="canWrite"
        :project-id="detail.project_id"
        @settled="load"
      />
      <div class="dataset-record-grid dataset-record-overview">
        <section class="resource-section">
          <h2>{{ text('source') }}</h2>
          <dl class="dataset-details">
            <dt>{{ text('version') }}</dt>
            <dd>{{ versionLabel }}</dd>
            <dt>{{ text('task') }}</dt>
            <dd>{{ text(detail.task_type) }}</dd>
            <dt>{{ text('created') }}</dt>
            <dd>{{ datasetDate(detail.created_at) }}</dd>
            <dt>{{ label('完成时间', 'Completed') }}</dt>
            <dd>{{ datasetDate(completedAt) }}</dd>
            <template v-if="!importing"><dt>{{ text('samples') }}</dt><dd>{{ number(sampleCount) }}</dd><dt>{{ text('classes') }}</dt><dd>{{ number(classCount) }}</dd></template>
            <dt v-if="importing">{{ label('数据格式', 'Data format') }}</dt><dd v-if="importing">{{ format }}</dd>
            <dt v-if="importDetail">{{ label('来源包大小', 'Source package size') }}</dt><dd v-if="importDetail">{{ formatBytes(importDetail.package_size) }}</dd>
          </dl>
        </section>
        <section v-if="importDetail" class="resource-section">
          <div class="dataset-heading"><h2>{{ label('检查结果', 'Check result') }}</h2><StatusBadge v-if="importDetail.validation_report.status" :label="importDetail.validation_report.status === 'ok' ? label('检查通过', 'Checks passed') : label('检查未通过', 'Checks did not pass')" :tone="importDetail.validation_report.status === 'ok' ? 'success' : 'warning'" /></div>
          <dl class="dataset-details">
            <dt>{{ importDetail.validation_report.added_count != null ? label('更新后样本', 'Samples after update') : text('samples') }}</dt><dd>{{ number(sampleCount) }}</dd>
            <dt>{{ text('classes') }}</dt><dd>{{ number(classCount) }}</dd>
            <template
              v-if="importDetail?.validation_report.added_count != null"
            >
              <dt>{{ label('新增样本', 'Added samples') }}</dt>
              <dd><DatasetCounts :items="countItems('samples', importDetail.validation_report.added_count, label('新增样本', 'Added samples'))" /></dd>
              <dt
                v-if="Number(importDetail.validation_report.removed_count) > 0"
              >
                {{ label('删除样本', 'Removed samples') }}
              </dt>
              <dd
                v-if="Number(importDetail.validation_report.removed_count) > 0"
              >
                <DatasetCounts :items="countItems('samples', importDetail.validation_report.removed_count, label('删除样本', 'Removed samples'))" />
              </dd>
            </template>
          </dl>
          <ResourceTable
            v-if="issues.length"
            class="dataset-table"
            :label="label('问题', 'Issues')"
            ><thead>
              <tr>
                <th>{{ label('类型', 'Type') }}</th>
                <th>{{ label('信息', 'Message') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(issue, index) in issues.slice(0, 100)" :key="index">
                <td>{{ issue.code || issue.severity || '—' }}</td>
                <td class="dataset-issue">
                  {{ issue.message || issue.actual || '—' }}
                </td>
              </tr>
            </tbody></ResourceTable
          >
          <p v-else-if="!importDetail.validation_report.status" class="dataset-muted">
            {{ label('尚无检查报告', 'No check report available') }}
          </p>
          <p v-if="issues.length > 100">
            {{
              label(
                '当前显示前 100 条，完整内容见原始报告。',
                'Showing the first 100 issues. See the full report below.',
              )
            }}
          </p>
        </section>
        <section v-else class="resource-section">
          <h2>{{ label('导出产物', 'Export files') }}</h2>
          <dl class="dataset-details">
            <dt>{{ text('format') }}</dt>
            <dd>{{ exportDetail?.format_id }}</dd>
            <dt>{{ text('file') }}</dt>
            <dd>
              {{
                cleaned
                  ? text('cleaned')
                  : exportDetail?.status !== 'completed' ? text(['queued', 'running'].includes(exportDetail?.status || '') ? 'fileGenerating' : 'fileNotGenerated') : exportDetail?.package_file_name || text('packageOnDownload')
              }}
            </dd>
            <dt>{{ label('大小', 'Size') }}</dt>
            <dd>{{ formatBytes(exportDetail?.package_size) }}</dd>
          </dl>
          <Button
            v-if="canWrite && detail.dataset_version_id"
            @click="newExport"
            ><Download :size="16" />{{
              label('重新创建导出', 'Create another export')
            }}</Button
          >
        </section>
      </div>
      <div class="dataset-record-grid dataset-record-tables">
        <section class="resource-section">
          <h2>{{ label('类别映射', 'Class mapping') }}</h2>
          <ResourceTable
            v-if="classMappings.length"
            class="dataset-table"
            :label="text('classes')"
            ><thead>
              <tr>
                <th>
                  {{ label('类别 ID', 'Class ID') }}
                </th>
                <th>{{ label('类别名称', 'Class name') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="mapping in classMappings" :key="`${mapping.source}:${mapping.target}`">
                <td :title="mapping.source">{{ mapping.source }}</td>
                <td :title="mapping.target">{{ mapping.target }}</td>
              </tr>
            </tbody></ResourceTable
          ><span v-else>—</span>
        </section>
        <section class="resource-section">
          <h2>{{ text('splits') }}</h2>
          <ResourceTable class="dataset-table" :label="text('splits')"
            ><thead>
              <tr>
                <th>Split</th>
                <th class="dataset-number-cell">{{ text('samples') }}</th>
                <th class="dataset-number-cell">{{ label('占比', 'Share') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="split in ['train', 'test', 'val']" :key="split">
                <td>{{ split }}</td>
                <td class="dataset-number-cell"><DatasetCounts v-if="splitCounts[split] != null" :items="countItems(split, splitCounts[split], splitName(split))" /><span v-else>—</span></td>
                <td class="dataset-number-cell">
                  {{
                    sampleCount && splitCounts[split] != null
                      ? `${((splitCounts[split] / sampleCount) * 100).toFixed(1)}%`
                      : '—'
                  }}
                </td>
              </tr>
            </tbody></ResourceTable
          >
        </section>
      </div>
      <section
        v-if="exportDetail?.status === 'completed' && !cleaned"
        class="resource-section dataset-record-files"
      >
        <div class="dataset-heading">
          <h2>{{ label('导出文件结构', 'Export file structure') }}</h2>
          <div class="dataset-actions">
            <Button
              :disabled="!folder"
              @click="openFolder(folder.split('/').slice(0, -1).join('/'))"
              ><ArrowUp :size="16" />{{ label('上一级', 'Parent') }}</Button
            ><span class="dataset-file-path" :title="folder || '/'">{{ folder || '/' }}</span>
          </div>
        </div>
        <InlineError v-if="fileError" :message="fileError" /><ResourceTable
          class="dataset-table"
          :label="text('structure')"
          ><thead>
            <tr>
              <th>{{ text('fileName') }}</th>
              <th style="width: 100px">{{ label('大小', 'Size') }}</th>
              <th style="width: 84px">{{ text('actions') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="file in files" :key="file.path">
              <td>
                <Button v-if="file.directory" variant="ghost" size="sm" class="dataset-file-entry dataset-file-name" :title="file.name" @click="openFile(file)"><ChevronRight :size="14" /><Folder :size="16" /><span>{{ file.name }}</span></Button>
                <div v-else class="dataset-file-name" :title="file.name"
                  ><component
                    :is="file.directory ? Folder : FileText"
                    :size="16"
                  /><span>{{ file.name }}</span></div
                >
              </td>
              <td>{{ file.directory ? '—' : formatBytes(file.size) }}</td>
              <td>
                <Button
                  v-if="
                    file.directory ||
                    /\.(json|txt|xml|yaml|yml|csv|jsonl)$/i.test(file.name)
                  "
                  size="sm"
                  @click="openFile(file)"
                  >{{ text('view') }}</Button
                >
              </td>
            </tr>
          </tbody></ResourceTable
        >
        <div v-if="cursor || cursors.length" class="dataset-actions">
          <Button :disabled="!cursors.length" @click="previousFiles">{{
            label('上一页', 'Previous page')
          }}</Button
          ><Button :disabled="!cursor" @click="nextFiles">{{
            label('下一页', 'Next page')
          }}</Button>
        </div>
      </section>
      <section v-if="importDetail?.status === 'completed' && detail.dataset_version_id" class="resource-section dataset-record-result">
        <div><h2>{{ importDetail.validation_report.added_count != null ? label('已更新版本', 'Updated version') : label('生成的数据集版本', 'Created dataset version') }}</h2><span>{{ versionLabel }}</span></div>
        <div class="dataset-actions"><Button v-if="canWrite && workspace" @click="newExport"><Download :size="16" />{{ text('export') }}</Button><Button v-if="workspace" variant="primary" @click="viewVersion"><FolderOpen :size="16" />{{ label('查看版本', 'View version') }}</Button><span v-else>{{ label('版本暂不可用', 'Version unavailable') }}</span></div>
      </section>
      <section class="resource-section">
        <details>
          <summary>
            {{ label('原始参数与报告', 'Parameters and report') }}
          </summary>
          <pre class="dataset-json">{{ JSON.stringify(detail, null, 2) }}</pre>
        </details>
      </section>
    </template>
    <SideDrawer
      :open="filePreviewOpen"
      :title="filePreview?.path || ''"
      :close-label="text('close')"
      @close="filePreviewOpen = false"
      @after-leave="filePreview = null"
      ><p v-if="filePreview?.truncated">
        {{ label('仅显示前 256 KB', 'Showing the first 256 KB') }}
      </p>
      <pre class="dataset-json">{{ filePreview?.content }}</pre>
    </SideDrawer>
    <ConfirmDialog
      v-if="confirmAction"
      :title="confirmTitle"
      :message="confirmMessage"
      :confirm-label="confirmTitle"
      :cancel-label="text('cancel')"
      :busy="busy"
      :confirm-variant="confirmAction === 'cancel' ? 'primary' : 'danger'"
      @confirm="performAction"
      @cancel="confirmAction = ''"
    />
  </section>
</template>
<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import {
  Activity,
  ArrowLeft,
  ArrowUp,
  ChevronRight,
  Download,
  FileText,
  Folder,
  FolderOpen,
  RefreshCw,
  Trash2,
  X,
} from '@lucide/vue'
import { useSessionStore } from '@/app/stores/session.store'
import { useFeedbackStore } from '@/app/stores/feedback.store'
import Button from '@/shared/ui/components/Button.vue'
import ResourceMenu from '@/shared/ui/components/ResourceMenu.vue'
import ResourceCleanupPanel from '@/shared/ui/components/ResourceCleanupPanel.vue'
import SideDrawer from '@/shared/ui/components/SideDrawer.vue'
import ConfirmDialog from '@/shared/ui/components/ConfirmDialog.vue'
import ResourceTable from '@/shared/ui/data-display/ResourceTable.vue'
import StatusBadge from '@/shared/ui/data-display/StatusBadge.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import TaskStateBadge from '@/modules/tasks/components/TaskStateBadge.vue'
import { cancelTask } from '@/modules/tasks/services/task.service'
import { apiRequest } from '@/shared/api/http-client'
import { ApiError } from '@/shared/api/error'
import { submitResourceDeletion } from '@/shared/api/resource-deletion'
import {
  getDatasetImportDetail,
  getDatasetExportDetail,
  downloadDatasetExport,
  deleteDatasetImport,
  deleteDatasetExport,
  type DatasetImportDetail,
  type DatasetExportDetail,
} from '../services/dataset.service'
import {
  getDatasetWorkspace,
  getDatasetInfo,
  datasetVersionPath,
  type DatasetWorkspace,
  type DatasetFile,
} from '../services/dataset-workspace.service'
import { datasetDate, datasetError, useDatasetText } from '../dataset-workspace'
import DatasetCounts from '../components/DatasetCounts.vue'
import { useDatasetCounts } from '../dataset-counts'
const { countItems, splitName } = useDatasetCounts()
import '../dataset-workspace.css'
const props = defineProps<{ kind: 'imports' | 'exports' }>()
const route = useRoute(),
  router = useRouter(),
  session = useSessionStore(),
  feedback = useFeedbackStore(),
  { locale } = useI18n(),
  text = useDatasetText()
const label = (zh: string, en: string) =>
  locale.value.startsWith('zh') ? zh : en
const importing = computed(() => props.kind === 'imports'),
  identity = computed(() =>
    String(importing.value ? route.params.datasetImportId : route.params.datasetExportId),
  )
const detail = ref<DatasetImportDetail | DatasetExportDetail | null>(null),
  workspace = ref<DatasetWorkspace | null>(null),
  name = ref(''),
  error = ref(''),
  loading = ref(false),
  busy = ref(false),
  confirmAction = ref(''),
  cancelRequested = ref(false)
const importDetail = computed(() =>
    detail.value && 'dataset_import_id' in detail.value ? detail.value : null,
  ),
  exportDetail = computed(() =>
    detail.value && 'dataset_export_id' in detail.value ? detail.value : null,
  )
const canWrite = computed(() => session.hasScopes(['datasets:write'])),
  terminal = computed(() =>
    ['completed', 'failed', 'cancelled', 'canceled'].includes(
      detail.value?.status || '',
    ),
  ),
  cleaned = computed(() => !!exportDetail.value?.metadata.files_cleaned_at)
const format = computed(
  () => importDetail.value?.format_type || exportDetail.value?.format_id || '—',
)
const number = (value: unknown) => typeof value === 'number' && Number.isFinite(value) ? value.toLocaleString() : '—'
const sourceFileName = computed(() => String(importDetail.value?.metadata.source_file_name || importDetail.value?.metadata.original_file_name || importDetail.value?.package_path.replaceAll('\\', '/').split('/').pop() || '—'))
const versionLabel = computed(() => {
  const value = importDetail.value?.dataset_version?.version_number || workspace.value?.version_number
  return value ? `v${value}` : '—'
})
const completedAt = computed(() =>
  String(
    detail.value?.metadata.completed_at ||
      detail.value?.metadata.exported_at ||
      detail.value?.metadata.imported_at ||
      '',
  ),
)
const classNames = computed(
  () =>
    exportDetail.value?.category_names ||
    Object.values(importDetail.value?.class_map || {}) ||
    [],
)
// 导入服务保存的是归一化类别 ID→名称，不冒充原始文件的类别名称。
const classMappings = computed(() => {
  const entries = Object.entries(importDetail.value?.class_map || (exportDetail.value?.metadata.class_map as Record<string, string> | undefined) || {})
  if (entries.length)
    return entries.map(([source, target]) => ({ source, target }))
  return classNames.value.map((name) => ({ source: '—', target: name }))
})
const sampleCount = computed(
  () =>
    exportDetail.value?.sample_count ??
    (importDetail.value?.validation_report.sample_count as number | undefined),
)
const classCount = computed(() => exportDetail.value?.category_names.length ?? importDetail.value?.validation_report.category_count)
const splitCounts = computed(() => {
  const source =
    exportDetail.value?.metadata.split_counts ||
    importDetail.value?.validation_report.split_counts ||
    importDetail.value?.detected_profile.split_counts ||
    {}
  return Object.fromEntries(
    Object.entries(source).filter(
      ([key]) =>
        !exportDetail.value || exportDetail.value.split_names.includes(key),
    ),
  ) as Record<string, number>
})
const issues = computed(() => [
  ...(importDetail.value?.validation_report.error ? [importDetail.value.validation_report.error as Record<string, unknown>] : []),
  ...((importDetail.value?.validation_report.errors as Record<
    string,
    unknown
  >[]) || []),
  ...((importDetail.value?.validation_report.warnings as Record<
    string,
    unknown
  >[]) || []),
])
const actions = computed(() =>
  !terminal.value
    ? [
        ...(detail.value?.task_id &&
        session.hasScopes(['tasks:write']) &&
        (detail.value.status === 'queued' ||
          importDetail.value?.processing_state === 'queued')
          ? [
              {
                id: 'cancel',
                label: label('取消任务', 'Cancel task'),
                icon: X,
                disabled: cancelRequested.value,
              },
            ]
          : []),
      ]
    : [
        ...(!importing.value && !cleaned.value
          ? [
              {
                id: 'cleanup',
                label: text('cleanup'),
                icon: Trash2,
                danger: true,
              },
            ]
          : []),
        {
          id: 'delete',
          label: label('删除记录', 'Delete record'),
          icon: Trash2,
          danger: true,
          disabled: !importing.value && !cleaned.value,
        },
      ],
)
const confirmTitle = computed(() =>
  confirmAction.value === 'cancel'
    ? label('取消任务', 'Cancel task')
    : confirmAction.value === 'cleanup'
      ? text('cleanup')
      : label('删除记录', 'Delete record'),
)
const confirmMessage = computed(() =>
  confirmAction.value === 'cancel'
    ? label(
        '停止尚未完成的处理？已完成结果会保留。',
        'Stop unfinished processing? Completed results are retained.',
      )
    : confirmAction.value === 'cleanup'
      ? label(
          '清理导出文件和 ZIP？保留记录、报告和来源版本。',
          'Clean export files and ZIP? Keep the record, report, and source version.',
        )
      : importing.value
        ? label(
            '删除记录、上传 ZIP 和暂存文件？保留数据集版本、图片和标注。',
            'Delete the record, upload and staging files? Keep dataset versions, images and annotations.',
          )
        : label(
            '删除这条已清理的导出记录？',
            'Delete this cleaned export record?',
          ),
)
let generation = 0,
  active = true,
  timer: ReturnType<typeof setTimeout> | undefined,
  fileGeneration = 0
function back() {
  void router.push({ path: '/datasets', query: { tab: props.kind } })
}
function viewVersion() {
  if (detail.value?.dataset_version_id)
    void router.push(
      datasetVersionPath(
        detail.value.dataset_id,
        detail.value.dataset_version_id,
      ),
    )
}
function newExport() {
  if (detail.value)
    void router.push({
      path: '/datasets/export',
      query: {
        dataset: detail.value.dataset_id,
        version: detail.value.dataset_version_id,
      },
    })
}
function formatBytes(value?: number | null) {
  if (value == null) return '—'
  return value >= 1048576
    ? `${(value / 1048576).toFixed(1)} MB`
    : `${(value / 1024).toFixed(1)} KB`
}
async function load() {
  clearTimeout(timer)
  const request = ++generation
  loading.value = true
  error.value = ''
  let retryable = true
  try {
    const result = await (importing.value
      ? getDatasetImportDetail(identity.value)
      : getDatasetExportDetail(identity.value))
    if (!active || request !== generation) return
    detail.value = result
    // 名称与来源版本的读取失败不应阻止历史记录及导出文件查看。
    try {
      const info = await getDatasetInfo(result.project_id, result.dataset_id)
      if (!active || request !== generation) return
      name.value = info.display_name
    } catch { if (active && request === generation) name.value ||= result.display_name || result.dataset_id }
    if (!active || request !== generation) return
    if (result.dataset_version_id && !workspace.value) {
      try {
        const data = await getDatasetWorkspace(
          result.dataset_id,
          result.dataset_version_id,
        )
        if (request === generation) workspace.value = data
      } catch {
        /* 记录仍可查看，来源版本可能已不可用。 */
      }
    }
    if (
      exportDetail.value?.status === 'completed' &&
      !cleaned.value &&
      !files.value.length
    )
      await loadFiles()
  } catch (e) {
    retryable = !(e instanceof ApiError && [401, 403, 404].includes(e.status))
    if (active && request === generation) error.value = datasetError(e)
  } finally {
    if (active && request === generation) {
      loading.value = false
      if (retryable && !terminal.value) timer = setTimeout(load, 2500)
    }
  }
}
async function download() {
  if (!exportDetail.value || busy.value) return
  busy.value = true
  error.value = ''
  try {
    const blob = await downloadDatasetExport(identity.value)
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = exportDetail.value.package_file_name || `${identity.value}.zip`
    a.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
    feedback.info(text('downloadStarted'))
    await load()
  } catch (e) {
    error.value = datasetError(e)
  } finally {
    busy.value = false
  }
}
async function performAction() {
  if (!detail.value || busy.value || !canWrite.value) return
  if (confirmAction.value === 'cancel' && !session.hasScopes(['tasks:write']))
    return
  busy.value = true
  error.value = ''
  try {
    if (confirmAction.value === 'cancel') {
      await cancelTask(detail.value.task_id!)
      cancelRequested.value = true
      await load()
    } else if (confirmAction.value === 'cleanup') {
      await submitResourceDeletion(
        'dataset-export-files',
        identity.value,
        detail.value.project_id,
      )
      await load()
    } else {
      await (importing.value
        ? deleteDatasetImport(identity.value)
        : deleteDatasetExport(identity.value))
      back()
    }
    confirmAction.value = ''
  } catch (e) {
    error.value = datasetError(e)
    confirmAction.value = ''
  } finally {
    busy.value = false
  }
}
const folder = ref(''),
  files = ref<DatasetFile[]>([]),
  fileError = ref(''),
  cursor = ref<string | null>(null),
  fileAfter = ref(''),
  cursors = ref<string[]>([]),
  filePreview = ref<{
    path: string
    content: string
    truncated: boolean
  } | null>(null)
async function loadFiles() {
  const request = ++fileGeneration
  fileError.value = ''
  try {
    const data = await apiRequest<{
      items: DatasetFile[]
      next_cursor: string | null
    }>(`/datasets/exports/${identity.value}/files`, {
      query: { path: folder.value, after: fileAfter.value },
    })
    if (active && request === fileGeneration) {
      files.value = data.items
      cursor.value = data.next_cursor
    }
  } catch (e) {
    if (active && request === fileGeneration) fileError.value = datasetError(e)
  }
}
function openFolder(path: string) {
  files.value = []
  cursor.value = null
  folder.value = path
  fileAfter.value = ''
  cursors.value = []
  void loadFiles()
}
async function openFile(file: DatasetFile) {
  if (file.directory) {
    openFolder(file.path)
    return
  }
  const request = ++fileGeneration
  try {
    const data = await apiRequest<{
      path: string
      content: string
      truncated: boolean
    }>(`/datasets/exports/${identity.value}/file-text`, {
      query: { path: file.path },
    })
    if (active && request === fileGeneration) {
      filePreview.value = data
      filePreviewOpen.value = true
    }
  } catch (e) {
    fileError.value = datasetError(e)
  }
}
const filePreviewOpen = ref(false)
watch(
  () => [identity.value, props.kind],
  () => {
    fileGeneration++
    detail.value = null
    workspace.value = null
    name.value = ''
    files.value = []
    folder.value = ''
    cursor.value = null
    fileAfter.value = ''
    cursors.value = []
    fileError.value = ''
    filePreviewOpen.value = false
    filePreview.value = null
    cancelRequested.value = false
    void load()
  },
  { immediate: true },
)
onBeforeUnmount(() => {
  active = false
  generation++
  fileGeneration++
  clearTimeout(timer)
})
function previousFiles() {
  fileAfter.value = cursors.value.pop() || ''
  void loadFiles()
}
function nextFiles() {
  if (!cursor.value) return
  cursors.value.push(fileAfter.value)
  fileAfter.value = cursor.value
  void loadFiles()
}
</script>
<style scoped>
.dataset-record-heading {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
}
.dataset-record-heading > .dataset-actions {
  margin-left: auto;
}
.dataset-record-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}
.dataset-record { display: flex; flex-direction: column; }
.dataset-record-subject { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.dataset-record-overview .dataset-details { margin-bottom: 0; }
.dataset-record-overview .resource-section > .ui-button { width: fit-content; }
.dataset-record--export .dataset-record-files { order: 1; }
.dataset-record--export .dataset-record-tables { order: 2; }
.dataset-record--export > .resource-section:last-of-type { order: 3; }
.dataset-record-result { display: flex; align-items: center; justify-content: space-between; gap: 16px; flex-wrap: wrap; }
.dataset-record-result h2 { margin: 0 0 8px; }
.dataset-record-result span { color: var(--am-text-muted); font-size: 14px; }
.dataset-file-name > span { min-width: 0; overflow: hidden; text-overflow: ellipsis; }
.dataset-file-name > svg { flex-shrink: 0; }
.dataset-record-grid .resource-section {
  margin: 0;
  min-width: 0;
}
.dataset-issue {
  white-space: normal !important;
  overflow-wrap: anywhere;
}
.dataset-file-name {
  display: flex;
  gap: 10px;
  align-items: center;
}
.dataset-file-entry { max-width: 100%; padding-inline: 0; font-weight: 400; }
.dataset-muted {
  color: var(--am-text-muted);
  font-size: 13px;
}
@media (max-width: 850px) {
  .dataset-record-grid {
    grid-template-columns: 1fr;
  }
  .dataset-record-heading > .dataset-actions {
    margin-left: 0;
  }
}
</style>
