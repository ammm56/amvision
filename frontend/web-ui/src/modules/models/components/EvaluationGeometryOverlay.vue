<template>
  <svg class="geometry-overlay" :viewBox="`0 0 ${width} ${height}`" aria-hidden="true">
    <g v-for="(layer, layerIndex) in layers" :key="layerIndex" :class="layerIndex ? 'prediction' : 'ground-truth'">
      <template v-for="(item, index) in layer" :key="index">
        <polygon v-if="item.polygon?.length" :points="polygonPoints(item.polygon)" />
        <template v-if="item.keypoints">
          <line v-for="edge in skeleton(item)" :key="`${edge.join('-')}`"
            :x1="point(item, edge[0])[0]" :y1="point(item, edge[0])[1]"
            :x2="point(item, edge[1])[0]" :y2="point(item, edge[1])[1]" />
          <template v-for="(x, i) in item.keypoints" :key="i">
            <template v-if="i % 3 === 0 && item.keypoints[i + 2] > 0">
              <circle :cx="x" :cy="item.keypoints[i + 1]" :r="radius" />
              <text v-if="showKeypointNumbers && layerIndex === 0" :x="x + radius * 1.5"
                :y="item.keypoints[i + 1] - radius * 1.5" :font-size="radius * 4">{{ i / 3 + 1 }}</text>
            </template>
          </template>
        </template>
      </template>
    </g>
  </svg>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { EvaluationGeometry, ModelEvaluationReport } from '../services/model-evaluation.service'

const props = defineProps<{
  width: number; height: number; layers: EvaluationGeometry[][]; definitions?: ModelEvaluationReport['keypoint_definitions']
  showKeypointNumbers?: boolean
}>()
const radius = computed(() => Math.max(2, Math.min(props.width, props.height) / 200))
function polygonPoints(polygon: number[] | number[][]): string {
  return polygon.flat().join(' ')
}
function point(item: EvaluationGeometry, index: number): number[] {
  return item.keypoints?.slice((index - 1) * 3, index * 3) ?? []
}
function skeleton(item: EvaluationGeometry): [number, number][] {
  const edges = props.definitions?.find(definition => definition.id === item.category_id)?.skeleton ?? []
  return edges.filter(([from, to]) => point(item, from)[2] > 0 && point(item, to)[2] > 0)
}
</script>

<style scoped>
.geometry-overlay { position:absolute; inset:0; width:100%; height:100%; pointer-events:none; }
.ground-truth { color:#00d69c; }
.prediction { color:#ff9d24; }
:is(polygon,line,circle) { vector-effect:non-scaling-stroke; stroke:currentColor; stroke-width:2px; }
polygon { fill:none; }
.prediction :is(polygon,line) { stroke-dasharray:5 3; }
circle { fill:currentColor; stroke:#15221e; stroke-width:1px; }
text { fill:white; stroke:#15221e; stroke-width:2px; paint-order:stroke; font-weight:700; }
</style>
