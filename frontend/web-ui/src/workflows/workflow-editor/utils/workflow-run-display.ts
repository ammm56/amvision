import type { WorkflowAppRuntime, WorkflowJsonObject, WorkflowRun } from '../types'

export type WorkflowRunRecordMode = 'full' | 'minimal' | 'none'
export type BusinessOutcome = 'OK' | 'NG' | null

export interface RunSummaryMetric {
  label: string
  value: number
  tone: 'neutral' | 'ok' | 'bad'
}

export interface BoundedJsonPreview {
  text: string
  truncated: boolean
  totalLines: number
  shownLines: number
  fullText: string
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

export function formatRunStateLabel(state: string): string {
  if (state === 'running') return '执行中'
  if (state === 'queued' || state === 'dispatching' || state === 'created') return '排队中'
  if (state === 'succeeded') return '成功'
  if (state === 'failed') return '失败'
  if (state === 'timed_out') return '超时'
  if (state === 'cancelled') return '已取消'
  return state || '未知'
}

export function formatRunDetailHeaderState(state: string): string {
  if (state === 'succeeded') return '执行成功'
  if (state === 'failed') return '执行失败'
  if (state === 'timed_out') return '执行超时'
  if (state === 'cancelled') return '已取消'
  if (state === 'running') return '执行中'
  if (state === 'queued' || state === 'dispatching' || state === 'created') return '排队中'
  return state || '未知'
}

export function runStateDotTone(state: string): 'ok' | 'bad' | 'warn' | 'neutral' {
  if (state === 'succeeded') return 'ok'
  if (state === 'failed' || state === 'timed_out') return 'bad'
  if (state === 'running' || state === 'queued' || state === 'dispatching' || state === 'created') return 'warn'
  return 'neutral'
}

export function isTerminalRunState(state: string): boolean {
  return ['succeeded', 'failed', 'cancelled', 'timed_out'].includes(state)
}

export function readRuntimeRecordMode(runtime: WorkflowAppRuntime | null | undefined): WorkflowRunRecordMode {
  const execMeta = runtime?.metadata?.default_execution_metadata
  const raw = isRecord(execMeta) ? execMeta.workflow_run_record_mode : null
  return raw === 'full' || raw === 'none' ? raw : 'minimal'
}

export function readRuntimeDiagnosticsEnabled(runtime: WorkflowAppRuntime | null | undefined): boolean {
  const execMeta = runtime?.metadata?.default_execution_metadata
  if (!isRecord(execMeta)) return false
  return Boolean(execMeta.return_timing_metadata_enabled || execMeta.return_node_timings_enabled)
}

export function readRunRecordMode(
  run: WorkflowRun | null | undefined,
  fallbackRuntime?: WorkflowAppRuntime | null,
): WorkflowRunRecordMode {
  const meta = run?.metadata
  if (isRecord(meta)) {
    const direct = meta.workflow_run_record_mode
    if (direct === 'full' || direct === 'minimal' || direct === 'none') return direct
    const execMeta = meta.default_execution_metadata
    if (isRecord(execMeta)) {
      const nested = execMeta.workflow_run_record_mode
      if (nested === 'full' || nested === 'minimal' || nested === 'none') return nested
    }
  }
  return fallbackRuntime ? readRuntimeRecordMode(fallbackRuntime) : 'minimal'
}

export function formatRecordModeLabel(mode: WorkflowRunRecordMode, verbose = false): string {
  if (mode === 'full') return verbose ? '完整记录' : '完整'
  if (mode === 'none') return '不保存'
  return verbose ? '摘要记录' : '摘要'
}

export function extractRunResponseBody(run: WorkflowRun | null | undefined): WorkflowJsonObject | null {
  const outputs = run?.outputs
  if (!isRecord(outputs)) return null
  const httpResp = outputs.http_response
  if (isRecord(httpResp) && isRecord(httpResp.body)) {
    return httpResp.body as WorkflowJsonObject
  }
  return null
}

export function extractRunResponseStatusCode(run: WorkflowRun | null | undefined): number | null {
  const outputs = run?.outputs
  if (!isRecord(outputs)) return null
  const httpResp = outputs.http_response
  if (!isRecord(httpResp)) return null
  const raw = httpResp.status_code
  if (typeof raw === 'number' && Number.isFinite(raw)) return raw
  if (typeof raw === 'string' && raw.trim()) {
    const parsed = Number(raw)
    return Number.isFinite(parsed) ? parsed : null
  }
  return null
}

function collectCandidatePayloads(run: WorkflowRun): Record<string, unknown>[] {
  const candidates: Record<string, unknown>[] = []
  const body = extractRunResponseBody(run)
  if (body) candidates.push(body)
  if (isRecord(run.outputs)) {
    candidates.push(run.outputs)
    for (const val of Object.values(run.outputs)) {
      if (isRecord(val)) {
        candidates.push(val)
        if (isRecord(val.value)) candidates.push(val.value)
      }
    }
  }
  return candidates
}

function normalizeVerdictToken(raw: unknown): BusinessOutcome {
  if (typeof raw === 'boolean') return raw ? 'OK' : 'NG'
  if (typeof raw !== 'string') return null
  const upper = raw.trim().toUpperCase()
  if (upper === 'OK' || upper === 'PASS' || upper === 'PASSED') return 'OK'
  if (upper === 'NG' || upper === 'FAIL' || upper === 'FAILED') return 'NG'
  return null
}

/** 仅在执行成功时解析显式业务判定，绝不把执行失败映射为业务 NG。 */
export function extractBusinessOutcome(run: WorkflowRun | null | undefined): BusinessOutcome {
  if (!run || run.state !== 'succeeded') return null
  const keys = ['business_result', 'verdict', 'judgment', 'pass_fail', 'overall_result', 'status', 'result', 'ok', 'is_ok', 'passed']
  for (const obj of collectCandidatePayloads(run)) {
    for (const key of keys) {
      if (key in obj) {
        const verdict = normalizeVerdictToken(obj[key])
        if (verdict) return verdict
      }
    }
  }
  return null
}

/** 提取通用计数指标（如 total / ok / ng / count），无匹配字段时返回空数组。 */
export function extractRunMetrics(run: WorkflowRun | null | undefined): RunSummaryMetric[] {
  if (!run || run.state !== 'succeeded') return []
  for (const obj of collectCandidatePayloads(run)) {
    const total = typeof obj.total === 'number' ? obj.total : typeof obj.total_count === 'number' ? obj.total_count : null
    const ok = typeof obj.ok === 'number' ? obj.ok : typeof obj.ok_count === 'number' ? obj.ok_count : null
    const ng = typeof obj.ng === 'number' ? obj.ng : typeof obj.ng_count === 'number' ? obj.ng_count : null
    if (total !== null && (ok !== null || ng !== null)) {
      const metrics: RunSummaryMetric[] = [{ label: '总数', value: total, tone: 'neutral' }]
      if (ok !== null) metrics.push({ label: 'OK', value: ok, tone: 'ok' })
      if (ng !== null) metrics.push({ label: 'NG', value: ng, tone: ng > 0 ? 'bad' : 'neutral' })
      return metrics
    }
  }
  return []
}

/** 仅从显式 error.details 或 node_records 中读取失败节点/阶段证据，不从图结构猜测。 */
export function extractRunFailureNode(run: WorkflowRun | null | undefined): { label: string; detail?: string } | null {
  if (!run || (run.state !== 'failed' && run.state !== 'timed_out')) return null
  const details = run.error?.details
  if (isRecord(details)) {
    const nodeName =
      (typeof details.node_title === 'string' && details.node_title)
      || (typeof details.node_name === 'string' && details.node_name)
      || (typeof details.node_type_id === 'string' && details.node_type_id)
      || (typeof details.node_id === 'string' && details.node_id)
      || (typeof details.stage === 'string' && details.stage)
      || ''
    if (nodeName) {
      const detailText =
        (typeof details.path === 'string' && details.path)
        || (typeof details.file_path === 'string' && details.file_path)
        || (typeof details.reason === 'string' && details.reason)
        || ''
      return { label: nodeName, ...(detailText ? { detail: detailText } : {}) }
    }
  }
  if (Array.isArray(run.node_records)) {
    const failedRec = run.node_records.find(
      (rec) => isRecord(rec) && (rec.state === 'failed' || rec.status === 'failed' || Boolean(rec.error)),
    )
    if (failedRec && isRecord(failedRec)) {
      const label =
        (typeof failedRec.display_name === 'string' && failedRec.display_name)
        || (typeof failedRec.node_type_id === 'string' && failedRec.node_type_id)
        || (typeof failedRec.node_id === 'string' && failedRec.node_id)
        || ''
      if (label) return { label }
    }
  }
  return null
}

export function formatRunDuration(startedAt: string | null | undefined, finishedAt: string | null | undefined): string {
  if (!startedAt || !finishedAt) return '—'
  const startMs = Date.parse(startedAt)
  const endMs = Date.parse(finishedAt)
  if (!Number.isFinite(startMs) || !Number.isFinite(endMs) || endMs < startMs) return '—'
  const diffMs = endMs - startMs
  if (diffMs < 1000) return `${diffMs} ms`
  if (diffMs < 60_000) return `${(diffMs / 1000).toFixed(2)} s`
  const mins = Math.floor(diffMs / 60_000)
  const secs = ((diffMs % 60_000) / 1000).toFixed(1)
  return `${mins}m ${secs}s`
}

export function formatBoundedJson(value: unknown, maxLines = 2000): BoundedJsonPreview {
  const fullText = JSON.stringify(value ?? {}, null, 2) || '{}'
  const lines = fullText.split('\n')
  if (lines.length <= maxLines) {
    return {
      text: fullText,
      truncated: false,
      totalLines: lines.length,
      shownLines: lines.length,
      fullText,
    }
  }
  return {
    text: lines.slice(0, maxLines).join('\n'),
    truncated: true,
    totalLines: lines.length,
    shownLines: maxLines,
    fullText,
  }
}

export function isCapacityError(error: unknown): boolean {
  const status = (error as { status?: number })?.status
  const code = String((error as { code?: string })?.code ?? '').toLowerCase()
  const message = error instanceof Error ? error.message.toLowerCase() : String(error ?? '').toLowerCase()
  return (
    status === 429
    || status === 503
    || code.includes('capacity')
    || code.includes('busy')
    || message.includes('capacity')
    || message.includes('满载')
    || message.includes('busy')
  )
}

export function isDisconnectOrUnknownReceiptError(error: unknown): boolean {
  const status = (error as { status?: number })?.status
  if (status === 0 || status === 502 || status === 504) return true
  const message = error instanceof Error ? error.message.toLowerCase() : String(error ?? '').toLowerCase()
  return (
    message.includes('network')
    || message.includes('failed to fetch')
    || message.includes('timeout')
    || message.includes('timed out')
    || message.includes('aborted')
    || message.includes('连接失败')
    || message.includes('超时')
  )
}
