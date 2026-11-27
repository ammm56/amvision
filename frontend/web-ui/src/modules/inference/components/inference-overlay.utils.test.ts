import { describe, expect, it } from 'vitest'

import {
  computeObbCorners,
  filterOverlayItems,
  formatObbAngleDeg,
  formatXywh,
  normalizeInferenceOverlayItems,
  summarizeOverlayClasses,
} from './inference-overlay.utils'

describe('inference-overlay utils', () => {
  it('normalizes detection, segmentation, pose, obb, and classification results uniformly', () => {
    const det = normalizeInferenceOverlayItems('detection', {
      labels: ['bolt', 'nut'],
      detections: [{ bbox_xyxy: [10, 20, 50, 60], score: 0.92, class_id: 0, class_name: 'bolt' }],
    })
    expect(det).toHaveLength(1)
    expect(det[0].className).toBe('bolt')
    expect(det[0].bboxXyxy).toEqual([10, 20, 50, 60])
    expect(formatXywh(det[0].bboxXyxy!)).toEqual({ x: 10, y: 20, w: 40, h: 40 })

    const seg = normalizeInferenceOverlayItems('segmentation', {
      labels: ['part'],
      instances: [
        {
          bbox_xyxy: [0, 0, 100, 100],
          score: 0.85,
          class_id: 0,
          class_name: 'part',
          segments: [[[5, 5], [90, 5], [90, 90]]],
          mask_area: 300,
        },
      ],
    })
    expect(seg[0].segments).toHaveLength(1)
    expect(seg[0].maskArea).toBe(300)

    const pose = normalizeInferenceOverlayItems('pose', {
      keypoint_confidence_threshold: 0.4,
      instances: [
        {
          bbox_xyxy: [1, 2, 30, 40],
          score: 0.91,
          class_id: 0,
          class_name: 'person',
          keypoints: [{ x: 10, y: 12, confidence: 0.8 }],
          kpt_shape: [17, 3],
        },
      ],
    })
    expect(pose[0].keypointThreshold).toBe(0.4)
    expect(pose[0].keypoints).toHaveLength(1)

    const obb = normalizeInferenceOverlayItems('obb', {
      instances: [
        {
          bbox_xyxy: [10, 10, 50, 50],
          bbox_xywhr: [100, 100, 40, 20, -Math.PI / 6],
          score: 0.77,
          class_id: 1,
          class_name: 'chip',
          angle: -Math.PI / 6,
        },
      ],
    })
    expect(obb[0].obbPolygon).toHaveLength(4)
    expect(formatObbAngleDeg(obb[0])).toBeCloseTo(-30, 1)

    const cls = normalizeInferenceOverlayItems('classification', {
      categories: [
        { class_id: 0, class_name: 'ok_part', probability: 0.88 },
        { class_id: 1, class_name: 'defect', probability: 0.12 },
      ],
    })
    expect(cls).toHaveLength(2)
    expect(cls[0].score).toBe(0.88)
  })

  it('rotates OBB corners accurately around center', () => {
    const corners = computeObbCorners([100, 100, 40, 20, Math.PI / 2])
    expect(corners[0][0]).toBeCloseTo(110, 1)
    expect(corners[0][1]).toBeCloseTo(80, 1)
    expect(corners[2][0]).toBeCloseTo(90, 1)
    expect(corners[2][1]).toBeCloseTo(120, 1)
  })

  it('filters items strictly on client side by minDisplayScore, selectedClasses, and isolateItemId', () => {
    const items = normalizeInferenceOverlayItems('detection', {
      detections: [
        { bbox_xyxy: [0, 0, 10, 10], score: 0.9, class_id: 0, class_name: 'bolt' },
        { bbox_xyxy: [0, 0, 10, 10], score: 0.4, class_id: 1, class_name: 'nut' },
        { bbox_xyxy: [0, 0, 10, 10], score: 0.8, class_id: 1, class_name: 'nut' },
      ],
    })
    expect(filterOverlayItems(items, { minDisplayScore: 0.5, selectedClasses: [] })).toHaveLength(2)
    const onlyBolt = filterOverlayItems(items, { minDisplayScore: 0.2, selectedClasses: ['bolt'] })
    expect(onlyBolt).toHaveLength(1)
    const isolated = filterOverlayItems(items, {
      minDisplayScore: 0,
      selectedClasses: [],
      isolateItemId: items[2].id,
    })
    expect(isolated).toHaveLength(1)
    expect(summarizeOverlayClasses(items)).toEqual([
      { className: 'bolt', color: items[0].color, count: 1 },
      { className: 'nut', color: items[1].color, count: 2 },
    ])
  })
})
