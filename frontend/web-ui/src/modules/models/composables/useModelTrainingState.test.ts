import { describe, expect, it } from 'vitest'

import { resolveSupportedTrainingExportFormats } from './useModelTrainingState'

describe('model training dataset export format support', () => {
  it('matches backend training format rules for detection models', () => {
    expect(resolveSupportedTrainingExportFormats('detection', 'yolox')).toEqual([
      'coco-detection-v1',
      'voc-detection-v1',
    ])
    expect(resolveSupportedTrainingExportFormats('detection', 'yolo11')).toEqual([
      'yolo-detection-v1',
      'coco-detection-v1',
    ])
    expect(resolveSupportedTrainingExportFormats('detection', 'rfdetr')).toEqual([
      'coco-detection-v1',
    ])
  })

  it('matches backend training format rules for non-detection models', () => {
    expect(resolveSupportedTrainingExportFormats('classification', 'yolo26')).toEqual([
      'imagenet-classification-v1',
    ])
    expect(resolveSupportedTrainingExportFormats('segmentation', 'yolov8')).toEqual([
      'yolo-instance-seg-v1',
      'coco-instance-seg-v1',
    ])
    expect(resolveSupportedTrainingExportFormats('segmentation', 'rfdetr')).toEqual([
      'coco-instance-seg-v1',
    ])
    expect(resolveSupportedTrainingExportFormats('pose', 'yolo11')).toEqual([
      'yolo-pose-v1',
      'coco-keypoints-v1',
    ])
    expect(resolveSupportedTrainingExportFormats('obb', 'yolov8')).toEqual(['dota-obb-v1'])
  })

  it('does not expose unsupported model and task combinations', () => {
    expect(resolveSupportedTrainingExportFormats('classification', 'rfdetr')).toEqual([])
    expect(resolveSupportedTrainingExportFormats('pose', 'yolox')).toEqual([])
    expect(resolveSupportedTrainingExportFormats('obb', 'rfdetr')).toEqual([])
  })
})
