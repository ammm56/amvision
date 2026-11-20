import type { ConversionTargetKey, Int8SampleSettings, ModelConversionTaskDetail, TensorRtInt8Settings, TensorRtShape } from './services/model.service'

export function conversionRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
}

export function readConversionTarget(task: ModelConversionTaskDetail): ConversionTargetKey | undefined {
  const formats = task.requested_target_formats?.length ? task.requested_target_formats : task.target_formats
  if (formats.length !== 1) return undefined
  const options = conversionRecord(task.task_spec?.extra_options)
  switch (formats[0]) {
    case 'onnx': return 'onnx'
    case 'onnx-optimized': return 'onnx-optimized'
    case 'openvino-ir':
      if (options.openvino_ir_precision === 'int8') return 'openvino-ir-int8'
      return options.openvino_ir_precision === 'fp16' ? 'openvino-ir-fp16' : 'openvino-ir-fp32'
    case 'tensorrt-engine':
      if (options.tensorrt_engine_precision === 'int8') return 'tensorrt-engine-int8'
      return options.tensorrt_engine_precision === 'fp16' ? 'tensorrt-engine-fp16' : 'tensorrt-engine-fp32'
  }
}

const formatLabels: Record<ConversionTargetKey, string> = {
  onnx: 'ONNX', 'onnx-optimized': 'ONNX (optimized)',
  'openvino-ir-fp32': 'OpenVINO IR FP32', 'openvino-ir-fp16': 'OpenVINO IR FP16', 'openvino-ir-int8': 'OpenVINO IR INT8',
  'tensorrt-engine-fp32': 'TensorRT FP32', 'tensorrt-engine-fp16': 'TensorRT FP16', 'tensorrt-engine-int8': 'TensorRT INT8',
}

export function conversionFormatName(format: string, zh: boolean): string {
  const labels: Record<string, string> = { onnx: 'ONNX', 'onnx-optimized': zh ? 'ONNX（优化）' : 'ONNX (optimized)', 'openvino-ir': 'OpenVINO', 'tensorrt-engine': 'TensorRT' }
  return labels[format] ?? format
}

export function conversionTargetLabel(task: ModelConversionTaskDetail, zh: boolean): string {
  const target = readConversionTarget(task)
  if (target === 'onnx-optimized' && zh) return 'ONNX（优化）'
  return target ? formatLabels[target] : task.target_formats.join(' / ') || '—'
}

export function readConversionInt8Samples(options: Record<string, unknown>): Int8SampleSettings | undefined {
  function sample(value: unknown) {
    const source = conversionRecord(value)
    return typeof source.dataset_export_id === 'string' && source.dataset_export_id && typeof source.sample_count === 'number' && Number.isInteger(source.sample_count) && source.sample_count > 0
      ? { dataset_export_id: source.dataset_export_id, sample_count: source.sample_count } : undefined
  }
  const calibration = sample(options.int8_calibration), validation = sample(options.int8_validation)
  return calibration && validation ? { int8_calibration: calibration, int8_validation: validation } : undefined
}

export function readConversionInt8Settings(options: Record<string, unknown>): TensorRtInt8Settings | undefined {
  function shape(value: unknown): TensorRtShape | undefined {
    return Array.isArray(value) && value.length === 4 && value.every(number => Number.isInteger(number) && number > 0)
      ? [value[0], value[1], value[2], value[3]] : undefined
  }
  const profile = conversionRecord(options.input_profile)
  const min = shape(profile.min), opt = shape(profile.opt), max = shape(profile.max)
  const samples = readConversionInt8Samples(options)
  const workspace = options.workspace_gib
  if (!min || !opt || !max || !samples || typeof workspace !== 'number' || !Number.isFinite(workspace) || workspace <= 0) return undefined
  return { input_profile: { min, opt, max }, ...samples, workspace_gib: workspace }
}

type ConversionStageState = 'done' | 'failed' | 'cancelled' | 'skipped' | 'unknown' | 'running' | 'waiting'

interface ConversionStage {
  kind: string
  state: ConversionStageState
  startedAt?: string
  endedAt?: string
}

export function readConversionStages(task: ModelConversionTaskDetail, failedValidation?: 'validate-tensorrt' | 'validate-openvino') {
  const planned = task.task_spec?.planned_steps
  const stages = Array.isArray(planned) ? planned.flatMap((step: unknown) => {
    const kind = conversionRecord(step).kind
    return typeof kind === 'string' && kind ? [kind] : []
  }) : []
  const recorded = task.report_summary.executed_step_kinds
  const done = new Set(Array.isArray(recorded) ? recorded.filter((item): item is string => typeof item === 'string') : [])
  let failure = -1
  let knownValidationOrder = false
  if (failedValidation) {
    const buildIndex = stages.indexOf(failedValidation === 'validate-openvino' ? 'build-openvino-ir' : 'build-tensorrt-engine')
    // 转换子进程先生成文件再校验，当前计划把两个动作收在构建步骤中。
    failure = stages.indexOf(failedValidation)
    knownValidationOrder = failure >= 0 || buildIndex >= 0
    if (failure === -1) {
      failure = buildIndex === -1 ? stages.length : buildIndex + 1
      stages.splice(failure, 0, failedValidation)
    }
  }
  const active = ['queued', 'running', 'pending'].includes(task.state)
  const targetBuild = task.builds.find(build => task.target_formats.includes(build.build_format))
  const buildValidation = conversionRecord(targetBuild?.metadata?.runtime_smoke)
  const reportValidation = conversionRecord(task.report_summary.validation_summary)
  const validationKind = buildValidation.stage ?? reportValidation.stage
  if (task.state === 'succeeded' && typeof validationKind === 'string' && validationKind && !stages.includes(validationKind)) {
    stages.push(validationKind)
    done.add(validationKind)
  }
  stages.push('register-artifact')
  const attemptId = [...task.events].reverse().find(event => event.attempt_id)?.attempt_id
  const events = task.events.filter(event => event.attempt_id === attemptId || !attemptId)
  const dates = new Map<string, { startedAt?: string; endedAt?: string }>()
  for (const event of events) {
    const progress = conversionRecord(event.payload.progress)
    if (typeof progress.stage !== 'string') continue
    if (progress.stage_state === 'running') dates.set(progress.stage, { startedAt: event.created_at })
    if (progress.stage_state === 'done') {
      dates.set(progress.stage, { ...dates.get(progress.stage), endedAt: event.created_at })
      done.add(progress.stage)
    }
  }
  const eventStage = events.map(event => conversionRecord(event.payload.progress).stage)
    .reverse().find((stage): stage is string => typeof stage === 'string' && stages.includes(stage))
  let progressStage = typeof task.progress.stage === 'string' && stages.includes(task.progress.stage)
    ? task.progress.stage : eventStage
  if (!progressStage && !failedValidation && task.state !== 'succeeded') {
    const planning = events.find(event => conversionRecord(event.payload.progress).stage === 'planning')
    if (planning) {
      progressStage = 'prepare-conversion'
      stages.unshift(progressStage)
      dates.set(progressStage, { startedAt: planning.created_at })
    }
  }
  const currentIndex = typeof progressStage === 'string' ? stages.indexOf(progressStage) : -1
  function stageState(kind: string, index: number): ConversionStageState {
    if (index === failure) return 'failed'
    if (kind === 'register-artifact' && task.builds.length) return 'done'
    if (knownValidationOrder) return index < failure ? 'done' : 'skipped'
    if (done.has(kind)) return 'done'
    if (currentIndex >= 0 && index < currentIndex) return 'done'
    if (active) {
      if (index === currentIndex) return 'running'
      return task.state !== 'running' || currentIndex >= 0 ? 'waiting' : 'unknown'
    }
    if (currentIndex >= 0 && index === currentIndex) {
      if (task.state === 'cancelled') return 'cancelled'
      if (task.state === 'failed' || task.state === 'timed_out') return 'failed'
    }
    if (kind === 'register-artifact' || !task.started_at || (currentIndex >= 0 && index > currentIndex)) {
      return 'skipped'
    }
    return 'unknown'
  }
  return stages.map((kind, index): ConversionStage => {
    const state = stageState(kind, index)
    const { startedAt, endedAt } = dates.get(kind) ?? {}
    const finishedWithTask = state === 'failed' || state === 'cancelled' || (kind === 'register-artifact' && state === 'done')
    return { kind, state, startedAt, endedAt: endedAt ?? (finishedWithTask ? task.finished_at ?? undefined : undefined) }
  })
}

export function conversionElapsedTime(started: string | null | undefined, finished: string | null | undefined, locale: string): string {
  const elapsed = Date.parse(finished ?? '') - Date.parse(started ?? '')
  if (!Number.isFinite(elapsed) || elapsed < 0) return '—'
  const seconds = Math.round(elapsed / 1000)
  const units: [number, Intl.NumberFormatOptions['unit']][] = [
    [Math.floor(seconds / 3600), 'hour'], [Math.floor(seconds / 60) % 60, 'minute'], [seconds % 60, 'second'],
  ]
  return units.filter(([value, unit]) => value > 0 || (seconds === 0 && unit === 'second'))
    .map(([value, unit]) => new Intl.NumberFormat(locale, { style: 'unit', unit, unitDisplay: 'short' }).format(value)).join(' ')
}
