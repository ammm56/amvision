<template>
  <section
    class="dataset-workspace dataset-record"
    :class="{ 'dataset-record--export': !importing, 'dataset-record--import': importing }"
  >
    <div class="dataset-heading">
      <div class="dataset-actions">
        <Button @click="back"
          ><ArrowLeft :size="16" />{{
            text('back')
          }}</Button
        >
        <h1 class="dataset-title" :title="name">
          <template v-if="name && importing">{{ name }} · </template>
          {{
            label(
              importing ? '导入详情' : '导出记录',
              importing
                ? 'Import details'
                : 'Export record',
            )
          }}
        </h1>
      </div>
      <div class="dataset-actions">
        <Button :loading="loading" @click="load()"
          ><RefreshCw :size="16" />{{ text('refresh') }}</Button
        ><ResourceMenu
          v-if="detail && canWrite && actions.length"
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
        <strong v-if="exportDetail" class="dataset-record-subject">{{ name }} · {{ datasetFormatLabel(exportDetail.format_id) }}</strong>
        <StatusBadge
          v-if="cleaned"
          tone="neutral"
          :label="label('已完成', 'Completed')"
        /><TaskStateBadge
          v-else
          :state="detail.status"
          appearance="icon"
        /><strong
          v-if="importing"
          class="dataset-record-subject"
          :title="importDetail ? sourceFileName : format"
          >{{ importDetail ? sourceFileName : format }}</strong
        ><StatusBadge v-if="cleaned" tone="warning" :label="text('cleaned')" />
        <div class="dataset-actions">
          <Button
            v-if="importDetail?.status === 'failed' && canWrite"
            variant="primary"
            @click="router.push('/datasets/import')"
            >{{ label('重新导入', 'Import again') }}</Button
          >
          <Button
            v-if="exportDetail && cleaned && canWrite"
            variant="primary"
            :disabled="!workspace"
            @click="newExport"
            >{{ label('重新创建导出', 'Create another export') }}</Button
          >
          <Button
            v-if="exportDetail?.status === 'completed'"
            :disabled="cleaned"
            :variant="cleaned ? 'secondary' : 'primary'"
            :loading="busy"
            @click="download"
            ><Download :size="16" />{{
              label('下载 ZIP', 'Download ZIP')
            }}</Button
          >
          <Button
            v-if="exportDetail?.status === 'completed' && trainingSupported"
            :disabled="cleaned"
            @click="startTraining"
            >{{
              label('用此导出创建训练', 'Create training from export')
            }}</Button
          >
          <Button v-if="!importing && workspace" @click="viewVersion"
            ><FolderOpen :size="16" />{{
              label('查看版本', 'View version')
            }}</Button
          >

        </div>
      </div>
      <div v-if="importDetail" class="record-file-meta">
        <span>{{ formatBytes(importDetail.package_size) }}</span><span>{{ label('数据格式','Format') }} {{ importFormatName }}</span>
        <span>{{ label('提交时间', 'Submitted') }} {{ datasetDate(detail.created_at) }}</span>
        <span v-if="completedAt">{{ label('完成时间', 'Completed') }} {{ datasetDate(completedAt) }}</span>
      </div>
      <InlineError
        v-if="detail.error_message && !importDetail"
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
      <ol
        v-if="importDetail"
        class="dataset-steps"
        :aria-label="label('导入进度', 'Import progress')"
      >
        <li
          v-for="(step, index) in importSteps"
          :key="step.label"
          :aria-label="
            step.complete
              ? step.label + ' · ' + label('已完成', 'Completed')
              : step.label
          "
          :class="{
            'is-complete': step.complete,
            'is-failed': failedStage === index,
          }"
        >
          <span aria-hidden="true"
            ><Check v-if="step.complete" :size="15" /><X
              v-else-if="failedStage === index"
              :size="15"
            /><template v-else>{{ index + 1 }}</template></span
          >
          <div><strong>{{ index + 1 }}. {{ step.label }}</strong>
            <time v-if="step.time" :datetime="step.time" :title="datasetDate(step.time)">{{ formatSystemDateTime(step.time, 'step') }}</time>
            <small v-else>—</small>
            <small>{{ step.complete ? step.result : failedStage === index ? label('失败','Failed') : label('待处理','Pending') }}</small>
          </div>
        </li>
      </ol>
      <ResourceCleanupPanel
        v-if="canWrite"
        :project-id="detail.project_id"
        :resource-id="identity"
        @settled="load"
      />
      <div v-if="exportDetail" class="export-facts">
        <div v-for="item in exportFacts" :key="item.label">
          <small>{{ item.label }}</small>
          <div class="fact-value"><component :is="item.icon" :size="17" /><strong :title="item.value">{{ item.value }}</strong></div>
          <small v-if="item.note">{{ item.note }}</small>
        </div>
      </div>
      <p v-if="cleaned" class="record-warning" role="status">
        <TriangleAlert :size="17" />{{
          label(
            '导出文件已清理，记录仍保留。',
            'Export files were cleaned. The record is retained.',
          )
        }}
      </p>
      <div
        v-if="importDetail"
        class="dataset-record-grid dataset-record-overview"
      >
        <section class="resource-section">
          <h2>{{ label('来源信息','Source information') }}</h2>
          <dl class="dataset-details">
            <dt>{{ text('fileName') }}</dt>
            <dd>{{ sourceFileName }}</dd>
            <dt>{{ label('文件大小','File size') }}</dt><dd>{{ formatBytes(importDetail.package_size) }}</dd>
            <dt>{{ label('数据格式','Format') }}</dt><dd>{{ importFormatName }}</dd>
            <dt>{{ label('提交时间','Submitted') }}</dt><dd>{{ datasetDate(detail.created_at) }}</dd>
            <dt>{{ label('完成时间','Completed') }}</dt><dd>{{ datasetDate(completedAt) }}</dd>
          </dl>
        </section>
        <section v-if="importDetail" class="resource-section">
          <div class="dataset-heading">
            <h2>{{ importDetail.status === 'failed' ? label('导入失败', 'Import failed') : label('结构检查结果', 'Validation results') }}</h2>
            <StatusBadge
              v-if="importDetail.validation_report.status && importDetail.validation_report.status !== 'ok' && importDetail.status !== 'failed'"
              :label="
                importDetail.validation_report.status === 'ok'
                  ? label('检查通过', 'Checks passed')
                  : label('检查未通过', 'Checks did not pass')
              "
              :tone="
                importDetail.validation_report.status === 'ok'
                  ? 'success'
                  : 'warning'
              "
            />
          </div>
          <div v-if="importDetail.status === 'failed'" class="record-failure" role="alert"><TriangleAlert :size="21" />
            <div><strong>{{ importSteps[failedStage]?.label || label('导入失败','Import failed') }}</strong>
            <p>{{ detail.error_message || issues[0]?.message || label('查看下方错误信息。','See the error details below.') }}</p></div>
          </div>
          <ResourceTable
            v-if="importDetail.validation_report.status === 'ok'"
            class="dataset-table validation-table"
            :label="label('校验摘要', 'Validation summary')"
            ><thead>
              <tr>
                <th>{{ label('检查项', 'Check') }}</th>
                <th>{{ label('结果', 'Result') }}</th>
                <th>{{ label('详情', 'Details') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="check in validationRows" :key="check.label">
                <td><span class="check-item"><CircleCheck class="status-disc" :size="17" />{{ check.label }}</span></td>
                <td><span class="mapping-pass"><CircleCheck class="status-disc" :size="17" />{{ label('通过', 'Passed') }}</span></td>
                <td>{{ check.value }}</td>
              </tr>
            </tbody></ResourceTable
          >
          <p v-if="importDetail.validation_report.added_count != null">
            {{ label('新增样本', 'Added samples') }}
            {{ number(importDetail.validation_report.added_count) }} ·
            {{ label('删除样本', 'Removed samples') }}
            {{ number(importDetail.validation_report.removed_count) }}
          </p>
          <ResourceTable
            v-if="issues.length && (importDetail.status !== 'failed' || issues.length > 1 || (detail.error_message && detail.error_message !== issues[0]?.message))"
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
          <InlineError
            v-if="importDetail.status !== 'failed' && detail.error_message && !issues.some(issue => issue.message === detail?.error_message)"
            :message="detail.error_message"
          />
          <p
            v-if="
              importDetail.status === 'failed' && !detail.dataset_version_id
            "
            class="dataset-muted"
          >
            {{
              label(
                '本次导入未生成版本。',
                'No version was created by this import.',
              )
            }}
          </p>
          <p
            v-if="
              !importDetail.validation_report.status && !detail.error_message
            "
            class="dataset-muted"
          >
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
      </div>
      <div class="dataset-record-grid dataset-record-tables">
        <section class="resource-section">
          <h2>{{ label('类别映射', 'Class mapping') }}<small v-if="classMappings.length"> ({{ classMappings.length }})</small></h2>
          <ResourceTable
            v-if="classMappings.length"
            class="dataset-table"
            :label="text('classes')"
            ><thead>
              <tr>
                <th>
                  {{ label('类别名称', 'Class name') }}
                </th>
                <th v-if="exportDetail">{{ label('目标类别 ID', 'Target class ID') }}</th>
                <th>{{ label('对象数', 'Objects') }}</th>
                <th v-if="importDetail">{{ label('映射状态', 'Mapping status') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="mapping in classMappings"
                :key="`${mapping.source}:${mapping.target}`"
              >
                <td :title="mapping.target">{{ mapping.target }}</td>
                <td v-if="exportDetail" :title="mapping.source">{{ mapping.source }}</td>
                <td>{{ number(objectCounts[mapping.source]) }}</td>
                <td v-if="importDetail"><span v-if="importDetail.validation_report.status === 'ok'" class="mapping-pass"><CircleCheck class="status-disc" :size="15" />{{ label('映射完成','Mapped') }}</span><template v-else>—</template></td>
              </tr>
              <tr v-if="importDetail && detail.metadata.object_count != null"><th scope="row">{{ label('合计','Total') }}</th><td>{{ number(detail.metadata.object_count) }}</td><td>—</td></tr>
            </tbody></ResourceTable
          ><span v-else>—</span>
        </section>
        <section class="resource-section">
          <h2>{{ text('splits') }}</h2>
          <ResourceTable class="dataset-table" :label="text('splits')"
            ><thead>
              <tr>
                <th>{{ label('划分','Split') }}</th>
                <th class="dataset-number-cell">{{ text('samples') }}</th>
                <th class="dataset-number-cell">
                  {{ label('对象数', 'Objects') }}
                </th>
                <th class="dataset-number-cell">
                  {{ label('占比', 'Share') }}
                </th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="split in ['train', 'val', 'test']" :key="split">
                <td>{{ split }}</td>
                <td class="dataset-number-cell">
                  <DatasetCounts
                    v-if="splitCounts[split] != null"
                    :items="
                      countItems(split, splitCounts[split], splitName(split))
                    "
                  /><span v-else>—</span>
                </td>
                <td class="dataset-number-cell">
                  {{ number(splitObjects[split]) }}
                </td>
                <td class="dataset-number-cell">
                  {{
                    sampleCount && splitCounts[split] != null
                      ? `${((splitCounts[split] / sampleCount) * 100).toFixed(1)}%`
                      : '—'
                  }}
                </td>
              </tr>
              <tr v-if="sampleCount != null && Object.keys(splitCounts).length">
                <th scope="row">{{ label('总计', 'Total') }}</th>
                <td class="dataset-number-cell">{{ number(sampleCount) }}</td>
                <td class="dataset-number-cell">
                  {{ number(detail.metadata.object_count) }}
                </td>
                <td class="dataset-number-cell">
                  {{ sampleCount ? '100%' : '—' }}
                </td>
              </tr>
            </tbody></ResourceTable
          >
        </section>
      </div>
      <DatasetExportFiles
        v-if="exportDetail?.status === 'completed'"
        :key="identity + ':' + cleaned"
        :id="identity"
        :format="datasetFormatLabel(exportDetail.format_id)"
        :cleaned="cleaned"
        :history="historicalFiles"
        :truncated="!!detail.metadata.file_list_truncated"
        :format-bytes="formatBytes"
        @preview="openFile"
      />
      <InlineError v-if="fileError" :message="fileError" />
      <section class="resource-section">
      <div
        v-if="importDetail?.status === 'completed' && detail.dataset_version_id"
        class="dataset-record-result"
      >
        <div>
          <h2>
            {{
              importDetail.validation_report.added_count != null
                ? label('已更新版本', 'Updated version')
                : label('生成的数据集版本', 'Created dataset version')
            }}
          </h2>
          <ResourceTable embedded class="dataset-table" :label="label('版本摘要','Version summary')">
            <thead><tr><th>{{ label('版本号','Version') }}</th><th>{{ label('样本数量','Samples') }}</th><th>{{ label('对象数量','Objects') }}</th><th>{{ label('类别数量','Classes') }}</th><th>{{ label('数据格式','Format') }}</th><th>{{ label('生成时间','Created') }}</th></tr></thead>
            <tbody><tr><td><span class="version-number"><Database :size="16" />{{ versionLabel }}</span></td><td>{{ number(sampleCount) }}</td><td>{{ number(detail.metadata.object_count) }}</td><td>{{ number(classCount) }}</td><td>{{ importFormatName }}</td><td :title="datasetDate(completedAt)">{{ datasetDate(completedAt) }}</td></tr></tbody>
          </ResourceTable>
        </div>
        <div class="dataset-actions">
          <Button v-if="canWrite && workspace" @click="newExport"
            ><Download :size="16" />{{ text('export') }}</Button
          >
          <Button v-if="workspace" variant="primary" @click="viewVersion"
            ><FolderOpen :size="16" />{{
              label('查看版本', 'View version')
            }}</Button
          ><span v-else>{{
            label('版本暂不可用', 'Version unavailable')
          }}</span>
        </div>
      </div>
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
    <DatasetRecordConfirm v-if="confirmAction === 'cleanup' || confirmAction === 'delete'" :importing="importing" :clean="confirmAction === 'cleanup'" :name="name" :version="versionLabel" :file="importing ? sourceFileName : exportDetail?.package_file_name" :busy="busy" @confirm="performAction" @cancel="confirmAction = ''" />
    <ConfirmDialog
      v-else-if="confirmAction"
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
import { formatSystemDateTime } from '@/shared/formatters/date-time'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import {
  Database, Scan, Layers, Clock, FileArchive, CircleCheck, TriangleAlert,
  Check,
  ArrowLeft,
  Download,
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
import DatasetRecordConfirm from '../components/DatasetRecordConfirm.vue'
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
import { datasetDate, datasetError, useDatasetText, datasetFormatLabel } from '../dataset-workspace'
import DatasetExportFiles from '../components/DatasetExportFiles.vue'
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
    String(
      importing.value
        ? route.params.datasetImportId
        : route.params.datasetExportId,
    ),
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
const importFormatName = computed(() => format.value === 'imagenet' ? 'ImageNet' : format.value.toUpperCase())
const number = (value: unknown) =>
  typeof value === 'number' && Number.isFinite(value)
    ? value.toLocaleString()
    : '—'
const sourceFileName = computed(() =>
  String(
    importDetail.value?.metadata.source_file_name ||
      importDetail.value?.metadata.original_file_name ||
      importDetail.value?.package_path.replaceAll('\\', '/').split('/').pop() ||
      '—',
  ),
)
const versionLabel = computed(() => {
  const value =
    importDetail.value?.dataset_version?.version_number ||
    workspace.value?.version_number
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
const splitObjects = computed(
  () =>
    (detail.value?.metadata.split_object_counts || {}) as Record<
      string,
      number
    >,
)
const objectCounts = computed(
  () =>
    (detail.value?.metadata.category_object_counts || {}) as Record<
      string,
      number
    >,
)
const historicalFiles = computed(
  () => (detail.value?.metadata.file_list || []) as DatasetFile[],
)
const trainingSupported = computed(() => {
  const catalog =
    session.bootstrap?.capabilities
      .training_export_formats_by_task_and_model_type
  const formats = catalog?.[detail.value?.task_type || '']
  return (
    !!exportDetail.value &&
    canWrite.value &&
    session.hasScopes(['models:read', 'tasks:read', 'tasks:write']) &&
    !!formats &&
    Object.values(formats).some((ids) => ids.includes(format.value))
  )
})
function startTraining() {
  if (exportDetail.value && !cleaned.value)
    void router.push({
      path: '/models',
      query: {
        datasetExport: identity.value,
        task: exportDetail.value.task_type,
      },
    })
}
const exportFacts = computed(() => {
  const e = exportDetail.value
  if (!e) return []
  const size = e.package_size ?? (e.metadata.historical_package_size as number | undefined)
  return [
    { icon: Database, label: label('来源版本','Source version'), value: [name.value, versionLabel.value].filter(Boolean).join(' ') },
    { icon: Scan, label: label('目标格式','Target format'), value: datasetFormatLabel(e.format_id) },
    { icon: Layers, label: label('类别与划分','Classes and splits'), value: [e.category_names.length + ' ' + text('classes'), ...e.split_names.map(key => key + ' ' + (splitCounts.value[key] ?? '—'))].join(' · ') },
    { icon: Clock, label: text('created'), value: datasetDate(e.created_at) },
    { icon: Clock, label: label('完成时间','Completed'), value: datasetDate(completedAt.value) },
    { icon: FileArchive, label: label('导出产物','Export package'), value: e.package_file_name || String(e.metadata.historical_package_name || e.metadata.package_name || (cleaned.value ? text('cleaned') : e.status === 'completed' ? text('packageOnDownload') : '—')), note: size != null ? formatBytes(size) : '' },
  ]
})
const validationRows = computed(() => [
  { label: label('样本文件', 'Sample files'), value: label(`已导入 ${number(sampleCount.value)} 个样本`, `${number(sampleCount.value)} samples imported`) },
  ...(detail.value?.metadata.object_count != null
    ? [
        {
          label: label('标注校验', 'Annotation validation'),
          value: label(`${number(detail.value.metadata.object_count)} 个标注对象`, `${number(detail.value.metadata.object_count)} annotated objects`),
        },
      ]
    : []),
  { label: label('类别映射','Class mapping'), value: label(`${number(classCount.value)} 个类别`, `${number(classCount.value)} classes`) },
  {
    label: text('splits'),
    value: Object.entries(splitCounts.value).map(([split, count]) => split + ' ' + number(count)).join(' / ') || '—',
  },
])
const failedStage = computed(() =>
  importDetail.value?.status === 'failed'
    ? importSteps.value.findIndex((s) => !s.complete)
    : -1,
)
const importSteps = computed(() => {
  const entry = importDetail.value
  if (!entry) return []
  return [
    {
      label: label('上传数据', 'Upload data'),
      result: label('上传完成', 'Uploaded'),
      time: String(entry.metadata.uploaded_at || ''),
      complete: entry.upload_state === 'uploaded',
    },
    {
      label: label('数据结构检查', 'Check structure'),
      result: label('解包完成', 'Archive extracted'),
      time: String(entry.metadata.extracted_at || ''),
      complete: !!entry.metadata.extracted_at || !!entry.detected_profile.format_type,
    },
    {
      label: label('标注校验', 'Validate annotations'),
      result: label('校验通过', 'Validated'),
      time: String(entry.metadata.validated_at || ''),
      complete: entry.validation_report.status === 'ok',
    },
    {
      label:
        entry.validation_report.added_count != null
          ? label('更新版本', 'Update version')
          : label('生成版本', 'Create version'),
      result: entry.validation_report.added_count != null ? label('版本已更新','Version updated') : label('版本已生成','Version created'),
      time: completedAt.value,
      complete: entry.status === 'completed' && !!entry.dataset_version_id,
    },
  ]
})
const classNames = computed(
  () =>
    exportDetail.value?.category_names ||
    Object.values(importDetail.value?.class_map || {}) ||
    [],
)
// 导入服务保存的是归一化类别 ID→名称，不冒充原始文件的类别名称。
const classMappings = computed(() => {
  if (exportDetail.value) {
    const ids = Object.keys(
      (exportDetail.value.metadata.class_map || {}) as Record<string, string>,
    ).sort((a, b) => Number(a) - Number(b))
    return exportDetail.value.category_names.map((target, i) => ({
      source: ids[i] ?? '—',
      target,
    }))
  }
  const entries = Object.entries(importDetail.value?.class_map || {})
  if (entries.length)
    return entries.map(([source, target]) => ({ source, target }))
  return classNames.value.map((name) => ({ source: '—', target: name }))
})
const sampleCount = computed(
  () =>
    exportDetail.value?.sample_count ??
    (importDetail.value?.validation_report.sample_count as number | undefined),
)
const classCount = computed(
  () =>
    exportDetail.value?.category_names.length ??
    importDetail.value?.validation_report.category_count,
)
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
  ...(importDetail.value?.validation_report.error
    ? [importDetail.value.validation_report.error as Record<string, unknown>]
    : []),
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
  if (detail.value && workspace.value)
    void router.push({
      path: '/datasets/export',
      query: {
        dataset: detail.value.dataset_id,
        version: detail.value.dataset_version_id,
        ...(exportDetail.value ? { format: exportDetail.value.format_id } : {}),
      },
    })
}
function formatBytes(value?: number | null) {
  if (value == null) return '—'
  return value >= 1048576
    ? `${(value / 1048576).toFixed(1)} MB`
    : `${(value / 1024).toFixed(1)} KB`
}
async function load(background = false) {
  clearTimeout(timer)
  const request = ++generation
  loading.value = !background || !detail.value
  let retryable = true
  try {
    const result = await (importing.value
      ? getDatasetImportDetail(identity.value)
      : getDatasetExportDetail(identity.value))
    if (!active || request !== generation) return
    error.value = ''
    detail.value = result
    // 名称与来源版本的读取失败不应阻止历史记录及导出文件查看。
    try {
      const info = await getDatasetInfo(result.project_id, result.dataset_id)
      if (!active || request !== generation) return
      name.value = info.display_name
    } catch {
      if (active && request === generation)
        name.value ||= result.display_name || result.dataset_id
    }
    if (!active || request !== generation) return
    if (result.dataset_version_id && !workspace.value) {
      try {
        const data = await getDatasetWorkspace(
          result.dataset_id,
          result.dataset_version_id,
        )
        if (active && request === generation) workspace.value = data
      } catch {
        /* 记录仍可查看，来源版本可能已不可用。 */
      }
    }
    if (!active || request !== generation) return
  } catch (e) {
    retryable = !(e instanceof ApiError && [401, 403, 404].includes(e.status))
    if (active && request === generation) error.value = datasetError(e)
  } finally {
    if (active && request === generation) {
      loading.value = false
      if (retryable && !terminal.value) timer = setTimeout(() => void load(true), 2500)
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
    a.download =
      exportDetail.value.package_file_name ||
      String(exportDetail.value.metadata.package_name || '') ||
      `${identity.value}.zip`
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
const fileError = ref(''),
  filePreview = ref<{
    path: string
    content: string
    truncated: boolean
  } | null>(null)
async function openFile(file: DatasetFile) {
  fileError.value = ''
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
    if (active && request === fileGeneration) fileError.value = datasetError(e)
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
</script>
<style scoped>
.record-failure { display: flex; gap: 12px; padding: 16px; color: var(--am-danger-text); background: var(--am-danger-surface); border-radius: var(--am-radius-sm); overflow-wrap: anywhere; }
.record-failure p { color: var(--am-text); margin: 6px 0 0; }
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
.dataset-record {
  display: flex;
  flex-direction: column;
}
.dataset-record-subject {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.dataset-record-overview .dataset-details {
  margin-bottom: 0;
}
.dataset-record-overview .resource-section > .ui-button {
  width: fit-content;
}
.dataset-record--export .dataset-record-files {
  order: 1;
}
.dataset-record--export .dataset-record-tables {
  order: 2;
}
.dataset-record--export > .resource-section:last-of-type {
  order: 3;
}
.dataset-record-result {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}
.dataset-record-result h2 {
  margin: 0 0 8px;
}
.dataset-record-result span {
  color: var(--am-text-muted);
  font-size: 14px;
}
.dataset-record-result > div:first-child { flex: 1 1 530px; min-width: 0; }
.dataset-record-result th:last-child { width: 26%; }
.record-file-meta { display: flex; flex-wrap: wrap; gap: 6px 18px; color: var(--am-text-muted); font-size: 13px; margin-top: -8px; }
.dataset-record .dataset-record-grid { grid-template-columns: minmax(0, 0.88fr) minmax(0, 1.12fr); gap: 14px; }
.dataset-record { gap: 14px; }
.dataset-record .resource-section { padding: clamp(16px, 1.5vw, 24px); gap: 12px; }
.dataset-record .resource-section > .resource-table { margin-inline: 0; }
.dataset-record :deep(.resource-table thead th) { background: var(--am-page); }
.dataset-record .resource-section > .resource-table { border: 0; }
.dataset-record .resource-section h2 { font-size: 16px; }
.dataset-record h2 small { font-weight: 400; color: var(--am-text-muted); }
.dataset-record :deep(.dataset-table td), .dataset-record :deep(.dataset-table th) { padding: 8px 10px; }
.dataset-record .dataset-record-overview .dataset-details { row-gap: 11px; }
.dataset-file-name > span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
}
.dataset-file-name > svg {
  flex-shrink: 0;
}
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
.dataset-file-entry {
  max-width: 100%;
  padding-inline: 0;
  font-weight: 400;
}
.dataset-muted {
  color: var(--am-text-muted);
  font-size: 13px;
}
@media (max-width: 850px) {
  .dataset-record .dataset-record-grid {
    grid-template-columns: 1fr;
  }
  .dataset-record-heading > .dataset-actions {
    margin-left: 0;
  }
}

.export-facts {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(115px, 1fr));
  gap: 12px;
  background: var(--am-surface);
  padding: 18px;
  border: 1px solid var(--am-border);
  border-radius: 6px;
}
.export-facts div {
  min-width: 0;
}
.export-facts small {
  color: var(--am-text-muted);
}
.export-facts strong {
  display: block;
  margin-top: 8px;
  font-size: 14px;
  font-weight: 500;
  overflow-wrap: anywhere;
}
.record-warning {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px;
  background: var(--am-warning-surface);
  border-radius: 6px;
}
.passed-check {
  color: var(--am-brand-primary);
  vertical-align: middle;
}
.dataset-record .dataset-steps li:not(:last-child)::after {
  content: '';
  height: 1px;
  flex: 1;
  background: var(--am-border);
}
.dataset-record .dataset-steps li.is-complete::after {
  background: var(--am-brand-primary);
}
.dataset-record .dataset-steps li.is-failed span {
  background: var(--am-danger, #dc2626);
  color: white;
}
.dataset-record .dataset-steps li > div { display: grid; gap: 5px; }
.dataset-record .dataset-steps li strong { font-size: 14px; color: var(--am-text); }
.dataset-record .dataset-steps li small, .dataset-record .dataset-steps li time { color: var(--am-text-muted); font-size: var(--am-type-caption); line-height: 1.45; }
.dataset-record .dataset-steps li time { font-variant-numeric: tabular-nums; }
.dataset-record .export-facts { grid-template-columns: minmax(0,1.2fr) minmax(0,1fr) minmax(0,1.25fr) repeat(2,minmax(0,1fr)) minmax(0,1.4fr); }
.export-facts .fact-value { display: flex; align-items: baseline; gap: 8px; margin-block-start: 6px; }
.fact-value svg { flex: none; align-self: flex-start; margin-top: 2px; }
.export-facts .fact-value strong { margin: 0; }
.mapping-pass { display: inline-flex; align-items: center; gap: 5px; color: var(--am-success-text); }
.mapping-pass svg { fill: var(--am-brand-primary); stroke: white; }
.record-warning { margin: 0; }
@media(max-width:1099px) { .dataset-record .export-facts { grid-template-columns: repeat(3,minmax(0,1fr)); } }
.dataset-record td > .mapping-pass { display: inline-flex; }
.dataset-record--import { gap: 12px; }
.dataset-record--import .dataset-record-heading { column-gap: 16px; }
.dataset-record--import .dataset-record-heading :deep(.task-state-icon) { font-size: 19px; font-weight: 600; }
.dataset-record--import .dataset-record-heading :deep(.task-state-icon--success) { color: var(--am-success-text); }
.dataset-record--import .dataset-record-heading :deep(.task-state-icon__symbol) { width: 32px; height: 32px; flex-basis: 32px; }
.dataset-record--import .dataset-record-subject { padding-inline-start: 16px; border-inline-start: 1px solid var(--am-border); }
.dataset-record--import .record-file-meta { margin: -5px 0 2px 48px; gap: 6px 0; font-size: 14px; }
.record-file-meta span + span { padding-inline-start: 14px; margin-inline-start: 14px; border-inline-start: 1px solid var(--am-border); }
.dataset-record--import .dataset-steps { align-items: flex-start; padding: 16px; }
.dataset-record--import .dataset-steps li { align-items: flex-start; }
.dataset-record--import .dataset-steps li::after { margin-top: 18px; }
.dataset-record--import .dataset-steps li > span { width: 36px; height: 36px; flex: 0 0 36px; }
.dataset-record--import .dataset-steps li > span svg { width: 22px; height: 22px; }
.dataset-record--import .dataset-record-grid { grid-template-columns: minmax(0, .89fr) minmax(0, 1.11fr); gap: 12px; }
.dataset-record--import .resource-section { padding: clamp(14px,1.15vw,20px); }
.dataset-record--import .dataset-record-overview .dataset-details { grid-template-columns: minmax(110px,32%) minmax(0,1fr); gap: 0; }
.dataset-record--import .dataset-details > * { padding: 9px 6px; border-bottom: 1px solid var(--am-border); }
.dataset-record--import .dataset-table .check-item, .dataset-record--import .dataset-table .version-number { display: inline-flex; align-items: center; gap: 9px; color: inherit; }
.check-item svg { flex: none; fill: var(--am-brand-primary); stroke: white; }
.validation-table th:first-child { width: 34%; }
.validation-table th:nth-child(2) { width: 20%; }
.validation-table td:last-child { white-space: normal; overflow-wrap: anywhere; }
.dataset-record--import .dataset-record-tables tbody tr:has(> th[scope="row"]) { font-weight: 600; }
.dataset-record--import .dataset-record-tables tbody tr:has(> th[scope="row"]):not(:hover) { background: var(--am-page); }
.dataset-record--import .dataset-record-result { align-items: center; }
.dataset-record--import .dataset-record-result .dataset-actions { margin-top: 20px; }
.dataset-record-result + details { padding-top: 10px; border-top: 1px solid var(--am-border); }
@media (max-width: 850px) {
  .dataset-record--import .dataset-record-grid { grid-template-columns: minmax(0,1fr); }
}
@media(min-width:1280px) and (min-height:780px) {
  .dataset-record .dataset-title { font-size: clamp(20px,1.45vw,25px); }
  .dataset-record .resource-section h2 { font-size: clamp(16px,1.08vw,18px); }
  .dataset-record .dataset-record-subject { font-size: clamp(17px,1.17vw,20px); }
  .dataset-record :deep(.dataset-table th),.dataset-record :deep(.dataset-table td) { font-size: clamp(14px,.96vw,16px); }
}
</style>
