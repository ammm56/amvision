<template>
  <div class="quality-panel">
    <InlineError v-if="error" :message="error" />
    <Button v-if="error" size="sm" @click="cycle++">{{
      label('重试', 'Retry')
    }}</Button>
    <header
      class="check-summary"
      :class="{
        warning: stale || (report && report.issue_count > 0),
        success: report && !stale && report.issue_count === 0,
      }"
      role="status"
    >
      <component
        :is="
          stale || (report && report.issue_count > 0)
            ? CircleAlert
            : report
              ? CircleCheck
              : Info
        "
        :size="28"
      />
      <div>
        <small
          >{{ label('最近检查', 'Last check') }}
          {{ datasetDate(job?.finished_at || job?.created_at) }}</small
        >
        <h2>{{ headline }}</h2>
        <span v-if="report"
          >{{ number(report.sample_count) }} {{ label('个样本', 'samples') }} ·
          {{ number(report.issue_count) }}
          {{ label('项提示', 'findings') }}</span
        >
        <span v-else-if="job?.error_message">{{ job.error_message }}</span>
      </div>
      <RouterLink
        v-if="job"
        class="check-detail"
        :to="{
          path:
            '/datasets/' +
            encodeURIComponent(workspace.dataset_id) +
            '/versions/' +
            encodeURIComponent(workspace.dataset_version_id) +
            '/tools/quality',
          query: { task: job.task_id },
        }"
        >{{ label('检查详情', 'Check details') }}</RouterLink
      >
    </header>
    <ResourceTable
      class="dataset-table quality-table"
      :label="label('质量检查结果', 'Quality check results')"
    >
      <thead>
        <tr>
          <th>{{ label('检查项', 'Check') }}</th>
          <th>{{ label('结果', 'Result') }}</th>
          <th>{{ label('受影响样本', 'Affected samples') }}</th>
          <th>{{ text('actions') }}</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="row.key">
          <td><span class="check-name"><component :is="row.icon" :size="16" aria-hidden="true" /> {{ row.name }}</span></td>
          <td>
            <span
              class="check-result"
              :class="{ pass: row.checked && !row.count, warn: row.checked && row.count > 0 }"
              ><span class="check-mark" aria-hidden="true"><b v-if="row.checked && row.count">!</b><component v-else :is="row.checked ? Check : Minus" :size="10" :stroke-width="3" /></span>{{
                !row.checked
                  ? label('未检查', 'Not checked')
                  : row.count
                    ? label('待复核', 'Review')
                    : label('通过', 'Passed')
              }}</span
            >
          </td>
          <td>
            {{
              !row.checked
                ? '—'
                : row.affected == null
                  ? label('未完整记录', 'Not fully recorded')
                  : number(row.affected)
            }}
          </td>
          <td>
            <Button
              size="sm"
              v-if="row.checked || row.key === 'semantic'"
              @click="activeKey = row.key"
              ><component :is="row.checked && row.issues.length ? ImageIcon : FileText" :size="14" aria-hidden="true" />{{
                row.checked && row.issues.length
                  ? label('查看样本', 'View samples')
                  : row.checked
                    ? label('查看报告', 'View report')
                    : label('查看说明', 'Details')
              }}</Button
            ><span v-else>—</span>
          </td>
        </tr>
      </tbody>
    </ResourceTable>
    <p class="quality-note">
      <Info :size="15" />{{
        label(
          '同一样本可能有多项提示。检查不会修改或删除样本。',
          'A sample may have multiple findings. Checks do not change samples.',
        )
      }}
    </p>
    <details
      class="import-check"
      @toggle="importOpen = ($event.currentTarget as HTMLDetailsElement).open"
    >
      <summary>
        {{ label('导入时的检查报告', 'Import validation report') }}
      </summary>
      <InlineError v-if="importError" :message="importError" />
      <p v-else-if="!importReport" role="status">{{ text('loading') }}</p>
      <div v-else-if="importReport.available">
        <RouterLink
          v-if="importReport.dataset_import_id"
          :to="
            '/datasets/imports/' +
            encodeURIComponent(importReport.dataset_import_id)
          "
          >{{ label('导入详情', 'Import details') }}</RouterLink
        >
        <pre class="dataset-json">{{
          JSON.stringify(importReport.report, null, 2)
        }}</pre>
      </div>
      <p v-else>
        {{
          label(
            '没有保留导入检查报告',
            'No import validation report was retained',
          )
        }}
      </p>
    </details>
    <SideDrawer
      :open="!!active"
      :title="active?.name || ''"
      :close-label="text('close')"
      @close="activeKey = ''"
    >
      <template v-if="active"
        ><p>{{ active.description }}</p>
        <p v-if="active.checked">
          {{ label('问题数', 'Findings') }}：{{ number(active.count) }}
        </p>
        <InlineError v-if="sampleError" :message="sampleError" />
        <ul v-if="active.issues.length" class="issue-list">
          <li v-for="(issue, i) in active.issues" :key="i">
            <button :disabled="opening" @click="openSample(issue.sample_id)">
              {{ issue.file_name }}</button
            ><span>{{ issue.message }}</span>
          </li>
        </ul>
        <p v-if="active.count > active.issues.length" class="dataset-muted">
          {{
            label(
              '报告仅保留部分明细。',
              'Only part of the findings was retained.',
            )
          }}
        </p>
      </template>
    </SideDrawer>
  </div>
</template>
<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { RouterLink } from 'vue-router'
import {
  CircleAlert,
  CircleCheck,
  Info,
  Files,
  Scan,
  Copy,
  Tags,
  UserRound,
  FileText,
  Image as ImageIcon,
  Check,
  Minus,
} from '@lucide/vue'
import Button from '@/shared/ui/components/Button.vue'
import SideDrawer from '@/shared/ui/components/SideDrawer.vue'
import ResourceTable from '@/shared/ui/data-display/ResourceTable.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import { datasetDate, datasetError, useDatasetText } from '../dataset-workspace'
import {
  getDatasetReport,
  getDatasetJob,
  listDatasetJobs,
  getDatasetSample,
  type DatasetJob,
  type DatasetWorkspace,
  type DatasetSample,
} from '../services/dataset-workspace.service'
const props = defineProps<{ workspace: DatasetWorkspace }>(),
  emit = defineEmits<{ sample: [sample: DatasetSample] }>()
const { locale } = useI18n(),
  text = useDatasetText(),
  label = (zh: string, en: string) => (locale.value.startsWith('zh') ? zh : en)
const number = (n: number) => n.toLocaleString(locale.value)
const job = ref<DatasetJob | null>(null),
  loading = ref(true),
  error = ref(''),
  cycle = ref(0),
  activeKey = ref(''),
  opening = ref(false),
  sampleError = ref('')
type Issue = {
  kind: string
  sample_id: string
  file_name: string
  message: string
}
type Report = {
  sample_count: number
  issue_count: number
  counts: Record<string, number>
  issues: Issue[]
  checked: string[]
  truncated: boolean
}
const report = computed(() =>
  job.value?.state === 'succeeded' && Array.isArray(job.value.result?.checked)
    ? (job.value.result as Report)
    : null,
)
const stale = computed(
  () =>
    !!report.value &&
    (job.value?.content_revision ?? '') !==
      (props.workspace.metadata.content_revision ?? ''),
)
const headline = computed(() =>
  stale.value
    ? label('样本已更新，需重新检查', 'Samples changed; run checks again')
    : report.value
      ? report.value.issue_count
        ? label('检查完成，有待核对项', 'Completed with findings')
        : label('检查通过', 'Checks passed')
      : job.value
        ? text(job.value.state)
        : error.value
          ? label('无法读取检查结果', 'Check results unavailable')
          : loading.value
            ? text('loading')
            : label('此版本尚未检查', 'This version has not been checked'),
)
const rows = computed(() => {
  const defs = [
    {
      key: 'files',
      name: label('文件与标注关联', 'Files and annotations'),
      icon: Files,
      checks: ['image_readability', 'empty_annotations'],
      kinds: ['unreadable_image', 'missing_asset', 'empty_annotation'],
      description: label(
        '检查图片可读性、附件和空标注。无标注的负样本可能是正常数据。',
        'Checks image readability, missing assets and empty annotations. Negative samples may have no annotations.',
      ),
    },
    {
      key: 'geometry',
      name: label('图像尺寸与标注边界', 'Image dimensions and bounds'),
      icon: Scan,
      checks: ['image_size', 'bounding_geometry'],
      kinds: ['image_size', 'invalid_geometry'],
      description: label(
        '核对登记尺寸、标注框大小及边界。',
        'Checks recorded dimensions and geometry bounds.',
      ),
    },
    {
      key: 'duplicates',
      name: label('重复样本', 'Exact duplicates'),
      icon: Copy,
      checks: ['exact_duplicates'],
      kinds: ['duplicate_image'],
      description: label(
        '按文件内容识别完全重复的样本，不判定近似重复。',
        'Compares exact file contents; near duplicates are not evaluated.',
      ),
    },
    {
      key: 'category',
      name: label('类别引用', 'Class references'),
      icon: Tags,
      checks: ['category_reference'],
      kinds: ['unknown_category'],
      description: label(
        '检查标注引用的类别是否存在。',
        'Checks that annotated classes exist.',
      ),
    },
    {
      key: 'semantic',
      name: label('标注语义正确性', 'Annotation semantics'),
      icon: UserRound,
      checks: [],
      kinds: [],
      description: label(
        '自动检查不能判断标注的类别语义是否正确。',
        'Automatic checks do not assess semantic correctness.',
      ),
    },
  ]
  return defs.map((d) => {
    const r = report.value,
      checked =
        !!r && !!d.checks.length && d.checks.every((c) => r.checked.includes(c))
    const issues = (r?.issues ?? []).filter((x) => d.kinds.includes(x.kind)),
      count = d.kinds.reduce((n, k) => n + (r?.counts[k] ?? 0), 0)
    return {
      ...d,
      checked,
      issues,
      count,
      affected:
        count === issues.length
          ? new Set(issues.map((x) => x.sample_id)).size
          : null,
    }
  })
})
const active = computed(() =>
  rows.value.find((row) => row.key === activeKey.value),
)
watch(activeKey, () => {
  sampleError.value = ''
})
const importOpen = ref(false),
  importError = ref(''),
  importReport = ref<Awaited<ReturnType<typeof getDatasetReport>> | null>(null)
watch(
  () => [props.workspace, importOpen.value],
  async (_, __, cleanup) => {
    importReport.value = null
    importError.value = ''
    if (!importOpen.value) return
    const ctrl = new AbortController()
    cleanup(() => ctrl.abort())
    try {
      const result = await getDatasetReport(
        props.workspace.dataset_id,
        props.workspace.dataset_version_id,
        ctrl.signal,
      )
      if (!ctrl.signal.aborted) importReport.value = result
    } catch (e) {
      if (!ctrl.signal.aborted) importError.value = datasetError(e)
    }
  },
)
let epoch = 0
watch(
  () => [props.workspace, cycle.value],
  (_, __, cleanup) => {
    const abort = new AbortController(),
      id = ++epoch
    let timer: ReturnType<typeof setTimeout> | undefined
    cleanup(() => {
      ++epoch
      abort.abort()
      clearTimeout(timer)
    })
    const w = props.workspace
    job.value = null
    activeKey.value = ''
    loading.value = true
    error.value = ''
    async function read() {
      try {
        const page = await listDatasetJobs(
          w.dataset_id,
          w.dataset_version_id,
          0,
          { operation: 'quality', limit: 1, signal: abort.signal },
        )
        const latest = page.items[0],
          detail = latest
            ? await getDatasetJob(
                w.dataset_id,
                w.dataset_version_id,
                latest.task_id,
                abort.signal,
              )
            : null
        if (id !== epoch) return
        job.value = detail
        if (
          detail &&
          [
            'queued',
            'pending',
            'running',
            'cancelling',
            'cancel_requested',
          ].includes(detail.state)
        )
          timer = setTimeout(read, 2500)
      } catch (e) {
        if (id === epoch) error.value = datasetError(e)
      } finally {
        if (id === epoch) loading.value = false
      }
    }
    void read()
  },
  { immediate: true },
)
async function openSample(sampleId: string) {
  const id = epoch
  opening.value = true
  sampleError.value = ''
  try {
    const s = await getDatasetSample(
      props.workspace.dataset_id,
      props.workspace.dataset_version_id,
      sampleId,
    )
    if (id === epoch && activeKey.value) {
      activeKey.value = ''
      emit('sample', s)
    }
  } catch (e) {
    if (id === epoch) sampleError.value = datasetError(e)
  } finally {
    opening.value = false
  }
}
</script>
<style scoped>
.check-detail {
  margin-left: auto;
  white-space: nowrap;
  color: var(--am-text);
}
.import-check summary {
  cursor: pointer;
  color: var(--am-text-muted);
}
.import-check[open] summary {
  margin-bottom: 12px;
}
.quality-panel {
  display: grid;
  gap: 16px;
  min-width: 0;
}
.check-summary {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 18px 22px;
  border: 1px solid var(--am-border);
  border-radius: var(--am-radius-md);
  background: var(--am-surface);
}
.check-summary h2 {
  font-size: 17px;
  margin: 4px 0;
}
.check-summary small,
.check-summary span,
.quality-note {
  font-size: 13px;
  color: var(--am-text-muted);
}
.check-summary.success {
  background: color-mix(in srgb, var(--am-brand-primary) 7%, var(--am-surface));
}
.check-summary.success > svg {
  color: var(--am-brand-primary);
}
.check-summary.warning {
  background: color-mix(in srgb, var(--am-warning-text) 9%, var(--am-surface));
}
.check-summary.warning > svg {
  color: var(--am-warning-text);
}
.quality-table :deep(th:first-child) {
  width: 35%;
}
.quality-table .check-name,
.quality-table .check-result {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}
.quality-table .check-name svg { flex: none; }
.quality-table .check-result {
  min-height: 26px;
  padding: 2px 10px;
  border-radius: var(--am-radius-sm);
  background: var(--am-hover-surface);
  color: var(--am-text-muted);
  font-size: 13px;
}
.check-mark {
  display: inline-grid;
  place-items: center;
  flex: none;
  width: 14px;
  height: 14px;
  border-radius: 50%;
  color: white;
  background: var(--am-text-muted);
}
.quality-table .check-result.pass {
  color: var(--am-success-text);
  background: var(--am-success-surface);
}
.check-result.pass .check-mark { background: var(--am-success-icon); }
.quality-table .check-result.warn {
  color: var(--am-warning-text);
  background: var(--am-warning-surface);
}
.check-result.warn .check-mark { background: var(--am-warning-icon); }
.quality-table :deep(th:last-child) { width: 10.5rem; }
.quality-table :deep(td:last-child) { text-overflow: clip; }
.quality-table :deep(.ui-button) { min-width: 90px; }
.check-mark b { font-size: 11px; line-height: 1; }
.quality-note {
  display: flex;
  gap: 8px;
  align-items: center;
  margin: 0;
}
.issue-list {
  padding: 0;
  list-style: none;
  display: grid;
  gap: 12px;
}
.issue-list li {
  display: grid;
  gap: 4px;
  overflow-wrap: anywhere;
}
.issue-list button {
  justify-self: start;
  font: inherit;
  color: var(--am-text);
  cursor: pointer;
}
</style>
