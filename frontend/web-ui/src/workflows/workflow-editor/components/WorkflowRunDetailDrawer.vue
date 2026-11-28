<template>
  <SideDrawer
    :open="open"
    title="执行记录详情"
    close-label="关闭"
    plain
    size="compact"
    :busy="cancelling"
    @close="emit('close')"
  >
    <div v-if="run" class="run-drawer">
      <!-- Header status & ID -->
      <div class="run-drawer__head">
        <div class="run-drawer__status-row">
          <span class="run-state-pill" :class="`is-${runStateDotTone(run.state)}`">
            <i class="run-dot" />
            {{ formatRunDetailHeaderState(run.state) }}
          </span>
          <span
            v-if="businessOutcome"
            class="run-biz-pill"
            :class="businessOutcome === 'NG' ? 'is-ng' : 'is-ok'"
          >
            业务 {{ businessOutcome }}
          </span>
        </div>
        <div class="run-drawer__id-row">
          <span class="run-muted">编号</span>
          <code class="run-mono" :title="run.workflow_run_id">{{ displayRunId }}</code>
          <button
            type="button"
            class="run-copy-mini"
            title="复制执行编号"
            @click="copyText(run.workflow_run_id, 'id')"
          >
            <Copy :size="13" />
          </button>
          <span v-if="copiedSection === 'id'" class="run-muted" role="status">{{ copyFeedback }}</span>
        </div>
      </div>

      <TabList
        :model-value="activeTab"
        :tabs="tabs"
        label="执行记录详情页签"
        variant="underline"
        @update:model-value="(val) => (activeTab = val as DetailSubTab)"
      />

      <!-- Tab 1: 概览 -->
      <div v-if="activeTab === 'overview'" class="run-tab-body">
        <dl class="run-kv">
          <div>
            <dt>应用</dt>
            <dd>{{ applicationName || run.application_id }}</dd>
          </div>
          <div>
            <dt>实例</dt>
            <dd>{{ runtimeName || run.workflow_runtime_id }}</dd>
          </div>
          <div>
            <dt>执行版本</dt>
            <dd>{{ versionLabel || '—' }}</dd>
          </div>
          <div>
            <dt>开始时间</dt>
            <dd>{{ formatSystemDateTime(run.started_at || run.created_at) }}</dd>
          </div>
          <div v-if="run.finished_at">
            <dt>结束时间</dt>
            <dd>{{ formatSystemDateTime(run.finished_at) }}</dd>
          </div>
          <div>
            <dt>耗时</dt>
            <dd>{{ formatRunDuration(run.started_at || run.created_at, run.finished_at) }}</dd>
          </div>
          <div>
            <dt>记录方式</dt>
            <dd>{{ formatRecordModeLabel(recordMode, true) }}</dd>
          </div>
        </dl>

        <!-- Failure notice -->
        <template v-if="run.state === 'failed' || run.state === 'timed_out'">
          <div class="run-failure-head">
            <strong>{{ run.error?.message || (run.state === 'timed_out' ? '执行超时' : '执行异常退出') }}</strong>
            <button type="button" class="run-link-btn" @click="activeTab = 'diagnostics'">
              查看诊断 ›
            </button>
          </div>
          <div v-if="failureNode" class="run-failure-box">
            <div class="run-failure-node">失败节点：{{ failureNode.label }}</div>
            <code v-if="failureNode.detail" class="run-failure-detail">{{ failureNode.detail }}</code>
          </div>
          <div class="run-biz-incomplete">
            <span class="run-muted">业务结果</span>
            <strong>—</strong>
            <p>执行未完成，未生成完整结果。</p>
          </div>
        </template>

        <!-- Metrics & Visual Result -->
        <template v-else>
          <section v-if="summaryMetrics.length > 0" class="run-section">
            <h4>结果</h4>
            <div class="run-metrics-grid">
              <div v-for="m in summaryMetrics" :key="m.label" class="run-metric-item">
                <span>{{ m.label }}</span>
                <strong :class="`is-${m.tone}`">{{ m.value }}</strong>
              </div>
            </div>
          </section>

          <section v-if="recordMode === 'full' && run.state === 'succeeded' && hasOutputPayload" class="run-section">
            <WorkflowRuntimeBodyViewer
              :project-id="projectId"
              :status-code="responseStatusCode"
              :body="responseBody || run.outputs"
              media-only
            />
          </section>
          <div v-else-if="run.state === 'succeeded'" class="run-minimal-notice">
            <strong>未保存预览图</strong>
            <span>{{ recordMode === 'minimal' ? '摘要记录下输入与节点明细未保留' : '本次输出未包含可渲染图像' }}</span>
          </div>
        </template>

        <details class="run-tech-box">
          <summary>技术信息</summary>
          <dl class="run-kv run-kv--compact">
            <div>
              <dt>修订次数</dt>
              <dd>{{ run.runtime_generation ?? '暂无' }}</dd>
            </div>
            <div>
              <dt>修订记录 ID</dt>
              <dd class="run-mono">{{ run.workflow_runtime_revision_id || '暂无' }}</dd>
            </div>
            <div>
              <dt>工作进程</dt>
              <dd class="run-mono">{{ run.worker_instance_id || '暂无' }}</dd>
            </div>
            <div>
              <dt>内容校验值</dt>
              <dd class="run-mono">{{ run.snapshot_fingerprint || '暂无' }}</dd>
            </div>
          </dl>
        </details>
      </div>

      <!-- Tab 2: 输入输出 -->
      <div v-else-if="activeTab === 'io'" class="run-tab-body">
        <section class="run-section">
          <div class="run-section__head">
            <h4>输入数据</h4>
            <div v-if="hasInputPayload" class="run-section__actions">
              <button type="button" class="run-link-btn" @click="copyText(inputPreview.text)">
                {{ inputPreview.truncated ? '复制当前片段' : '复制输入' }}
              </button>
              <button
                v-if="inputPreview.truncated"
                type="button"
                class="run-link-btn"
                @click="downloadJson(`run-${run.workflow_run_id}-input.json`, inputPreview.fullText)"
              >
                下载完整 JSON
              </button>
            </div>
          </div>
          <div v-if="!hasInputPayload" class="run-minimal-notice">
            <span>{{ recordMode === 'minimal' ? '摘要记录未保留完整输入数据' : '无持久化输入数据' }}</span>
          </div>
          <template v-else>
            <p v-if="inputPreview.truncated" class="run-truncate-hint">
              内容共 {{ inputPreview.totalLines }} 行，预览已截断为前 {{ inputPreview.shownLines }} 行。
            </p>
            <pre class="run-json-block">{{ inputPreview.text }}</pre>
          </template>
        </section>

        <section class="run-section">
          <div class="run-section__head">
            <h4>输出数据</h4>
            <div v-if="hasOutputPayload" class="run-section__actions">
              <button type="button" class="run-link-btn" @click="copyText(outputPreview.text)">
                {{ outputPreview.truncated ? '复制当前片段' : '复制输出' }}
              </button>
              <button
                v-if="outputPreview.truncated"
                type="button"
                class="run-link-btn"
                @click="downloadJson(`run-${run.workflow_run_id}-output.json`, outputPreview.fullText)"
              >
                下载完整 JSON
              </button>
            </div>
          </div>
          <div v-if="!hasOutputPayload" class="run-minimal-notice">未保存输出数据</div>
          <template v-else>
            <p v-if="outputPreview.truncated" class="run-truncate-hint">
              内容共 {{ outputPreview.totalLines }} 行，预览已截断为前 {{ outputPreview.shownLines }} 行。
            </p>
            <pre class="run-json-block">{{ outputPreview.text }}</pre>
          </template>
        </section>
        <p v-if="copiedSection === 'content'" class="run-muted" role="status">{{ copyFeedback }}</p>
      </div>

      <!-- Tab 3: 诊断 -->
      <div v-else class="run-tab-body">
        <div v-if="run.error" class="run-error-card">
          <div class="run-section__head">
            <h4>错误信息</h4>
            <button type="button" class="run-link-btn" @click="copyText(JSON.stringify(run.error, null, 2))">
              复制错误
            </button>
          </div>
          <p class="run-err-msg">{{ run.error.code }}: {{ run.error.message }}</p>
          <pre v-if="Object.keys(run.error.details || {}).length > 0" class="run-json-block">{{ JSON.stringify(run.error.details, null, 2) }}</pre>
        </div>

        <section class="run-section">
          <div class="run-section__head">
            <h4>阶段耗时</h4>
            <button type="button" class="run-link-btn" @click="copyText(diagnosticsText)">
          复制诊断
            </button>
          </div>
          <div v-if="timingEntries.length === 0" class="run-minimal-notice">
            <span>暂无耗时明细（需在实例配置开启“返回诊断”）</span>
          </div>
          <dl v-else class="run-kv run-kv--compact">
            <div v-for="[k, v] in timingEntries" :key="k">
              <dt>{{ k }}</dt>
              <dd>{{ v }}</dd>
            </div>
          </dl>
        </section>
        <p v-if="copiedSection === 'content'" class="run-muted" role="status">{{ copyFeedback }}</p>

        <section v-if="nodeRecords.length > 0" class="run-section">
          <h4>节点执行记录 ({{ nodeRecords.length }})</h4>
          <div class="run-node-list">
            <div v-for="(rec, idx) in nodeRecords" :key="idx" class="run-node-item">
              <strong>{{ String(rec.display_name || rec.node_type_id || rec.node_id || `节点 ${idx + 1}`) }}</strong>
              <span class="run-muted">{{ String(rec.state || rec.status || 'completed') }}</span>
            </div>
          </div>
        </section>
      </div>
    </div>

    <template #footer>
      <Button variant="secondary" @click="emit('close')">关闭</Button>
      <Button
        v-if="run && canWrite && !isTerminalRunState(run.state)"
        variant="danger"
        :loading="cancelling"
        @click="emit('cancel-run', run)"
      >
        取消执行
      </Button>
      <Button
        v-if="run && (run.state === 'failed' || run.state === 'timed_out')"
        variant="secondary"
        @click="copyErrorSummary"
      >
        {{ footerCopyFeedback || '复制错误' }}
      </Button>
      <Button
        v-else-if="hasOutputPayload"
        variant="secondary"
        @click="copyResultSummary"
      >
        {{ footerCopyFeedback || '复制结果' }}
      </Button>
    </template>
  </SideDrawer>
</template>

<script setup lang="ts">
import { Copy } from '@lucide/vue'
import { computed, ref, watch } from 'vue'

import { formatSystemDateTime } from '@/shared/formatters/date-time'
import Button from '@/shared/ui/components/Button.vue'
import SideDrawer from '@/shared/ui/components/SideDrawer.vue'
import TabList, { type TabListItem } from '@/shared/ui/navigation/TabList.vue'
import type { WorkflowRun } from '../types'
import {
  extractBusinessOutcome,
  extractRunFailureNode,
  extractRunMetrics,
  extractRunResponseBody,
  extractRunResponseStatusCode,
  formatBoundedJson,
  formatRecordModeLabel,
  formatRunDetailHeaderState,
  formatRunDuration,
  isTerminalRunState,
  readRunRecordMode,
  runStateDotTone,
} from '../utils/workflow-run-display'
import WorkflowRuntimeBodyViewer from './WorkflowRuntimeBodyViewer.vue'

type DetailSubTab = 'overview' | 'io' | 'diagnostics'

const props = withDefaults(
  defineProps<{
    open: boolean
    projectId: string
    applicationName: string
    run: WorkflowRun | null
    runtimeName: string
    versionLabel: string
    canWrite?: boolean
    cancelling?: boolean
  }>(),
  {
    canWrite: false,
    cancelling: false,
  },
)

const emit = defineEmits<{
  close: []
  'cancel-run': [run: WorkflowRun]
}>()

const activeTab = ref<DetailSubTab>('overview')
const copyFeedback = ref('')
const copiedSection = ref<'id' | 'content' | null>(null)
const footerCopyFeedback = ref('')

const tabs: TabListItem[] = [
  { id: 'overview', label: '概览' },
  { id: 'io', label: '输入输出' },
  { id: 'diagnostics', label: '诊断' },
]

watch(
  () => [props.open, props.run?.workflow_run_id] as const,
  ([isOpen]) => {
    if (isOpen) {
      activeTab.value = 'overview'
      copyFeedback.value = ''
      copiedSection.value = null
      footerCopyFeedback.value = ''
    }
  },
)

const recordMode = computed(() => readRunRecordMode(props.run))
const displayRunId = computed(() => {
  const id = props.run?.workflow_run_id ?? ''
  return id.length > 26 ? `${id.slice(0, 13)}…${id.slice(-8)}` : id
})
const businessOutcome = computed(() => extractBusinessOutcome(props.run))
const summaryMetrics = computed(() => extractRunMetrics(props.run))
const failureNode = computed(() => extractRunFailureNode(props.run))
const responseBody = computed(() => extractRunResponseBody(props.run))
const responseStatusCode = computed(() => extractRunResponseStatusCode(props.run))

const hasInputPayload = computed(() => {
  const input = props.run?.input_payload
  return Boolean(input && typeof input === 'object' && Object.keys(input).length > 0)
})

const inputPreview = computed(() => formatBoundedJson(props.run?.input_payload ?? {}))
const persistedOutputs = computed(() => ({
    outputs: props.run?.outputs ?? {},
    ...(Object.keys(props.run?.template_outputs ?? {}).length > 0
      ? { template_outputs: props.run?.template_outputs }
      : {}),
}))
const hasOutputPayload = computed(() => Object.values(persistedOutputs.value).some((value) => Object.keys(value ?? {}).length > 0))
const outputPreview = computed(() => formatBoundedJson(persistedOutputs.value))

const timingEntries = computed<Array<[string, string]>>(() => {
  const meta = props.run?.metadata
  if (!meta || typeof meta !== 'object') return []
  const rawTimings = meta.timings ?? meta.execution_timings
  if (!rawTimings || typeof rawTimings !== 'object' || Array.isArray(rawTimings)) return []
  return Object.entries(rawTimings as Record<string, unknown>).map(([k, v]) => [
    k,
    typeof v === 'number' ? `${v.toFixed(2)} ms` : String(v ?? '—'),
  ])
})

const nodeRecords = computed(() =>
  Array.isArray(props.run?.node_records)
    ? (props.run?.node_records.filter((item) => item && typeof item === 'object') as Record<string, unknown>[])
    : [],
)

const diagnosticsText = computed(() =>
  JSON.stringify(
    {
      workflow_run_id: props.run?.workflow_run_id,
      state: props.run?.state,
      error: props.run?.error,
      metadata: props.run?.metadata,
      node_records: props.run?.node_records,
    },
    null,
    2,
  ),
)

async function copyText(text: string, section: 'id' | 'content' = 'content'): Promise<void> {
  copiedSection.value = section
  try {
    await navigator.clipboard.writeText(text)
    copyFeedback.value = '已复制'
    window.setTimeout(() => {
      copyFeedback.value = ''
    }, 1600)
  } catch {
    copyFeedback.value = '复制失败'
  }
}

async function copyErrorSummary(): Promise<void> {
  if (!props.run) return
  const payload = JSON.stringify(
    {
      workflow_run_id: props.run.workflow_run_id,
      state: props.run.state,
      error: props.run.error,
      failure_node: failureNode.value,
    },
    null,
    2,
  )
  await copyFooterText(payload)
}

async function copyResultSummary(): Promise<void> {
  if (!props.run) return
  await copyFooterText(outputPreview.value.fullText)
}

async function copyFooterText(text: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(text)
    footerCopyFeedback.value = '已复制'
    window.setTimeout(() => {
      footerCopyFeedback.value = ''
    }, 1600)
  } catch {
    footerCopyFeedback.value = '复制失败'
  }
}

function downloadJson(filename: string, content: string): void {
  const blob = new Blob([content], { type: 'application/json;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.click()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}
</script>

<style scoped>
.run-drawer {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.run-drawer__head {
  display: grid;
  gap: 6px;
}

.run-drawer__status-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.run-state-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 14px;
  font-weight: 700;
}

.run-state-pill.is-ok {
  color: var(--am-action-primary);
}

.run-state-pill.is-bad {
  color: #dc2626;
}

.run-state-pill.is-warn {
  color: #d97706;
}

.run-state-pill.is-neutral {
  color: var(--am-text-muted);
}

.run-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: currentColor;
}

.run-biz-pill {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 600;
}

.run-biz-pill.is-ok {
  background: var(--am-row-selected);
  color: var(--am-action-primary);
}

.run-biz-pill.is-ng {
  background: rgba(220, 38, 38, 0.12);
  color: #dc2626;
}

.run-drawer__id-row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
}

.run-muted {
  color: var(--am-text-muted);
}

.run-mono {
  font-family: var(--am-font-mono, ui-monospace, monospace);
  word-break: break-all;
}

.run-copy-mini {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: var(--am-text-muted);
  cursor: pointer;
}

.run-copy-mini:hover {
  background: var(--am-hover-surface);
  color: var(--am-text-strong);
}

.run-tab-body {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 14px;
}

.run-kv {
  margin: 0;
  display: grid;
  gap: 2px;
}

.run-kv > div {
  display: grid;
  grid-template-columns: 92px minmax(0, 1fr);
  gap: 10px;
  padding: 6px 0;
  font-size: 13px;
}

.run-kv dt {
  color: var(--am-text-muted);
}

.run-kv dd {
  margin: 0;
  color: var(--am-text-strong);
  overflow-wrap: anywhere;
}

.run-kv--compact > div {
  font-size: 12px;
  padding: 4px 0;
}

.run-failure-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.run-failure-head strong {
  font-size: 13px;
  color: var(--am-text-strong);
}

.run-failure-box {
  display: grid;
  gap: 8px;
  padding: 12px;
  border: 1px solid rgba(220, 38, 38, 0.25);
  border-radius: var(--am-radius-sm);
  background: rgba(220, 38, 38, 0.06);
}

.run-failure-node {
  font-size: 12px;
  font-weight: 600;
  color: #dc2626;
}

.run-failure-detail {
  padding: 8px 10px;
  border-radius: 6px;
  background: var(--am-surface-soft);
  color: var(--am-text-strong);
  font-family: var(--am-font-mono, ui-monospace, monospace);
  font-size: 12px;
  word-break: break-all;
}

.run-biz-incomplete {
  display: grid;
  gap: 4px;
  padding-top: 8px;
  border-top: 1px solid var(--am-border);
  font-size: 13px;
}

.run-biz-incomplete p {
  margin: 0;
  color: var(--am-text-muted);
  font-size: 12px;
}

.run-section {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 10px;
}

.run-section h4 {
  margin: 0;
  font-size: 13px;
  font-weight: 600;
  color: var(--am-text-strong);
}

.run-section__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.run-section__actions {
  display: inline-flex;
  align-items: center;
  gap: 10px;
}

.run-link-btn {
  border: none;
  background: transparent;
  padding: 0;
  font-size: 12px;
  font-weight: 500;
  color: var(--am-action-primary);
  cursor: pointer;
}

.run-link-btn:hover {
  text-decoration: underline;
}

.run-metrics-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  padding: 10px 12px;
  border: 1px solid var(--am-border);
  border-radius: var(--am-radius-sm);
  background: var(--am-surface-soft);
  text-align: center;
}

.run-metric-item {
  display: grid;
  gap: 4px;
}

.run-metric-item span {
  font-size: 12px;
  color: var(--am-text-muted);
}

.run-metric-item strong {
  font-size: 18px;
  color: var(--am-text-strong);
}

.run-metric-item strong.is-ok {
  color: var(--am-action-primary);
}

.run-metric-item strong.is-bad {
  color: #dc2626;
}

.run-minimal-notice {
  display: grid;
  gap: 4px;
  padding: 14px;
  border: 1px solid var(--am-border);
  border-radius: var(--am-radius-sm);
  background: var(--am-surface-soft);
  font-size: 12px;
  color: var(--am-text-muted);
}

.run-minimal-notice strong {
  color: var(--am-text-strong);
}

.run-tech-box {
  border: 1px solid var(--am-border);
  border-radius: var(--am-radius-sm);
  padding: 10px 12px;
  background: var(--am-surface-soft);
}

.run-tech-box summary {
  cursor: pointer;
  font-size: 13px;
  font-weight: 600;
  color: var(--am-text-strong);
}

.run-tech-box[open] .run-kv {
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px solid var(--am-border);
}

.run-json-block {
  min-width: 0;
  max-width: 100%;
  margin: 0;
  padding: 10px 12px;
  border: 1px solid var(--am-border);
  border-radius: var(--am-radius-sm);
  background: var(--am-surface-soft);
  color: var(--am-text-strong);
  font-family: var(--am-font-mono, ui-monospace, monospace);
  font-size: 12px;
  overflow-x: auto;
  max-height: 360px;
  overflow-y: auto;
}

.run-truncate-hint {
  margin: 0;
  font-size: 12px;
  color: #d97706;
}

.run-error-card {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 8px;
  padding: 12px;
  border: 1px solid rgba(220, 38, 38, 0.25);
  border-radius: var(--am-radius-sm);
  background: rgba(220, 38, 38, 0.05);
}

.run-err-msg {
  margin: 0;
  font-size: 12px;
  color: #dc2626;
  word-break: break-word;
}

.run-node-list {
  display: grid;
  gap: 6px;
}

.run-node-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 10px;
  border: 1px solid var(--am-border);
  border-radius: var(--am-radius-sm);
  font-size: 12px;
}
</style>
