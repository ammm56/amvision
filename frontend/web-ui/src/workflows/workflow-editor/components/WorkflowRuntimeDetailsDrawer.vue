<template>
  <SideDrawer
    :open="open"
    title="运行实例详情"
    :close-label="t('common.close')"
    plain
    size="compact"
    @close="emit('close')"
  >
    <template v-if="runtime">
      <div class="rtd-head-sub">
        <strong>{{ runtime.display_name || '未命名实例' }}</strong>
        <span class="rtd-status" :class="`is-${statusTone}`">
          <i class="rtd-dot" />
          {{ statusLabel }}
        </span>
      </div>

      <nav class="rtd-tabs" role="tablist">
        <button
          type="button"
          role="tab"
          :class="{ 'is-active': activeTab === 'overview' }"
          :aria-selected="activeTab === 'overview'"
          @click="activeTab = 'overview'"
        >
          概览
        </button>
        <button
          type="button"
          role="tab"
          :class="{ 'is-active': activeTab === 'diagnostics' }"
          :aria-selected="activeTab === 'diagnostics'"
          @click="activeTab = 'diagnostics'"
        >
          诊断
        </button>
      </nav>

      <div v-show="activeTab === 'overview'" class="rtd-panel">
        <dl class="rtd-kv">
          <div>
            <dt>所属应用</dt>
            <dd>{{ applicationName || runtime.application_id }}</dd>
          </div>
          <div>
            <dt>运行版本</dt>
            <dd>{{ versionLabel }}</dd>
          </div>
          <div>
            <dt>目标版本</dt>
            <dd>{{ targetVersionLabel || versionLabel }}</dd>
          </div>
          <div>
            <dt>关联触发</dt>
            <dd>{{ triggerSourceCount }}</dd>
          </div>
          <div>
            <dt>{{ t('workflowEditor.appDetail.fields.requestTimeoutSeconds') }}</dt>
            <dd>{{ runtime.request_timeout_seconds }}</dd>
          </div>
          <div>
            <dt>执行记录</dt>
            <dd>{{ recordModeLabel }}</dd>
          </div>
          <div>
            <dt>返回诊断</dt>
            <dd>{{ diagnosticsLabel }}</dd>
          </div>
          <div>
            <dt>最近心跳</dt>
            <dd>{{ formatDateTime(runtime.heartbeat_at) }}</dd>
          </div>
          <div>
            <dt>最近错误</dt>
            <dd :class="{ 'is-err': Boolean(runtime.last_error) }">{{ runtime.last_error || '无' }}</dd>
          </div>
        </dl>

        <details class="rtd-tech-box">
          <summary>
            <ChevronRight :size="14" class="rtd-tech-chevron" />
            <span>技术信息</span>
          </summary>
          <dl class="rtd-kv rtd-kv--compact">
            <div>
              <dt>实例 ID</dt>
              <dd class="rtd-mono">
                <span>{{ runtime.workflow_runtime_id }}</span>
                <button
                  type="button"
                  class="rtd-copy"
                  title="复制实例 ID"
                  @click="copyText(runtime.workflow_runtime_id)"
                >
                  <Copy :size="12" />
                </button>
              </dd>
            </div>
            <div>
              <dt>修订次数</dt>
              <dd>{{ runtime.revision_generation }}</dd>
            </div>
            <div>
              <dt>期望状态</dt>
              <dd>{{ desiredStateLabel }}</dd>
            </div>
            <div>
              <dt>创建时间</dt>
              <dd>{{ formatDateTime(runtime.created_at) }}</dd>
            </div>
            <div>
              <dt>更新时间</dt>
              <dd>{{ formatDateTime(runtime.updated_at) }}</dd>
            </div>
          </dl>
        </details>
      </div>

      <div v-show="activeTab === 'diagnostics'" class="rtd-panel">
        <div v-if="runtime.observed_state === 'failed' || runtime.last_error" class="rtd-diag-alert">
          <AlertCircle :size="16" class="rtd-diag-alert__icon" />
          <div>
            <strong>{{ runtime.observed_state === 'failed' ? '实例运行异常' : '最近错误记录' }}</strong>
            <p>{{ runtime.last_error || '实例未进入正常状态' }}</p>
            <div class="rtd-diag-meta">
              <span>检查时间：{{ formatDateTime(runtime.heartbeat_at || runtime.updated_at) }}</span>
              <span>目标版本：{{ targetVersionLabel || versionLabel }}</span>
            </div>
          </div>
        </div>
        <div v-else class="rtd-diag-ok">
          <div>
            <strong>健康状态：{{ statusLabel }}</strong>
            <small>最近检查：{{ formatDateTime(runtime.heartbeat_at || runtime.updated_at) }}</small>
          </div>
          <Button size="sm" variant="secondary" @click="emit('refresh-health', runtime)">
            <RefreshCw :size="13" />
            刷新诊断
          </Button>
        </div>

        <details class="rtd-tech-box" open>
          <summary>原始诊断</summary>
          <pre class="rtd-json">{{ healthJsonText }}</pre>
        </details>
      </div>
    </template>

    <template v-if="runtime" #footer>
      <Button variant="secondary" @click="emit('close')">关闭</Button>
      <Button
        v-if="activeTab === 'overview' && canWrite && isEditable"
        variant="secondary"
        data-runtime-edit-config
        @click="emit('edit-config', runtime)"
      >
        编辑配置
      </Button>
      <Button
        v-if="activeTab === 'overview'"
        variant="primary"
        @click="emit('monitor', runtime)"
      >
        运行监视
      </Button>
      <Button
        v-else
        variant="secondary"
        @click="copyText(diagnosticBundleText)"
      >
        复制诊断
      </Button>
    </template>
  </SideDrawer>
</template>

<script setup lang="ts">
import { AlertCircle, ChevronRight, Copy, RefreshCw } from '@lucide/vue'
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import { formatSystemDateTime } from '@/shared/formatters/date-time'
import Button from '@/shared/ui/components/Button.vue'
import SideDrawer from '@/shared/ui/components/SideDrawer.vue'
import type { WorkflowAppRuntime, WorkflowJsonObject } from '../types'

const props = withDefaults(
  defineProps<{
    open: boolean
    runtime: WorkflowAppRuntime | null
    applicationName?: string
    versionLabel: string
    targetVersionLabel?: string
    triggerSourceCount: number
    canWrite?: boolean
    initialTab?: 'overview' | 'diagnostics'
  }>(),
  {
    applicationName: '',
    targetVersionLabel: '',
    canWrite: false,
    initialTab: 'overview',
  },
)

const emit = defineEmits<{
  close: []
  'edit-config': [runtime: WorkflowAppRuntime]
  monitor: [runtime: WorkflowAppRuntime]
  'refresh-health': [runtime: WorkflowAppRuntime]
}>()

const { t } = useI18n()
const activeTab = ref<'overview' | 'diagnostics'>('overview')

watch(
  () => [props.open, props.initialTab] as const,
  ([isOpen, tab]) => {
    if (isOpen) {
      activeTab.value = tab || 'overview'
    }
  },
  { immediate: true },
)

const statusTone = computed<'ok' | 'bad' | 'warn' | 'neutral'>(() => {
  const s = props.runtime?.observed_state
  if (s === 'running') return 'ok'
  if (s === 'failed') return 'bad'
  if (s === 'starting' || s === 'stopping') return 'warn'
  return 'neutral'
})

const statusLabel = computed(() => {
  const s = props.runtime?.observed_state
  if (s === 'running') return '运行中'
  if (s === 'stopped') return '已停止'
  if (s === 'failed') return '启动失败'
  if (s === 'starting') return '启动中'
  if (s === 'stopping') return '停止中'
  return s || '未知'
})

const desiredStateLabel = computed(() => {
  const s = props.runtime?.desired_state
  if (s === 'running') return '运行中'
  if (s === 'stopped') return '已停止'
  return s || '—'
})

const isEditable = computed(
  () => props.runtime?.observed_state === 'stopped' || props.runtime?.observed_state === 'failed',
)

const defaultExecMeta = computed<WorkflowJsonObject>(() => {
  const raw = props.runtime?.metadata?.default_execution_metadata
  return typeof raw === 'object' && raw !== null && !Array.isArray(raw) ? (raw as WorkflowJsonObject) : {}
})

const recordModeLabel = computed(() => {
  const mode = defaultExecMeta.value.workflow_run_record_mode
  if (mode === 'full') return '完整'
  if (mode === 'minimal') return '摘要'
  if (mode === 'none') return '不保存'
  return '—'
})

const diagnosticsLabel = computed(() => {
  const val = defaultExecMeta.value.return_timing_metadata_enabled ?? defaultExecMeta.value.return_node_timings_enabled
  if (typeof val === 'boolean') return val ? '开启' : '关闭'
  return '关闭'
})

const healthJsonText = computed(() => {
  if (!props.runtime) return '{}'
  return Object.keys(props.runtime.health_summary).length > 0
    ? JSON.stringify(props.runtime.health_summary, null, 2)
    : '{}'
})

const diagnosticBundleText = computed(() =>
  props.runtime
    ? JSON.stringify(
        {
          workflow_runtime_id: props.runtime.workflow_runtime_id,
          observed_state: props.runtime.observed_state,
          last_error: props.runtime.last_error,
          health_summary: props.runtime.health_summary,
        },
        null,
        2,
      )
    : '{}',
)

function formatDateTime(value: string | null | undefined): string {
  return value ? formatSystemDateTime(value) : '—'
}

async function copyText(value: string): Promise<void> {
  if (!value || typeof navigator === 'undefined' || !navigator.clipboard) return
  try {
    await navigator.clipboard.writeText(value)
  } catch {
    // ignore
  }
}
</script>

<style scoped>
.rtd-head-sub {
  display: flex;
  align-items: center;
  gap: 12px;
  padding-bottom: 10px;
}

.rtd-head-sub strong {
  font-size: 15px;
  color: var(--am-text-strong);
}

.rtd-status {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 500;
}

.rtd-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}

.rtd-status.is-ok {
  color: var(--am-action-primary);
}

.rtd-status.is-ok .rtd-dot {
  background: var(--am-action-primary);
}

.rtd-status.is-bad {
  color: #dc2626;
}

.rtd-status.is-bad .rtd-dot {
  background: #dc2626;
}

.rtd-status.is-warn {
  color: #d97706;
}

.rtd-status.is-warn .rtd-dot {
  background: #f59e0b;
}

.rtd-status.is-neutral {
  color: var(--am-text-muted);
}

.rtd-status.is-neutral .rtd-dot {
  background: var(--am-text-muted);
}

.rtd-tabs {
  display: flex;
  gap: 18px;
  border-bottom: 1px solid var(--am-border);
  margin-bottom: 12px;
}

.rtd-tabs button {
  padding: 8px 2px;
  border: none;
  border-bottom: 2px solid transparent;
  background: transparent;
  color: var(--am-text-muted);
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
}

.rtd-tabs button.is-active {
  color: var(--am-text-strong);
  border-bottom-color: var(--am-brand-primary);
  font-weight: 600;
}

.rtd-panel {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 12px;
}

.rtd-kv {
  margin: 0;
  display: grid;
  gap: 2px;
}

.rtd-kv > div {
  display: grid;
  grid-template-columns: 88px minmax(0, 1fr);
  align-items: start;
  gap: 10px;
  padding: 7px 0;
  font-size: 13px;
}

.rtd-kv--compact > div {
  padding: 5px 0;
}

.rtd-kv dt {
  color: var(--am-text-muted);
}

.rtd-kv dd {
  margin: 0;
  color: var(--am-text-strong);
  overflow-wrap: anywhere;
}

.rtd-kv dd.is-err {
  color: #dc2626;
}

.rtd-mono {
  display: flex !important;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  font-family: var(--am-font-mono);
  font-size: 12px;
}

.rtd-copy {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border: none;
  border-radius: 4px;
  background: transparent;
  color: var(--am-text-muted);
  cursor: pointer;
  flex: none;
}

.rtd-copy:hover {
  background: var(--am-hover-surface);
  color: var(--am-text-strong);
}

.rtd-tech-box {
  min-width: 0;
  border: 1px solid var(--am-border);
  border-radius: 8px;
  padding: 10px 12px;
  background: var(--am-surface-soft);
}

.rtd-tech-box summary {
  display: flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  list-style: none;
  font-size: 13px;
  font-weight: 600;
  color: var(--am-text-strong);
}

.rtd-tech-box summary::-webkit-details-marker {
  display: none;
}

.rtd-tech-chevron {
  color: var(--am-text-muted);
  transition: transform 140ms ease;
}

.rtd-tech-box[open] .rtd-tech-chevron {
  transform: rotate(90deg);
}

.rtd-tech-box[open] .rtd-kv {
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px solid var(--am-border);
}

.rtd-diag-alert {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 12px;
  border: 1px solid color-mix(in srgb, #dc2626 40%, transparent);
  border-radius: 8px;
  background: color-mix(in srgb, #dc2626 6%, var(--am-surface));
}

.rtd-diag-alert__icon {
  color: #dc2626;
  flex: none;
  margin-top: 2px;
}

.rtd-diag-alert strong {
  display: block;
  font-size: 14px;
  color: #dc2626;
}

.rtd-diag-alert p {
  margin: 4px 0 8px;
  font-size: 13px;
  color: var(--am-text-strong);
}

.rtd-diag-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  font-size: 12px;
  color: var(--am-text-muted);
}

.rtd-diag-ok {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 10px 12px;
  border: 1px solid var(--am-border);
  border-radius: 8px;
  background: var(--am-surface-soft);
}

.rtd-diag-ok strong {
  display: block;
  font-size: 13px;
  color: var(--am-text-strong);
}

.rtd-diag-ok small {
  font-size: 12px;
  color: var(--am-text-muted);
}

.rtd-json {
  min-width: 0;
  max-width: 100%;
  margin: 8px 0 0;
  padding: 10px;
  border-radius: 6px;
  background: var(--am-code-surface);
  color: var(--am-code-text);
  font-family: var(--am-font-mono);
  font-size: 12px;
  overflow: auto;
  max-height: 280px;
}
</style>
