import { computed, reactive, ref, watch, type ComputedRef, type Ref } from 'vue'

import type {
  ModelTrainingTaskDetail,
  ModelTaskType,
  PlatformBaseModelDetail,
  TrainingParameterSchemaItem,
} from '../services/model.service'
import {
  getDefaultTrainingModelParameterValues,
  getModelLayerTrainingFields,
  isTrainingAugmentationField,
  supportsTrainingWarmStart,
  type TrainingParameterValues,
} from '../training-parameter-support'

type SelectValue = string | number | boolean | null

export function savedTrainingText(value: unknown): string {
  return typeof value === 'string' ? value.trim() : ''
}

function selectValueToString(value: SelectValue): string {
  return typeof value === 'string' ? value : String(value ?? '')
}

function normalizeText(value: string | null | undefined): string {
  return String(value ?? '').trim().toLowerCase()
}

function resolveOptimizerLearningRate(optimizer: string): string {
  return ['adam', 'adamw', 'nadam', 'radam'].includes(normalizeText(optimizer))
    ? '0.001'
    : '0.01'
}

function alignPositiveDimension(value: number, divisor: number): number {
  const normalized = Math.max(1, Math.trunc(Number(value) || 0))
  return Math.ceil(normalized / divisor) * divisor
}

function resolveRfdetrInputDivisor(
  taskType: ModelTaskType,
  modelTypeValue: string,
  modelScaleValue: string,
): number {
  if (normalizeText(modelTypeValue) !== 'rfdetr') {
    return 1
  }
  const scale = normalizeText(modelScaleValue)
  if (taskType === 'detection') {
    return scale === 'base' ? 56 : 32
  }
  if (taskType === 'segmentation') {
    return scale === 'nano' ? 12 : 24
  }
  return 1
}

export function useTrainingParameters(options: {
  selectedTaskType: Ref<ModelTaskType>
  resolvedTrainingModelType: ComputedRef<string>
  resolvedTrainingModelScale: ComputedRef<string>
  trainingParameterSchema: ComputedRef<TrainingParameterSchemaItem | null>
  isOutputModelNameTaken?: (name: string) => boolean
  translate: (key: string, params?: Record<string, string>) => string
}) {
  const outputModelName = ref('')
  const trainingRecipeId = ref('default')
  const lastSuggestedOutputModelName = ref('')
  const maxEpochs = ref(100)
  const batchMode = ref<'auto' | 'fixed'>('auto')
  const batchSize = ref(16)
  const batchTargetMemoryFraction = ref(0.6)
  const batchMinimumSize = ref(1)
  const batchMaximumSize = ref<number | undefined>(undefined)
  const batchRecoverOnOom = ref(true)
  const batchMaxOomRetries = ref(3)
  const trainingDevice = ref('')
  const evaluationInterval = ref(5)
  const ampMode = ref<'auto' | 'enabled' | 'disabled'>('auto')
  const ampDtype = ref<'auto' | 'fp16' | 'bf16'>('auto')
  const checkpointInterval = ref(5)
  const checkpointKeepPeriodic = ref(2)
  const inputWidth = ref(640)
  const inputHeight = ref(640)
  const trainingDisplayName = ref('')
  const trainingModelParameterValues = reactive<TrainingParameterValues>({})
  const trainingAugmentationEnabled = ref(true)

  function applySavedTrainingParameters(task: ModelTrainingTaskDetail, device: string): () => void {
    const restore: (() => void)[] = []
    function apply<T>(field: Ref<T>, value: T): void {
      const original = field.value
      restore.push(() => { field.value = original })
      field.value = value
    }
    function number(value: unknown, fallback: number): number {
      return typeof value === 'number' && Number.isFinite(value) ? value : fallback
    }
    const spec = task.task_spec
    const extra = spec.extra_options as Record<string, unknown> | undefined ?? {}
    const input = spec.input_size as { width?: number; height?: number } | null | undefined
    const originalParameters = { ...trainingModelParameterValues }
    restore.push(() => Object.assign(trainingModelParameterValues, originalParameters))
    apply(outputModelName, savedTrainingText(spec.output_model_name) || task.output_model_name || '')
    apply(trainingDisplayName, '')
    apply(trainingRecipeId, savedTrainingText(spec.recipe_id) || task.recipe_id || 'default')
    apply(maxEpochs, number(spec.max_epochs, maxEpochs.value))
    apply(inputWidth, number(input?.width, inputWidth.value))
    apply(inputHeight, number(input?.height, inputHeight.value))
    apply(batchMode, extra.batch_mode === 'fixed' || (extra.batch_mode !== 'auto' && number(spec.batch_size, 0) > 0) ? 'fixed' : 'auto')
    apply(batchSize, number(spec.batch_size, batchSize.value) > 0 ? number(spec.batch_size, batchSize.value) : batchSize.value)
    apply(batchTargetMemoryFraction, number(extra.batch_target_memory_fraction, batchTargetMemoryFraction.value))
    apply(batchMinimumSize, number(extra.batch_minimum_size, batchMinimumSize.value))
    apply(batchMaximumSize, typeof extra.batch_maximum_size === 'number' ? extra.batch_maximum_size : undefined)
    apply(batchRecoverOnOom, typeof extra.batch_recover_on_oom === 'boolean' ? extra.batch_recover_on_oom : batchRecoverOnOom.value)
    apply(batchMaxOomRetries, number(extra.batch_oom_max_retries, batchMaxOomRetries.value))
    const precision = savedTrainingText(spec.precision) || task.precision
    const legacyAmp = precision === 'fp32' ? 'disabled' : precision === 'fp16' || precision === 'bf16' ? 'enabled' : 'auto'
    apply(ampMode, extra.amp_mode === 'enabled' || extra.amp_mode === 'disabled' || extra.amp_mode === 'auto' ? extra.amp_mode : legacyAmp)
    const dtype = extra.amp_dtype ?? precision
    apply(ampDtype, dtype === 'fp16' || dtype === 'bf16' ? dtype : 'auto')
    apply(checkpointInterval, number(extra.checkpoint_interval, checkpointInterval.value))
    apply(checkpointKeepPeriodic, number(extra.checkpoint_keep_periodic, checkpointKeepPeriodic.value))
    apply(evaluationInterval, number(spec.evaluation_interval ?? extra.evaluation_interval ?? task.evaluation_interval, evaluationInterval.value))
    apply(trainingDevice, device)
    apply(trainingAugmentationEnabled, extra.disable_augmentation !== true)

    const parameters = { ...extra }
    for (const key of ['mosaic_scale', 'mixup_scale']) {
      const range = extra[key]
      if (!Array.isArray(range) || range.length !== 2) continue
      parameters[`${key}_min`] ??= range[0]
      parameters[`${key}_max`] ??= range[1]
    }
    for (const key of Object.keys(trainingModelParameterValues)) {
      const value = parameters[key]
      if (typeof value === 'string' || typeof value === 'boolean' || typeof value === 'number' && Number.isFinite(value)) {
        trainingModelParameterValues[key] = String(value)
      }
    }
    return () => restore.forEach(reset => reset())
  }

  const trainingTaskSupportsWarmStart = computed(
    () => supportsTrainingWarmStart(options.selectedTaskType.value),
  )
  const allTrainingModelParameterFields = computed(
    () => {
      if (!options.resolvedTrainingModelType.value || !options.trainingParameterSchema.value) {
        return []
      }
      return getModelLayerTrainingFields(
        options.selectedTaskType.value,
        options.resolvedTrainingModelType.value,
        options.trainingParameterSchema.value,
      )
    },
  )
  const trainingModelParameterFields = computed(
    () => allTrainingModelParameterFields.value.filter((field) => !isTrainingAugmentationField(field)),
  )
  const trainingAugmentationParameterFields = computed(
    () => allTrainingModelParameterFields.value.filter(isTrainingAugmentationField),
  )
  const trainingSupportsAugmentationToggle = computed(
    () => trainingAugmentationParameterFields.value.length > 0,
  )
  const trainingModelParameterSectionTitle = computed(() => {
    if (!options.resolvedTrainingModelType.value) {
      return options.translate('modelOps.trainingParameters.advanced')
    }
    const taskKey = `taskKinds.tasks.${options.selectedTaskType.value}`
    const translatedTask = options.translate(taskKey)
    const localizedTaskType = translatedTask === taskKey ? options.selectedTaskType.value : translatedTask
    return options.translate('modelOps.trainingParameters.advancedForModel', {
      taskType: localizedTaskType,
      modelType: options.resolvedTrainingModelType.value,
    })
  })

  function buildSuggestedOutputModelName(
    model: Pick<PlatformBaseModelDetail, 'model_name' | 'model_type' | 'model_scale'>,
    datasetName: string,
  ): string {
    const family = (model.model_type || model.model_name).trim().toUpperCase()
    const scales: Record<string, string> = { nano: 'n', small: 's', medium: 'm', large: 'l', 'extra-large': 'x' }
    const scale = model.model_scale.trim()
    const variant = scale ? `${family}-${scales[scale] ?? scale}` : family
    const dataset = datasetName.trim().replace(/^dataset-([\w-]+)[-_]\d{8,}$/i, '$1')
    const title = /^dataset-(?:export-)?[a-f0-9]{12,}$/i.test(dataset) ? '' : dataset
    return [title.slice(0, 80), variant].filter(Boolean).join(' ').slice(0, 128)
  }

  function syncSuggestedOutputModelName(
    model: Pick<PlatformBaseModelDetail, 'model_name' | 'model_type' | 'model_scale'>,
    datasetName = '',
  ): void {
    const currentValue = outputModelName.value.trim()
    if (currentValue && currentValue !== lastSuggestedOutputModelName.value) {
      return
    }
    const title = buildSuggestedOutputModelName(model, datasetName)
    let nextValue = title
    for (let index = 2; options.isOutputModelNameTaken?.(nextValue); index += 1) {
      const suffix = ` · ${index}`
      nextValue = title.slice(0, 128 - suffix.length) + suffix
    }
    outputModelName.value = nextValue
    lastSuggestedOutputModelName.value = nextValue
  }

  function resetSuggestedOutputModelName(): void {
    outputModelName.value = ''
    lastSuggestedOutputModelName.value = ''
  }

  function setBatchMode(value: SelectValue): void {
    batchMode.value = selectValueToString(value) === 'fixed' ? 'fixed' : 'auto'
  }

  function setAmpMode(value: SelectValue): void {
    const normalized = selectValueToString(value)
    ampMode.value = normalized === 'enabled' || normalized === 'disabled' ? normalized : 'auto'
  }

  function setAmpDtype(value: SelectValue): void {
    const normalized = selectValueToString(value)
    ampDtype.value = normalized === 'fp16' || normalized === 'bf16' ? normalized : 'auto'
  }

  function setTrainingDevice(value: SelectValue): void {
    trainingDevice.value = selectValueToString(value)
  }

  function setTrainingModelParameterValue(key: string, value: SelectValue): void {
    const nextValue = selectValueToString(value)
    if (key === 'optimizer') {
      const previousOptimizer = trainingModelParameterValues.optimizer ?? 'auto'
      const previousDefault = resolveOptimizerLearningRate(previousOptimizer)
      const currentLearningRate = trainingModelParameterValues.learning_rate ?? ''
      trainingModelParameterValues.optimizer = nextValue
      if (!currentLearningRate || currentLearningRate === previousDefault) {
        trainingModelParameterValues.learning_rate = resolveOptimizerLearningRate(nextValue)
      }
      return
    }
    trainingModelParameterValues[key] = nextValue
  }

  function alignTrainingInputSizeForSubmit(): { width: number; height: number } {
    const divisor = resolveRfdetrInputDivisor(
      options.selectedTaskType.value,
      options.resolvedTrainingModelType.value,
      options.resolvedTrainingModelScale.value,
    )
    if (divisor <= 1) {
      return {
        width: inputWidth.value,
        height: inputHeight.value,
      }
    }
    return {
      width: alignPositiveDimension(inputWidth.value, divisor),
      height: alignPositiveDimension(inputHeight.value, divisor),
    }
  }

  watch(
    [
      options.selectedTaskType,
      options.resolvedTrainingModelType,
      options.trainingParameterSchema,
    ],
    ([taskType, modelType, parameterSchema], [previousTaskType, previousModelType, previousSchema]) => {
      const sameModel = taskType === previousTaskType && modelType === previousModelType && Boolean(previousSchema && parameterSchema)
      const defaultValues = modelType && parameterSchema
        ? getDefaultTrainingModelParameterValues(taskType, modelType, parameterSchema)
        : {}
      const visibleKeys = new Set(Object.keys(defaultValues))
      for (const key of Object.keys(trainingModelParameterValues)) {
        if (!visibleKeys.has(key)) {
          delete trainingModelParameterValues[key]
        }
      }
      for (const [key, value] of Object.entries(defaultValues)) {
        if (!sameModel || !(key in trainingModelParameterValues)) trainingModelParameterValues[key] = value
      }
      if (!sameModel) {
        trainingAugmentationEnabled.value = true
      }
    },
    { immediate: true },
  )

  return {
    outputModelName,
    trainingRecipeId,
    applySavedTrainingParameters,
    maxEpochs,
    batchMode,
    batchSize,
    batchTargetMemoryFraction,
    batchMinimumSize,
    batchMaximumSize,
    batchRecoverOnOom,
    batchMaxOomRetries,
    trainingDevice,
    evaluationInterval,
    ampMode,
    ampDtype,
    checkpointInterval,
    checkpointKeepPeriodic,
    inputWidth,
    inputHeight,
    trainingDisplayName,
    trainingModelParameterValues,
    trainingAugmentationEnabled,
    trainingTaskSupportsWarmStart,
    trainingModelParameterFields,
    trainingAugmentationParameterFields,
    trainingSupportsAugmentationToggle,
    trainingModelParameterSectionTitle,
    setBatchMode,
    setAmpMode,
    setAmpDtype,
    setTrainingDevice,
    setTrainingModelParameterValue,
    syncSuggestedOutputModelName,
    resetSuggestedOutputModelName,
    alignTrainingInputSizeForSubmit,
  }
}
