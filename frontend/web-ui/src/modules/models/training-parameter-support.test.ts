import { describe, expect, it } from 'vitest'

import {
  buildTrainingParameters,
  buildTrainingDeviceOptions,
  getDefaultTrainingModelParameterValues,
  getModelLayerTrainingFields,
  isTrainingAugmentationField,
  isTrainingAugmentationParameterDisabled,
  isTrainingModelParameterDisabled,
  normalizeTrainingParameterNumber,
  validateTrainingModelLayerValues,
} from './training-parameter-support'
import type {
  ModelTaskType,
  TrainingParameterSchemaItem,
} from './services/model.service'

function fieldKeys(taskType: ModelTaskType, modelType: string): string[] {
  return getModelLayerTrainingFields(taskType, modelType).map((field) => field.key)
}

function augmentationFieldKeys(taskType: ModelTaskType, modelType: string): string[] {
  return getModelLayerTrainingFields(taskType, modelType)
    .filter(isTrainingAugmentationField)
    .map((field) => field.key)
}

function defaultValues(taskType: ModelTaskType, modelType: string): Record<string, string> {
  return getDefaultTrainingModelParameterValues(taskType, modelType)
}

const supportedTrainingPairs: ReadonlyArray<readonly [ModelTaskType, string]> = [
  ['detection', 'yolox'],
  ['detection', 'yolov8'],
  ['detection', 'yolo11'],
  ['detection', 'yolo26'],
  ['detection', 'rfdetr'],
  ['classification', 'yolov8'],
  ['classification', 'yolo11'],
  ['classification', 'yolo26'],
  ['segmentation', 'yolov8'],
  ['segmentation', 'yolo11'],
  ['segmentation', 'yolo26'],
  ['segmentation', 'rfdetr'],
  ['pose', 'yolov8'],
  ['pose', 'yolo11'],
  ['pose', 'yolo26'],
  ['obb', 'yolov8'],
  ['obb', 'yolo11'],
  ['obb', 'yolo26'],
]

function buildSchemaItem(
  taskType: ModelTaskType,
  modelType: string,
  overrides: Record<string, Partial<TrainingParameterSchemaItem['numeric_fields'][number]>> = {},
): TrainingParameterSchemaItem {
  const fields = getModelLayerTrainingFields(taskType, modelType)
  return {
    task_type: taskType,
    model_type: modelType,
    schema_name: `${taskType}-${modelType}`,
    parameter_schema: {},
    default_parameters: {},
    capabilities: {
      postprocess_mode: modelType === 'yolo26' ? 'end_to_end' : 'nms',
      supports_nms_threshold: modelType !== 'yolo26',
      distribution_loss_name: modelType === 'yolo26' ? 'l1_loss' : 'dfl_loss',
      augmentation_families: ['hsv', 'mosaic', 'mixup', 'affine', 'multi_scale'],
      best_metric_name: 'map50_95',
      best_metric_direction: 'maximize',
    },
    numeric_fields: fields
      .filter((field) => field.inputKind === 'number')
      .map((field) => ({
        key: field.key,
        schema_path: field.key,
        value_kind: field.valueKind as 'int' | 'float',
        minimum: field.min!,
        maximum: field.max!,
        step: field.step!,
        decimals: 0,
        default_value: Number(field.defaultValue),
        ...overrides[field.key],
      })),
  }
}

describe('training parameter augmentation support', () => {
  it('keeps every numeric default valid under native HTML constraints', () => {
    const invalidDefaults: string[] = []
    for (const [taskType, modelType] of supportedTrainingPairs) {
      for (const field of getModelLayerTrainingFields(taskType, modelType)) {
        if (field.inputKind !== 'number' || !field.defaultValue) continue
        const input = document.createElement('input')
        input.type = 'number'
        if (field.min !== undefined) input.min = String(field.min)
        if (field.max !== undefined) input.max = String(field.max)
        if (field.step !== undefined) input.step = String(field.step)
        input.value = field.defaultValue
        if (!input.checkValidity()) {
          invalidDefaults.push(
            `${taskType}/${modelType}/${field.key}: ${input.validationMessage}`,
          )
        }
      }
    }

    expect(invalidDefaults).toEqual([])
  })

  it('uses explicit hundredth steps for positive YOLO scale ranges', () => {
    const scaleKeys = new Set([
      'mosaic_scale_min',
      'mosaic_scale_max',
      'mixup_scale_min',
      'mixup_scale_max',
    ])
    for (const [taskType, modelType] of supportedTrainingPairs) {
      for (const field of getModelLayerTrainingFields(taskType, modelType)) {
        if (!scaleKeys.has(field.key)) continue
        expect(field.min, `${taskType}/${modelType}/${field.key}`).toBe(0.01)
        expect(field.step, `${taskType}/${modelType}/${field.key}`).toBe(0.01)
      }
    }
  })

  it('uses backend numeric specs as the rendered constraint source', () => {
    const schema = buildSchemaItem('detection', 'yolo26', {
      hsv_h: {
        minimum: 0.02,
        maximum: 0.5,
        step: 0.02,
        decimals: 2,
        default_value: 0.02,
      },
    })
    const field = getModelLayerTrainingFields('detection', 'yolo26', schema)
      .find((item) => item.key === 'hsv_h')!

    expect(field).toMatchObject({
      min: 0.02,
      max: 0.5,
      step: 0.02,
      defaultValue: '0.02',
    })
  })

  it('rejects a backend numeric catalog that does not cover the rendered form', () => {
    const schema = buildSchemaItem('detection', 'yolo26')
    schema.numeric_fields = schema.numeric_fields.filter((field) => field.key !== 'hsv_h')

    expect(() => getModelLayerTrainingFields('detection', 'yolo26', schema))
      .toThrow('训练参数目录缺少数值字段')
  })

  it('builds training device options from backend device diagnostics', () => {
    expect(buildTrainingDeviceOptions(null)).toEqual([
      { label: '自动选择（默认）', value: '' },
      { label: 'cpu', value: 'cpu' },
    ])
    expect(
      buildTrainingDeviceOptions({
        gpu: {
          available: true,
          devices: [{ name: 'GPU 0' }, { name: 'GPU 1' }],
        },
        cuda: { available: true },
      }),
    ).toEqual([
      { label: '自动选择（默认）', value: '' },
      { label: 'cpu', value: 'cpu' },
      { label: 'cuda', value: 'cuda' },
      { label: 'cuda:0', value: 'cuda:0' },
      { label: 'cuda:1', value: 'cuda:1' },
    ])
  })

  it('does not expose fake indexed CUDA devices when only CUDA availability is known', () => {
    expect(buildTrainingDeviceOptions({ cuda: { available: true } })).toEqual([
      { label: '自动选择（默认）', value: '' },
      { label: 'cpu', value: 'cpu' },
    ])
  })

  it('exposes YOLOX detection augmentation fields', () => {
    expect(augmentationFieldKeys('detection', 'yolox')).toEqual(
      expect.arrayContaining([
        'flip_prob',
        'hsv_prob',
        'mosaic_prob',
        'mixup_prob',
        'enable_mixup',
        'multiscale_range',
        'no_aug_epochs',
      ]),
    )
  })

  it('exposes RF-DETR augmentation presets only for supported RF-DETR tasks', () => {
    for (const taskType of ['detection', 'segmentation'] as const) {
      expect(augmentationFieldKeys(taskType, 'rfdetr')).toEqual([
        'rfdetr_augmentation_preset',
        'scale_jitter',
        'augmentation_backend',
      ])
      expect(fieldKeys(taskType, 'rfdetr')).toContain('learning_rate')
    }
  })

  it('exposes ordinary YOLO augmentation fields for detection, segmentation, pose and OBB', () => {
    for (const taskType of ['detection', 'segmentation', 'pose', 'obb'] as const) {
      for (const modelType of ['yolov8', 'yolo11', 'yolo26']) {
        expect(augmentationFieldKeys(taskType, modelType)).toEqual(
          expect.arrayContaining([
            'flip_prob',
            'hsv_h',
            'hsv_s',
            'hsv_v',
            'mosaic_prob',
            'mixup_prob',
            'affine_prob',
            'close_mosaic',
            'multi_scale',
          ]),
        )
      }
    }
  })

  it('uses an explicit optimizer for every ordinary YOLO task', () => {
    for (const taskType of ['detection', 'classification', 'segmentation', 'pose', 'obb'] as const) {
      for (const modelType of ['yolov8', 'yolo11', 'yolo26']) {
        expect(fieldKeys(taskType, modelType)).toContain('optimizer')
        expect(defaultValues(taskType, modelType).optimizer).toBe('auto')
      }
    }
  })

  it('does not submit stale NMS values for YOLO26 end-to-end tasks', () => {
    for (const taskType of ['detection', 'segmentation', 'pose', 'obb'] as const) {
      const values = defaultValues(taskType, 'yolo26')
      values.evaluation_nms_threshold = '0.5'
      const parameters = buildTrainingParameters(taskType, 'yolo26', values, {
        parameterSchema: buildSchemaItem(taskType, 'yolo26'),
      })

      expect(parameters.evaluation).not.toHaveProperty('nms_threshold')
    }
  })

  it('labels the third box regression loss from model capabilities', () => {
    const yolo26Field = getModelLayerTrainingFields(
      'detection',
      'yolo26',
      buildSchemaItem('detection', 'yolo26'),
    ).find((field) => field.key === 'l1_loss_weight')
    const yolo11Field = getModelLayerTrainingFields(
      'detection',
      'yolo11',
      buildSchemaItem('detection', 'yolo11'),
    ).find((field) => field.key === 'dfl_loss_weight')

    expect(yolo26Field?.label).toBe('L1 框回归损失权重')
    expect(yolo11Field?.label).toBe('DFL 损失权重')
    expect(fieldKeys('detection', 'yolo26')).not.toContain('dfl_loss_weight')
  })

  it('uses the reference box gain as the default YOLO mask gain', () => {
    for (const modelType of ['yolov8', 'yolo11', 'yolo26']) {
      const values = defaultValues('segmentation', modelType)
      expect(values.box_loss_weight).toBe('7.5')
      expect(values.mask_loss_weight).toBe('7.5')
      expect(buildTrainingParameters('segmentation', modelType, values)).toMatchObject({
        loss: { box_weight: 7.5, mask_weight: 7.5 },
      })
    }
  })

  it('does not submit an Auto placeholder learning rate', () => {
    const values = defaultValues('classification', 'yolo11')
    expect(isTrainingModelParameterDisabled(
      getModelLayerTrainingFields('classification', 'yolo11').find((field) => field.key === 'learning_rate')!,
      values,
    )).toBe(true)
    expect(buildTrainingParameters('classification', 'yolo11', values).optimization).not.toHaveProperty('learning_rate')
    values.optimizer = 'adamw'
    values.learning_rate = '0.001'
    expect(buildTrainingParameters('classification', 'yolo11', values)).toMatchObject({
      optimization: { optimizer: 'adamw', learning_rate: 0.001 },
    })
  })

  it('uses explicit RF-DETR scheduler semantics', () => {
    const stepValues = defaultValues('segmentation', 'rfdetr')
    expect(buildTrainingParameters('segmentation', 'rfdetr', stepValues)).toMatchObject({
      optimization: { lr_scheduler: 'step' },
    })
    expect(buildTrainingParameters('segmentation', 'rfdetr', stepValues).optimization).not.toHaveProperty('min_lr_ratio')
    stepValues.lr_scheduler = 'cosine'
    expect(buildTrainingParameters('segmentation', 'rfdetr', stepValues)).toMatchObject({
      optimization: { lr_scheduler: 'cosine', min_lr_ratio: 0.01 },
    })
  })

  it('submits RF-DETR runtime, evaluation, accumulation and advanced groups', () => {
    const values = defaultValues('detection', 'rfdetr')

    expect(buildTrainingParameters('detection', 'rfdetr', values)).toMatchObject({
      runtime: { num_workers: 2 },
      optimization: { weight_decay: 0.0001, grad_accum_steps: 4 },
      evaluation: { max_detections: 500 },
      advanced: { use_ema: true, multi_scale: true, expanded_scales: true },
    })
  })

  it('exposes classification image augmentation fields for ordinary YOLO models', () => {
    for (const modelType of ['yolov8', 'yolo11', 'yolo26']) {
      expect(augmentationFieldKeys('classification', modelType)).toEqual([
        'flip_prob',
        'crop_mode',
        'crop_scale_min',
        'crop_scale_max',
        'auto_augment',
        'rotation_degrees',
        'translate_ratio',
        'scale_min',
        'scale_max',
        'brightness_gain',
        'contrast_gain',
        'gamma_min',
        'gamma_max',
        'hue_gain',
        'saturation_gain',
        'value_gain',
        'random_erasing_prob',
      ])
    }
  })

  it('submits enabled RF-DETR augmentation preset and backend', () => {
    const values = {
      ...defaultValues('detection', 'rfdetr'),
      rfdetr_augmentation_preset: 'industrial',
      scale_jitter: 'false',
      augmentation_backend: 'auto',
    }

    expect(buildTrainingParameters('detection', 'rfdetr', values)).toMatchObject({
      augmentation: { preset: 'industrial', scale_jitter: false, backend: 'auto' },
    })
  })

  it('submits the common training device outside model-specific fields', () => {
    const values = defaultValues('detection', 'yolo11')

    expect(fieldKeys('detection', 'yolo11')).not.toContain('device')
    expect(
      buildTrainingParameters('detection', 'yolo11', values, {
        device: 'cuda:1',
      }),
    ).toMatchObject({
      runtime: { device: 'cuda:1' },
    })
  })

  it('submits a disable flag when RF-DETR augmentation is turned off', () => {
    const values = defaultValues('segmentation', 'rfdetr')

    expect(
      buildTrainingParameters('segmentation', 'rfdetr', values, {
        augmentationEnabled: false,
      }),
    ).toMatchObject({
      augmentation: { enabled: false },
    })
  })

  it('submits disabled values for ordinary YOLO augmentation', () => {
    const values = defaultValues('pose', 'yolo11')

    expect(
      buildTrainingParameters('pose', 'yolo11', values, {
        augmentationEnabled: false,
      }),
    ).toMatchObject({
      augmentation: { enabled: false },
    })
  })

  it('submits disabled values for YOLOX augmentation', () => {
    const values = defaultValues('detection', 'yolox')

    expect(
      buildTrainingParameters('detection', 'yolox', values, {
        augmentationEnabled: false,
      }),
    ).toMatchObject({
      augmentation: { enabled: false },
    })
  })

  it('submits disabled values for classification augmentation', () => {
    const values = defaultValues('classification', 'yolov8')

    expect(
      buildTrainingParameters('classification', 'yolov8', values, {
        augmentationEnabled: false,
      }),
    ).toMatchObject({
      augmentation: { enabled: false },
    })
  })

  it('disables inactive classification controls without discarding their values', () => {
    const fields = getModelLayerTrainingFields('classification', 'yolo11')
    const values = defaultValues('classification', 'yolo11')
    const field = (key: string) => fields.find((item) => item.key === key)!

    expect(isTrainingAugmentationParameterDisabled(field('crop_scale_min'), values, true)).toBe(false)
    expect(isTrainingAugmentationParameterDisabled(field('rotation_degrees'), values, true)).toBe(true)

    values.crop_mode = 'none'
    values.auto_augment = 'none'
    expect(isTrainingAugmentationParameterDisabled(field('crop_scale_min'), values, true)).toBe(true)
    expect(isTrainingAugmentationParameterDisabled(field('rotation_degrees'), values, true)).toBe(false)
    expect(isTrainingAugmentationParameterDisabled(field('flip_prob'), values, false)).toBe(true)
  })

  it('rejects reversed classification ranges before submission', () => {
    const values = defaultValues('classification', 'yolov8')
    values.crop_scale_min = '0.9'
    values.crop_scale_max = '0.4'
    expect(validateTrainingModelLayerValues('classification', 'yolov8', values)).toContain('crop_scale')

    values.crop_scale_min = '0.4'
    values.crop_scale_max = '0.9'
    values.auto_augment = 'none'
    values.gamma_min = '1.2'
    values.gamma_max = '0.8'
    expect(validateTrainingModelLayerValues('classification', 'yolov8', values)).toContain('gamma')
  })

  it('keeps validating model parameters when augmentation is disabled', () => {
    const values = defaultValues('detection', 'yolo11')
    values.weight_decay = '2'

    expect(validateTrainingModelLayerValues(
      'detection',
      'yolo11',
      values,
      { augmentationEnabled: false },
    )).toContain('权重衰减')
  })

  it('rejects reversed YOLOX augmentation ranges', () => {
    const values = defaultValues('detection', 'yolox')
    values.mixup_scale_min = '2'
    values.mixup_scale_max = '0.5'

    expect(validateTrainingModelLayerValues('detection', 'yolox', values))
      .toContain('mixup_scale')
  })

  it('rejects values outside the declared decimal step grid', () => {
    const values = defaultValues('detection', 'yolo26')
    values.hsv_h = '0.0155'

    expect(validateTrainingModelLayerValues('detection', 'yolo26', values))
      .toContain('0.001')

    values.hsv_h = '0.015'
    expect(validateTrainingModelLayerValues('detection', 'yolo26', values)).toBeNull()
  })

  it('normalizes classification numeric inputs to their safe bounds on blur', () => {
    const fields = getModelLayerTrainingFields('classification', 'yolo11')
    const field = (key: string) => fields.find((item) => item.key === key)!

    expect(normalizeTrainingParameterNumber(field('translate_ratio'), '0.8')).toBe('0.5')
    expect(normalizeTrainingParameterNumber(field('scale_min'), '0')).toBe('0.1')
    expect(normalizeTrainingParameterNumber(field('scale_max'), '9')).toBe('2')
    expect(normalizeTrainingParameterNumber(field('gamma_max'), '8')).toBe('5')
    expect(normalizeTrainingParameterNumber(field('rotation_degrees'), '360')).toBe('180')
  })
})
