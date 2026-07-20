import { computed, ref } from 'vue'
import { describe, expect, it } from 'vitest'

import { useImageGeometryAnnotations, type GeometryOverlay } from './useImageGeometryAnnotations'

describe('useImageGeometryAnnotations', () => {
  it('keeps CAD labels in screen pixels at low image scale', () => {
    const scale = ref(0.16)
    const viewportWidth = ref(1524)
    const viewportHeight = ref(986)
    const imageWidth = 5472
    const imageHeight = 3648
    const overlays = computed<GeometryOverlay[]>(() => [
      {
        kind: 'search-roi',
        id: 'search',
        bboxXyxy: [1051, 0, 1725, 606],
        circle: null,
      },
      {
        kind: 'reference-circle',
        id: 'reference',
        bboxXyxy: null,
        circle: { centerX: 1409.05, centerY: 275.84, radius: 38.48 },
      },
    ])
    const offsetX = ref(-183)
    const offsetY = ref(0)
    const sourceToViewport = (sourceX: number, sourceY: number) => ({
      x: viewportWidth.value / 2 + offsetX.value + (sourceX - imageWidth / 2) * scale.value,
      y: viewportHeight.value / 2 + offsetY.value + (sourceY - imageHeight / 2) * scale.value,
    })
    const annotations = useImageGeometryAnnotations({
      overlays,
      draftBboxXyxy: computed(() => null),
      draftCircle: computed(() => null),
      interactionTool: computed(() => 'rect'),
      viewportWidth,
      viewportHeight,
      reservedRightPx: computed(() => 366),
      sourceToViewport,
      translate: (key) => key,
    })

    expect(annotations.roiAnnotations.value[0]?.boxWidth).toBe(238)
    expect(annotations.circleAnnotations.value[0]?.boxWidth).toBe(224)
    expect(annotations.roiAnnotations.value[0]?.boxX).toBeGreaterThanOrEqual(7)
    expect(annotations.circleAnnotations.value[0]?.boxX).toBeLessThanOrEqual(1524 - 366 - 224 - 6)

    scale.value = 1
    expect(annotations.roiAnnotations.value[0]?.boxWidth).toBe(238)
    expect(annotations.circleAnnotations.value[0]?.boxWidth).toBe(224)
  })
})
