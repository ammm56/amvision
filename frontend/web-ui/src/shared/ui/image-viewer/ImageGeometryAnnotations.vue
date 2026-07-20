<template>
  <svg
    v-if="viewBox && (roiAnnotations.length || circleAnnotations.length)"
    class="image-viewer__dimension-layer"
    :viewBox="viewBox"
    preserveAspectRatio="none"
    aria-hidden="true"
  >
    <g
      v-for="annotation in roiAnnotations"
      :key="annotation.key"
      class="image-viewer__dimension image-viewer__dimension--search-roi"
    >
      <rect class="image-viewer__dimension-box" :x="annotation.boxX" :y="annotation.boxY" :width="annotation.boxWidth" :height="annotation.boxHeight" rx="5" />
      <text class="image-viewer__dimension-text" :x="annotation.boxX + 8" :y="annotation.boxY + 14" font-size="11">
        <tspan class="image-viewer__dimension-title">{{ annotation.title }}</tspan>
        <tspan :x="annotation.boxX + 8" dy="16">{{ annotation.detail }}</tspan>
      </text>
    </g>
    <g
      v-for="annotation in circleAnnotations"
      :key="annotation.key"
      class="image-viewer__dimension"
      :class="`image-viewer__dimension--${annotation.kind}`"
    >
      <line class="image-viewer__dimension-line" :x1="annotation.centerX" :y1="annotation.centerY" :x2="annotation.rimX" :y2="annotation.rimY" />
      <polyline class="image-viewer__dimension-line" :points="annotation.leaderPoints" />
      <line class="image-viewer__dimension-tick" :x1="annotation.tickX1" :y1="annotation.tickY1" :x2="annotation.tickX2" :y2="annotation.tickY2" />
      <line class="image-viewer__dimension-center" :x1="annotation.centerX - 5" :y1="annotation.centerY" :x2="annotation.centerX + 5" :y2="annotation.centerY" />
      <line class="image-viewer__dimension-center" :x1="annotation.centerX" :y1="annotation.centerY - 5" :x2="annotation.centerX" :y2="annotation.centerY + 5" />
      <rect class="image-viewer__dimension-box" :x="annotation.boxX" :y="annotation.boxY" :width="annotation.boxWidth" :height="annotation.boxHeight" rx="5" />
      <text class="image-viewer__dimension-text" :x="annotation.boxX + 8" :y="annotation.boxY + 14" font-size="11">
        <tspan class="image-viewer__dimension-title">{{ annotation.title }}</tspan>
        <tspan :x="annotation.boxX + 8" dy="16">{{ annotation.positionText }}</tspan>
        <tspan :x="annotation.boxX + 8" dy="16">{{ annotation.sizeText }}</tspan>
      </text>
    </g>
  </svg>
</template>

<script setup lang="ts">
import type { CircleScreenAnnotation, RoiScreenAnnotation } from './useImageGeometryAnnotations'

defineProps<{
  viewBox: string
  roiAnnotations: RoiScreenAnnotation[]
  circleAnnotations: CircleScreenAnnotation[]
}>()
</script>
