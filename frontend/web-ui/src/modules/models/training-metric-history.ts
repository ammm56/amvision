import type { ModelTaskType } from './services/model.service'

export interface TrainingMetricPoint {
  epoch: number
  metrics: Record<string, number>
}

export interface TrainingScalarPoint {
  epoch: number
  value: number
}

export interface TrainingRuntimePoint {
  globalStep: number
  timestamp: string
  runtime: Record<string, number>
  attemptNo?: number
}

export interface TrainingMetricCapability {
  trainMetrics: readonly string[]
  validationMetrics: readonly string[]
}

const HISTORY_LIMIT = 2_000

const COMMON_SPATIAL_TRAIN_METRICS = [
  'loss',
  'class_loss',
  'box_loss',
  'dfl_loss',
  'l1_loss',
] as const

const METRIC_CAPABILITIES: Record<ModelTaskType, TrainingMetricCapability> = {
  detection: {
    trainMetrics: COMMON_SPATIAL_TRAIN_METRICS,
    validationMetrics: ['map50_95', 'map50', 'loss'],
  },
  classification: {
    trainMetrics: ['loss', 'accuracy', 'top1_accuracy', 'top5_accuracy'],
    validationMetrics: ['top1_accuracy', 'top5_accuracy', 'accuracy', 'loss'],
  },
  segmentation: {
    trainMetrics: [...COMMON_SPATIAL_TRAIN_METRICS, 'mask_loss', 'seg_loss'],
    validationMetrics: [
      'mask_map50_95',
      'val/segm_mAP_50_95',
      'mask_map50',
      'val/segm_mAP_50',
      'box_map50_95',
      'bbox_map50_95',
      'box_map50',
      'bbox_map50',
      'map50_95',
      'map50',
      'loss',
    ],
  },
  pose: {
    trainMetrics: [...COMMON_SPATIAL_TRAIN_METRICS, 'kpt_loss', 'pose_loss', 'kobj_loss'],
    validationMetrics: [
      'oks_ap50_95',
      'oks_ap50',
      'bbox_map50_95',
      'bbox_map50',
      'map50_95',
      'map50',
      'loss',
    ],
  },
  obb: {
    trainMetrics: [...COMMON_SPATIAL_TRAIN_METRICS, 'angle_loss'],
    validationMetrics: ['map50_95', 'map50', 'rotated_map50_95', 'rotated_map50', 'loss'],
  },
}

export function getTrainingMetricCapability(taskType: ModelTaskType): TrainingMetricCapability {
  return METRIC_CAPABILITIES[taskType]
}

const VALIDATION_METRIC_LABELS: Readonly<Record<string, string>> = {
  top1_accuracy: 'Top-1 Accuracy',
  top5_accuracy: 'Top-5 Accuracy',
  accuracy: 'Accuracy',
  map50_95: 'mAP50–95',
  map50: 'mAP50',
  mask_map50_95: 'Mask mAP50–95',
  mask_map50: 'Mask mAP50',
  segm_map_50_95: 'Mask mAP50–95',
  segm_map_50: 'Mask mAP50',
  oks_ap50_95: 'OKS AP50–95',
  oks_ap50: 'OKS AP50',
  rotated_map50_95: 'Rotated mAP50–95',
  rotated_map50: 'Rotated mAP50',
  box_map50_95: 'Box mAP50–95',
  box_map50: 'Box mAP50',
  bbox_map50_95: 'Box mAP50–95',
  bbox_map50: 'Box mAP50',
}

export function formatTrainingMetricLabel(
  name: string,
  taskType: ModelTaskType | null = null,
  history: readonly TrainingMetricPoint[] = [],
): string {
  const key = name.replace(/^val[_/]/, '').replace(/^ema_/, '').toLowerCase()
  if (key === 'map_50_95' || key === 'map_50') {
    const label = key === 'map_50_95' ? 'mAP50–95' : 'mAP50'
    return taskType === 'segmentation' ? `Box ${label}` : label
  }
  if (key !== 'map50_95' && key !== 'map50') return VALIDATION_METRIC_LABELS[key] ?? name

  const label = VALIDATION_METRIC_LABELS[key]
  if (taskType === 'obb') return `Rotated ${label}`
  if (taskType === 'pose') return `Box ${label}`
  if (taskType !== 'segmentation') return label

  // 旧 YOLO 分割任务用 map50_95 保存主指标。有掩膜真值时这一列来自 Mask AP。
  const maskKey = `mask_${key}`
  const recorded = history.filter(({ metrics }) => Number.isFinite(metrics[maskKey]))
  if (!recorded.length) return label
  return recorded.some(({ metrics }) => metrics[key] !== undefined && metrics[key] !== metrics[maskKey])
    ? `Box ${label}`
    : `Mask ${label}`
}

export function appendTrainingMetricPoint(
  history: readonly TrainingMetricPoint[],
  point: TrainingMetricPoint | null,
): TrainingMetricPoint[] {
  if (point === null || point.epoch < 1 || Object.keys(point.metrics).length === 0) {
    return [...history]
  }
  const nextHistory = history.filter((item) => item.epoch !== point.epoch)
  nextHistory.push(point)
  nextHistory.sort((left, right) => left.epoch - right.epoch)
  return nextHistory.slice(-HISTORY_LIMIT)
}

export function appendTrainingScalarPoint(
  history: readonly TrainingScalarPoint[],
  point: TrainingScalarPoint | null,
): TrainingScalarPoint[] {
  if (point === null || point.epoch < 1 || !Number.isFinite(point.value)) {
    return [...history]
  }
  const nextHistory = history.filter((item) => item.epoch !== point.epoch)
  nextHistory.push(point)
  nextHistory.sort((left, right) => left.epoch - right.epoch)
  return nextHistory.slice(-HISTORY_LIMIT)
}

export function appendTrainingRuntimePoint(
  history: readonly TrainingRuntimePoint[],
  point: TrainingRuntimePoint | null,
): TrainingRuntimePoint[] {
  if (point === null || point.globalStep < 1 || Object.keys(point.runtime).length === 0) {
    return [...history]
  }
  const nextHistory = history.filter((item) => item.globalStep !== point.globalStep)
  nextHistory.push(point)
  nextHistory.sort((left, right) => left.globalStep - right.globalStep)
  return nextHistory.slice(-HISTORY_LIMIT)
}

export function buildRuntimePoint(
  globalStep: unknown,
  timestamp: unknown,
  runtime: unknown,
  attemptNo?: unknown,
): TrainingRuntimePoint | null {
  if (
    typeof globalStep !== 'number'
    || !Number.isInteger(globalStep)
    || globalStep < 1
    || typeof timestamp !== 'string'
  ) return null
  const finiteRuntime = readFiniteRuntime(runtime)
  if (Object.keys(finiteRuntime).length === 0) return null
  return typeof attemptNo === 'number' && Number.isInteger(attemptNo) && attemptNo >= 0
    ? { globalStep, timestamp, runtime: finiteRuntime, attemptNo }
    : { globalStep, timestamp, runtime: finiteRuntime }
}

export function buildMetricPointFromProgress(
  progress: Record<string, unknown>,
  fieldName: 'train_metrics' | 'validation_metrics',
): TrainingMetricPoint | null {
  const epoch = readEpoch(progress)
  const metrics = readFiniteMetrics(progress[fieldName])
  return epoch === null || Object.keys(metrics).length === 0 ? null : { epoch, metrics }
}

export function buildLearningRatePointFromProgress(
  progress: Record<string, unknown>,
): TrainingScalarPoint | null {
  const epoch = readEpoch(progress)
  const learningRate = progress.learning_rate
  if (epoch === null || typeof learningRate !== 'number' || !Number.isFinite(learningRate)) {
    return null
  }
  return { epoch, value: learningRate }
}

export function readPersistedMetricHistory(payload: Record<string, unknown>): TrainingMetricPoint[] {
  const rawHistory = readRawHistory(payload)
  const evaluatedEpochs = Array.isArray(payload.evaluated_epochs)
    ? payload.evaluated_epochs
    : []
  return rawHistory.reduce<TrainingMetricPoint[]>((history, item, index) => {
    const record = readRecord(item)
    const evaluatedEpoch = evaluatedEpochs[index]
    const epoch = readEpoch(record)
      ?? (typeof evaluatedEpoch === 'number' && Number.isInteger(evaluatedEpoch) && evaluatedEpoch >= 1
        ? evaluatedEpoch
        : index + 1)
    const metrics = readFiniteMetrics(record)
    return appendTrainingMetricPoint(
      history,
      epoch === null ? null : { epoch, metrics },
    )
  }, [])
}

export function readLegacyRfdetrMetricHistory(payload: Record<string, unknown>): {
  train: TrainingMetricPoint[]
  validation: TrainingMetricPoint[]
} {
  if (payload.implementation_mode !== 'rfdetr-full-core') return { train: [], validation: [] }

  const epochs = new Map<number, Record<string, number>>()
  for (const item of readRawHistory(payload)) {
    const row = readRecord(item)
    if (typeof row.epoch !== 'string' || !/^\d+$/.test(row.epoch)) continue
    const epoch = Number(row.epoch) + 1
    if (!Number.isSafeInteger(epoch)) continue
    const metrics = epochs.get(epoch) ?? {}
    for (const [key, value] of Object.entries(row)) {
      if (key !== 'train/loss_epoch' && key !== 'train/loss' && !key.startsWith('val/')) continue
      if (typeof value !== 'string' || !value.trim()) continue
      const parsed = Number(value)
      if (Number.isFinite(parsed)) metrics[key] = parsed
    }
    epochs.set(epoch, metrics)
  }

  const train: TrainingMetricPoint[] = []
  const validation: TrainingMetricPoint[] = []
  for (const [epoch, metrics] of [...epochs].sort(([left], [right]) => left - right).slice(-HISTORY_LIMIT)) {
    const loss = metrics['train/loss_epoch'] ?? metrics['train/loss']
    if (loss !== undefined) train.push({ epoch, metrics: { loss } })
    const validationMetrics = Object.fromEntries(Object.entries(metrics).filter(([key]) => key.startsWith('val/')))
    if (Object.keys(validationMetrics).length) validation.push({ epoch, metrics: validationMetrics })
  }
  return { train, validation }
}

export function readPersistedLearningRateHistory(
  payload: Record<string, unknown>,
): TrainingScalarPoint[] {
  return readRawHistory(payload).reduce<TrainingScalarPoint[]>((history, item, index) => {
    const record = readRecord(item)
    const normalizedRecord = readEpoch(record) === null
      ? { ...record, epoch: index + 1 }
      : record
    return appendTrainingScalarPoint(
      history,
      buildLearningRatePointFromProgress(normalizedRecord),
    )
  }, [])
}

export function readPersistedRuntimeHistory(
  payload: Record<string, unknown>,
): TrainingRuntimePoint[] {
  const rawHistory = Array.isArray(payload.runtime_history)
    ? payload.runtime_history
    : []
  return rawHistory.reduce<TrainingRuntimePoint[]>((history, item) => {
    const record = readRecord(item)
    return appendTrainingRuntimePoint(
      history,
      buildRuntimePoint(
        record.global_step,
        record.timestamp,
        record.runtime,
        record.attempt_no,
      ),
    )
  }, [])
}

export function readOrderedMetricNames(
  history: readonly TrainingMetricPoint[],
  preferredNames: readonly string[],
  includeAdditionalMetrics = true,
): string[] {
  const discoveredNames = new Set<string>()
  history.forEach((point) => Object.keys(point.metrics).forEach((name) => discoveredNames.add(name)))
  const preferred = preferredNames.filter((name) => discoveredNames.delete(name))
  return includeAdditionalMetrics
    ? [...preferred, ...Array.from(discoveredNames).sort()]
    : preferred
}

function readEpoch(record: Record<string, unknown>): number | null {
  const epoch = record.epoch
  if (typeof epoch === 'number' && Number.isInteger(epoch) && epoch >= 1) {
    return epoch
  }
  const epochIndex = record.epoch_index
  if (typeof epochIndex === 'number' && Number.isInteger(epochIndex) && epochIndex >= 0) {
    return epochIndex + 1
  }
  return null
}

function readRawHistory(payload: Record<string, unknown>): unknown[] {
  if (Array.isArray(payload.epoch_history)) return payload.epoch_history
  if (Array.isArray(payload.history)) return payload.history
  return []
}

function readFiniteMetrics(value: unknown): Record<string, number> {
  const record = readRecord(value)
  return Object.fromEntries(
    Object.entries(record).filter((entry): entry is [string, number] => (
      !['epoch', 'epoch_index', 'learning_rate'].includes(entry[0])
      && typeof entry[1] === 'number'
      && Number.isFinite(entry[1])
    )),
  )
}

function readFiniteRuntime(value: unknown): Record<string, number> {
  const record = readRecord(value)
  return Object.fromEntries(
    Object.entries(record).filter((entry): entry is [string, number] => (
      typeof entry[1] === 'number' && Number.isFinite(entry[1])
    )),
  )
}

function readRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {}
}
