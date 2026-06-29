import { describe, expect, it } from 'vitest'

import {
  buildTrainingExtraOptions,
  getDefaultTrainingModelParameterValues,
  getModelLayerTrainingFields,
  isTrainingAugmentationField,
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

  it('exposes classification image augmentation fields for ordinary YOLO models', () => {
    for (const modelType of ['yolov8', 'yolo11', 'yolo26']) {
      expect(augmentationFieldKeys('classification', modelType)).toEqual([
        'flip_prob',
        'hsv_prob',
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
      hsv_prob: 0,
      random_erasing_prob: 0,
      disable_augmentation: true,
    })
  })
})
