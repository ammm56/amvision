import { formatSmallModelNumber } from './model-number-format'
import type { DetectionEvaluationReport, DetectionEvaluationTask } from './services/model-evaluation.service'

export type EvaluationComparisonRow = { task: DetectionEvaluationTask; report: DetectionEvaluationReport['payload'] }
export const comparisonMetrics = ['map50_95', 'map50'] as const

export function comparisonScope({ task, report }: EvaluationComparisonRow) {
  return {
    exportId: task.dataset_export_id || null,
    version: task.dataset_version_id || null,
    split: report.split_name ?? task.report_summary.split_name ?? task.split_name ?? null,
    count: report.sample_count ?? task.report_summary.sample_count ?? null,
    failed: report.coverage?.failed ?? task.report_summary.coverage?.failed ?? 0,
    unprocessed: report.coverage?.unprocessed ?? task.report_summary.coverage?.unprocessed ?? 0,
    score: report.score_threshold ?? task.score_threshold ?? null,
    nms: report.nms_threshold !== undefined ? report.nms_threshold : task.model_type === 'yolo26' ? null : task.nms_threshold ?? null,
  }
}

function classScope(row: EvaluationComparisonRow): string {
  return JSON.stringify(row.report.per_class_metrics?.map(({ class_id, class_name, gt_count }) =>
    [class_id, class_name, gt_count] as const).sort((a, b) => a[0] - b[0]) ?? [])
}

export function comparisonConflicts(rows: EvaluationComparisonRow[]) {
  const [first, ...others] = rows
  if (!first || !others.length) return []
  const a = comparisonScope(first)
  const categories = classScope(first)
  return others.flatMap((row, index) => {
    const b = comparisonScope(row)
    const reasons: Array<{ kind: 'partial' | 'missing' | 'dataset' | 'samples' | 'rules' | 'classes'; a?: string; b?: string }> = []
    if ([a, b].some(scope => !scope.exportId || !scope.split || scope.count == null || !Number.isInteger(scope.count) || scope.count <= 0 || !Number.isFinite(scope.score))
      || !first.report.per_class_metrics?.length || !row.report.per_class_metrics?.length) reasons.push({ kind: 'missing' })
    if (a.failed > 0 || b.failed > 0 || a.unprocessed > 0 || b.unprocessed > 0) reasons.push({ kind: 'partial' })
    if (a.exportId !== b.exportId || (a.version && b.version && a.version !== b.version)) reasons.push({ kind: 'dataset', a: a.exportId !== b.exportId ? a.exportId ?? '—' : a.version!, b: a.exportId !== b.exportId ? b.exportId ?? '—' : b.version! })
    if (a.split !== b.split || a.count !== b.count) reasons.push({ kind: 'samples', a: `${a.split ?? '—'} · ${a.count ?? '—'}`, b: `${b.split ?? '—'} · ${b.count ?? '—'}` })
    if (a.score !== b.score || a.nms !== b.nms) reasons.push({ kind: 'rules', a: describeComparisonRules(a, true), b: describeComparisonRules(b, true) })
    if (categories !== classScope(row)) reasons.push({ kind: 'classes' })
    return reasons.length ? [{ row, index: index + 1, reasons }] : []
  })
}

export function evaluationClassMean(row: EvaluationComparisonRow): number | undefined {
  const classes = row.report.per_class_metrics?.filter(item => item.gt_count > 0) ?? []
  if (!classes.length || classes.some(item => !Number.isFinite(item.ap50_95))) return undefined
  return classes.reduce((total, item) => total + item.ap50_95, 0) / classes.length
}

export function evaluationRuntime({ task, report }: EvaluationComparisonRow): string {
  // 历史目标检测评估通过 ModelVersion 加载原始权重。
  const backend = report.execution?.runtime_backend ?? task.progress.runtime_backend ?? 'pytorch'
  const precision = report.execution?.runtime_precision ?? task.progress.runtime_precision
  const names: Record<string, string> = { pytorch: 'PyTorch', onnx: 'ONNX', onnxruntime: 'ONNX Runtime', tensorrt: 'TensorRT', openvino: 'OpenVINO' }
  return [names[backend.toLowerCase()] ?? backend, precision?.toUpperCase()].filter(Boolean).join(' ')
}

export function evaluationInputDescription(row: EvaluationComparisonRow): string {
  const execution = row.report.execution
  const spec = execution?.model_input_spec
  const size = execution?.input_size
  const sizeText = size && Number.isInteger(size.width) && Number.isInteger(size.height) ? `${size.width} × ${size.height}` : ''
  return [sizeText, spec?.color_space, spec?.preprocess, spec?.normalization].filter(value => typeof value === 'string' && value).join(' · ')
}

export function describeComparisonRules(scope: ReturnType<typeof comparisonScope>, exact = false): string {
  const rule = (value: number | null) => value == null ? '—' : exact ? String(value) : formatSmallModelNumber(value)
  return `score ${rule(scope.score)} · NMS ${rule(scope.nms)}`
}

export function evaluationMetric(value: number | null | undefined): string {
  return typeof value === 'number' && Number.isFinite(value) ? value.toFixed(3) : '—'
}

export function evaluationDelta(value: number | undefined, baseline: number | undefined) {
  if (value === undefined || baseline === undefined || !Number.isFinite(value) || !Number.isFinite(baseline)) return { text: '—', tone: '' }
  const delta = Number((value - baseline).toFixed(3))
  return { text: `${delta > 0 ? '+' : ''}${delta.toFixed(3)}`, tone: delta > 0 ? 'positive' : delta < 0 ? 'negative' : '' }
}
