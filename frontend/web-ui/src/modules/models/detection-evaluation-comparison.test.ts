import { describe, expect, it } from 'vitest'
import { comparisonConflicts, comparisonScope, evaluationClassMean, evaluationDelta, evaluationInputDescription, evaluationMetric, evaluationRuntime, type EvaluationComparisonRow } from './detection-evaluation-comparison'

function row(id: string): EvaluationComparisonRow {
  const category = (class_id: number, class_name: string, gt_count: number) => ({
    class_id, class_name, gt_count, pred_count: 0, ap50: 0, ap50_95: 0, precision: 0, recall: 0, f1: 0,
  })
  return {
    task: { task_id: id, display_name: id, project_id: 'project', model_type: 'yolo11', model_version_id: id,
      dataset_export_id: 'export', dataset_version_id: 'v3', created_at: '', state: 'succeeded', progress: {},
      report_summary: { split_name: 'test', sample_count: 61 }, score_threshold: 0.25, nms_threshold: 0.7 },
    report: { per_class_metrics: [category(0, 'barcode', 42), category(1, 'qrcode', 50)] },
  }
}

describe('detection evaluation comparison', () => {
  it('matches archived task settings and ignores serialization order of class rows', () => {
    const a = row('a'), b = row('b')
    b.report.per_class_metrics?.reverse()
    expect(comparisonScope(a)).toMatchObject({ split: 'test', count: 61, score: 0.25, nms: 0.7 })
    expect(comparisonConflicts([a, b])).toEqual([])
  })

  it('identifies different datasets, sample scopes, thresholds and annotations', () => {
    const a = row('a'), b = row('b'), c = row('c')
    b.task.dataset_export_id = 'other-export'
    b.report.split_name = 'val'
    b.report.score_threshold = 0.123456
    b.report.per_class_metrics![0].gt_count++
    c.task.dataset_export_id = undefined
    c.report.sample_count = 0
    const conflicts = comparisonConflicts([a, b, c])
    expect(conflicts[0].reasons.map(reason => reason.kind)).toEqual(['dataset', 'samples', 'rules', 'classes'])
    expect(conflicts[0].reasons[2].b).toContain('0.123456')
    expect(conflicts[1].reasons[0].kind).toBe('missing')
  })

  it('rejects comparison of a partial report even when the scored sample counts match', () => {
    const a = row('a'), b = row('b')
    b.report.coverage = { requested: 62, succeeded: 61, failed: 1, unprocessed: 0 }
    expect(comparisonConflicts([a, b])[0].reasons.map(reason => reason.kind)).toContain('partial')
  })

  it('uses report execution metadata and keeps unavailable historical details empty', () => {
    const a = row('a')
    expect(evaluationRuntime(a)).toBe('PyTorch')
    expect(evaluationInputDescription(a)).toBe('')
    a.report.execution = { runtime_backend: 'tensorrt', runtime_precision: 'fp16', input_size: { width: 640, height: 384 } }
    a.report.nms_threshold = null
    expect(evaluationRuntime(a)).toBe('TensorRT FP16')
    expect(evaluationInputDescription(a)).toBe('640 × 384')
    expect(comparisonScope(a).nms).toBeNull()
    expect(comparisonConflicts([a, row('b')])[0].reasons.map(reason => reason.kind)).toEqual(['rules'])
  })

  it('averages measured classes and includes AP zero for a class with annotations', () => {
    const a = row('a')
    a.report.map50_95 = 0.99
    a.report.per_class_metrics![0].ap50_95 = 0.309257
    expect(evaluationClassMean(a)).toBeCloseTo(0.1546285)
    a.report.per_class_metrics![1].gt_count = 0
    expect(evaluationClassMean(a)).toBeCloseTo(0.309257)
    a.report.per_class_metrics = []
    expect(evaluationClassMean(a)).toBeUndefined()
    expect(comparisonConflicts([a, row('b')])[0].reasons.map(reason => reason.kind)).toContain('missing')
  })

  it('formats display values and subtracts before rounding', () => {
    expect(evaluationMetric(0.243321)).toBe('0.243')
    expect(evaluationMetric(null)).toBe('—')
    expect(evaluationDelta(0.243321, 0.154629)).toEqual({ text: '+0.089', tone: 'positive' })
    expect(evaluationDelta(0.154629, 0.243321)).toEqual({ text: '-0.089', tone: 'negative' })
    expect(evaluationDelta(0.243121, 0.243321)).toEqual({ text: '0.000', tone: '' })
    expect(evaluationDelta(undefined, 0.154629).text).toBe('—')
  })
})
