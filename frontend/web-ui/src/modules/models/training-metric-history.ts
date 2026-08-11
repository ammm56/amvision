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
      'mask_map50',
      'box_map50_95',
      'box_map50',
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
): TrainingRuntimePoint | null {
  if (
    typeof globalStep !== 'number'
    || !Number.isInteger(globalStep)
    || globalStep < 1
    || typeof timestamp !== 'string'
  ) return null
  const finiteRuntime = readFiniteRuntime(runtime)
  return Object.keys(finiteRuntime).length === 0
    ? null
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
