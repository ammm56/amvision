import type { ModelTrainingTaskDetail } from './services/model.service'

/** 读取已完成轮次，批次遥测中的当前轮次不能作为完成依据。 */
export function readCompletedTrainingEpoch(progress: unknown): number | null {
  if (!progress || typeof progress !== 'object') return null
  if ('completed_epoch' in progress && typeof progress.completed_epoch === 'number'
    && Number.isInteger(progress.completed_epoch) && progress.completed_epoch >= 0) {
    return progress.completed_epoch
  }
  if ('granularity' in progress && progress.granularity === 'batch') return null
  if ('epoch' in progress && typeof progress.epoch === 'number' && Number.isInteger(progress.epoch)
    && progress.epoch > 0 && (
      ('granularity' in progress && progress.granularity === 'epoch')
      || ('train_metrics' in progress && progress.train_metrics && typeof progress.train_metrics === 'object')
    )) {
    return progress.epoch
  }
  return null
}

/** 用同一次尝试的完整轮次估算剩余耗时，并计入按周期执行的验证。 */
export function estimateTrainingRemainingSeconds(
  events: ModelTrainingTaskDetail['events'],
  attempt: number,
  completed: number,
  total: number,
  evaluationInterval?: number | null,
): number | null {
  if (total <= completed) return null
  const times = new Map<number, { time: number; validated: boolean }>()
  for (const event of events) {
    if (event.event_type !== 'progress' || (event.payload.attempt_no ?? 1) !== attempt) continue
    const progress = event.payload.progress
    const epoch = readCompletedTrainingEpoch(progress)
    if (epoch === null || epoch <= 0 || epoch > completed || epoch < completed - 24) continue
    const time = Date.parse(event.created_at)
    const previous = times.get(epoch)
    if (Number.isFinite(time) && (!previous || time < previous.time)) {
      const validated = Boolean(progress && typeof progress === 'object'
        && 'validation_ran' in progress && progress.validation_ran === true)
      times.set(epoch, { time, validated })
    }
  }

  const samples = [...times].sort(([left], [right]) => left - right)
  const durations: number[] = []
  const trainingDurations: number[] = []
  const validationDurations: number[] = []
  for (let index = 1; index < samples.length; index += 1) {
    const [previousEpoch, previous] = samples[index - 1]
    const [epoch, current] = samples[index]
    const duration = (current.time - previous.time) / 1000
    if (duration <= 0) continue
    durations.push(duration / (epoch - previousEpoch))
    if (epoch === previousEpoch + 1) {
      (current.validated ? validationDurations : trainingDurations).push(duration)
    }
  }
  if (durations.length < 3) return null

  const remaining = total - completed
  if (evaluationInterval && Number.isInteger(evaluationInterval) && evaluationInterval > 1
    && validationDurations.length >= 2 && trainingDurations.length >= 3) {
    // 最后一轮会验证，训练与验证外的最终产物整理由页面单独提示。
    const validationRounds = Math.floor(total / evaluationInterval) - Math.floor(completed / evaluationInterval)
      + (total % evaluationInterval === 0 ? 0 : 1)
    const trainingTime = averageEpochDuration(trainingDurations)
    const validationTime = Math.max(trainingTime, averageEpochDuration(validationDurations))
    return trainingTime * (remaining - validationRounds) + validationTime * validationRounds
  }
  return averageEpochDuration(durations) * remaining
}

function averageEpochDuration(durations: number[]): number {
  if (durations.length < 6) return durations.reduce((sum, value) => sum + value, 0) / durations.length
  const ordered = [...durations].sort((left, right) => left - right)
  const median = ordered[Math.floor(ordered.length / 2)]
  return durations.reduce((sum, value) => sum + Math.min(value, median * 2), 0) / durations.length
}
