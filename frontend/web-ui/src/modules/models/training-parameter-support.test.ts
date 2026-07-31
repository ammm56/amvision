import { describe, expect, it } from 'vitest'

import {
  buildTrainingExtraOptions,
  buildTrainingDeviceOptions,
  getDefaultTrainingModelParameterValues,
  getModelLayerTrainingFields,
  isTrainingAugmentationField,
  isTrainingAugmentationParameterDisabled,
  isTrainingModelParameterDisabled,
  normalizeTrainingParameterNumber,
  validateTrainingModelLayerValues,
} from './training-parameter-support'
import type { ModelTaskType } from './services/model.service'

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

describe('training parameter augmentation support', () => {
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
            'hsv_prob',
            'mosaic_prob',
            'mixup_prob',
            'enable_mixup',
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

  it('does not submit an Auto placeholder learning rate', () => {
    const values = defaultValues('classification', 'yolo11')
    expect(isTrainingModelParameterDisabled(
      getModelLayerTrainingFields('classification', 'yolo11').find((field) => field.key === 'learning_rate')!,
      values,
    )).toBe(true)
    expect(buildTrainingExtraOptions('classification', 'yolo11', values)).not.toHaveProperty('learning_rate')
    values.optimizer = 'adamw'
    values.learning_rate = '0.001'
    expect(buildTrainingExtraOptions('classification', 'yolo11', values)).toMatchObject({
      optimizer: 'adamw',
      learning_rate: 0.001,
    })
  })

  it('uses explicit RF-DETR scheduler semantics', () => {
    const stepValues = defaultValues('segmentation', 'rfdetr')
    expect(buildTrainingExtraOptions('segmentation', 'rfdetr', stepValues)).toMatchObject({
      lr_scheduler: 'step',
    })
    expect(buildTrainingExtraOptions('segmentation', 'rfdetr', stepValues)).not.toHaveProperty('min_lr_ratio')
    stepValues.lr_scheduler = 'cosine'
    expect(buildTrainingExtraOptions('segmentation', 'rfdetr', stepValues)).toMatchObject({
      lr_scheduler: 'cosine',
      min_lr_ratio: 0.01,
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
      augmentation_backend: 'auto',
    }

    expect(buildTrainingExtraOptions('detection', 'rfdetr', values)).toMatchObject({
      rfdetr_augmentation_preset: 'industrial',
      augmentation_backend: 'auto',
    })
  })

  it('submits the common training device outside model-specific fields', () => {
    const values = defaultValues('detection', 'yolo11')

    expect(fieldKeys('detection', 'yolo11')).not.toContain('device')
    expect(
      buildTrainingExtraOptions('detection', 'yolo11', values, {
        device: 'cuda:1',
      }),
    ).toMatchObject({
      device: 'cuda:1',
    })
  })

  it('submits a disable flag when RF-DETR augmentation is turned off', () => {
    const values = defaultValues('segmentation', 'rfdetr')

    expect(
      buildTrainingExtraOptions('segmentation', 'rfdetr', values, {
        augmentationEnabled: false,
      }),
    ).toMatchObject({
      disable_augmentation: true,
    })
  })

  it('submits disabled values for ordinary YOLO augmentation', () => {
    const values = defaultValues('pose', 'yolo11')

    expect(
      buildTrainingExtraOptions('pose', 'yolo11', values, {
        augmentationEnabled: false,
      }),
    ).toMatchObject({
      flip_prob: 0,
      hsv_prob: 0,
      mosaic_prob: 0,
      mixup_prob: 0,
      enable_mixup: false,
      affine_prob: 0,
      close_mosaic: 0,
      multi_scale: 0,
    })
  })

  it('submits disabled values for YOLOX augmentation', () => {
    const values = defaultValues('detection', 'yolox')

    expect(
      buildTrainingExtraOptions('detection', 'yolox', values, {
        augmentationEnabled: false,
      }),
    ).toMatchObject({
      flip_prob: 0,
      hsv_prob: 0,
      mosaic_prob: 0,
      mixup_prob: 0,
      enable_mixup: false,
      multiscale_range: 0,
      no_aug_epochs: 0,
    })
  })

  it('submits disabled values for classification augmentation', () => {
    const values = defaultValues('classification', 'yolov8')

    expect(
      buildTrainingExtraOptions('classification', 'yolov8', values, {
        augmentationEnabled: false,
      }),
    ).toMatchObject({
      flip_prob: 0,
      crop_mode: 'none',
      crop_scale_min: 1,
      crop_scale_max: 1,
      auto_augment: 'none',
      rotation_degrees: 0,
      translate_ratio: 0,
      scale_min: 1,
      scale_max: 1,
      brightness_gain: 0,
      contrast_gain: 0,
      gamma_min: 1,
      gamma_max: 1,
      hue_gain: 0,
      saturation_gain: 0,
      value_gain: 0,
      random_erasing_prob: 0,
      disable_augmentation: true,
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
