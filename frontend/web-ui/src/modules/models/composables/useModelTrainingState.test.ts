import { describe, expect, it } from 'vitest'

import { resolveSupportedTrainingExportFormats } from './useModelTrainingState'

const capabilityMatrix = {
  detection: {
    yolox: ['coco-detection-v1', 'voc-detection-v1'],
    yolo11: ['yolo-detection-v1', 'coco-detection-v1'],
    rfdetr: ['coco-detection-v1'],
  },
  classification: {
    yolo26: ['imagenet-classification-v1'],
  },
  segmentation: {
    yolov8: ['yolo-instance-seg-v1', 'coco-instance-seg-v1'],
    rfdetr: ['coco-instance-seg-v1'],
  },
  pose: {
    yolo11: ['yolo-pose-v1', 'coco-keypoints-v1'],
  },
  obb: {
    yolov8: ['dota-obb-v1'],
  },
}

describe('model training dataset export format support', () => {
  it('matches backend training format rules for detection models', () => {
    expect(resolveSupportedTrainingExportFormats('detection', 'yolox', capabilityMatrix)).toEqual([
      'coco-detection-v1',
      'voc-detection-v1',
    ])
    expect(resolveSupportedTrainingExportFormats('detection', 'yolo11', capabilityMatrix)).toEqual([
      'yolo-detection-v1',
      'coco-detection-v1',
    ])
    expect(resolveSupportedTrainingExportFormats('detection', 'rfdetr', capabilityMatrix)).toEqual([
      'coco-detection-v1',
    ])
  })

  it('matches backend training format rules for non-detection models', () => {
    expect(resolveSupportedTrainingExportFormats('classification', 'yolo26', capabilityMatrix)).toEqual([
      'imagenet-classification-v1',
    ])
    expect(resolveSupportedTrainingExportFormats('segmentation', 'yolov8', capabilityMatrix)).toEqual([
      'yolo-instance-seg-v1',
      'coco-instance-seg-v1',
    ])
    expect(resolveSupportedTrainingExportFormats('segmentation', 'rfdetr', capabilityMatrix)).toEqual([
      'coco-instance-seg-v1',
    ])
    expect(resolveSupportedTrainingExportFormats('pose', 'yolo11', capabilityMatrix)).toEqual([
      'yolo-pose-v1',
      'coco-keypoints-v1',
    ])
    expect(resolveSupportedTrainingExportFormats('obb', 'yolov8', capabilityMatrix)).toEqual(['dota-obb-v1'])
  })

  it('does not expose unsupported model and task combinations', () => {
    expect(resolveSupportedTrainingExportFormats('classification', 'rfdetr', capabilityMatrix)).toEqual([])
    expect(resolveSupportedTrainingExportFormats('pose', 'yolox', capabilityMatrix)).toEqual([])
    expect(resolveSupportedTrainingExportFormats('obb', 'rfdetr', capabilityMatrix)).toEqual([])
  })
})
