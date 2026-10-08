<template>
  <g v-if="shape" class="result-shape" :class="{'result-shape--expected':shape.kind==='expected-point'}">
    <title>{{ shape.item_id }}{{ shape.kind==='expected-point' ? ' · '+expectedLabel : '' }}</title>
    <line v-if="shape.kind==='line' && shape.points[1]" :x1="shape.points[0]![0]" :y1="shape.points[0]![1]" :x2="shape.points[1][0]" :y2="shape.points[1][1]" />
    <rect v-else-if="shape.kind==='expected-point'" :x="shape.points[0]![0]-14" :y="shape.points[0]![1]-14" width="28" height="28" />
    <circle v-else :cx="shape.points[0]![0]" :cy="shape.points[0]![1]" r="10" />
    <text :x="shape.points[0]![0]" :y="shape.points[0]![1]-20">{{ shape.item_id }}{{ shape.kind==='expected-point' ? ' · '+expectedLabel : '' }}</text>
  </g>
</template>
<script setup lang="ts">
import {computed} from 'vue'
import {useI18n} from 'vue-i18n'
import type {ResultGeometryShape} from './result-geometry'
defineProps<{shape:ResultGeometryShape|null}>()
const {locale}=useI18n()
const expectedLabel=computed(()=>locale.value==='zh-CN'?'预期位置':'Expected position')
</script>
<style scoped>
.result-shape { pointer-events:none; }
line,rect,circle { stroke:#ffcf40;stroke-width:3;fill:none;vector-effect:non-scaling-stroke; }
.result-shape--expected rect { stroke-dasharray:5 4; }
text { font-size:16px;fill:white;stroke:#121212;stroke-width:3;paint-order:stroke; }
</style>
