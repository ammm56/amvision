import type { ModelTrainingTaskDetail, PlatformBaseModelVersionSummary } from './services/model.service'

type ModelMetricTask = Pick<ModelTrainingTaskDetail, 'state' | 'model_version_id' | 'best_metric_name' | 'best_metric_value' | 'training_summary'>

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
}

function positiveInteger(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isInteger(value) && value > 0 ? value : undefined
}

export function modelVersionMetric(version: PlatformBaseModelVersionSummary, task: ModelMetricTask | null, report?: unknown) {
  const training = task?.state === 'succeeded' && task.model_version_id === version.model_version_id ? task : null
  const saved = record(version.metadata.metrics_summary)
  const file = record(report)
  const hasSavedMetric = typeof saved.best_metric_name === 'string' && saved.best_metric_name
    && typeof saved.best_metric_value === 'number' && Number.isFinite(saved.best_metric_value)
  const name = hasSavedMetric ? saved.best_metric_name : (training?.best_metric_name ?? file.best_metric_name)
  const value = hasSavedMetric ? saved.best_metric_value : (training?.best_metric_value ?? file.best_metric_value)
  if (typeof name !== 'string' || !name || typeof value !== 'number' || !Number.isFinite(value)) return null

  const validation = record(training?.training_summary.validation_metrics_payload)
  const trainingConfig = record(version.metadata.training_config)
  const maxEpochs = positiveInteger(trainingConfig.max_epochs) ?? positiveInteger(training?.training_summary.max_epochs)
    ?? positiveInteger(file.max_epochs)
  const trainingMatchesMetric = training?.best_metric_name === name && training?.best_metric_value === value
  const fileMatchesMetric = file.best_metric_name === name && file.best_metric_value === value
  let epoch = positiveInteger(hasSavedMetric ? saved.best_epoch : undefined)
    ?? positiveInteger(trainingMatchesMetric ? validation.best_epoch : undefined)
    ?? positiveInteger(fileMatchesMetric ? file.best_epoch : undefined)
  for (const source of [validation, file]) {
    if (epoch !== undefined || !Array.isArray(source.epoch_history)) continue
    const key = name.replace(/^val[_/]/, '')
    const evaluatedEpochs = Array.isArray(source.evaluated_epochs) ? source.evaluated_epochs : []
    const matchingEpochs = new Set<number>()
    for (const [index, item] of source.epoch_history.entries()) {
      const point = record(item)
      const measured = point[name] ?? point[key] ?? point[`val_${key}`]
      const measuredEpoch = positiveInteger(point.epoch) ?? positiveInteger(evaluatedEpochs[index])
      if (measured === value && measuredEpoch !== undefined) matchingEpochs.add(measuredEpoch)
    }
    if (matchingEpochs.size === 1) [epoch] = matchingEpochs
  }
  if (epoch !== undefined && maxEpochs !== undefined && epoch > maxEpochs) epoch = undefined
  return { name, value, epoch, maxEpochs }
}
