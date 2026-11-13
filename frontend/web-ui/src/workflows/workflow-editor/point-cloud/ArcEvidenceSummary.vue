<template>
  <section v-if="item?.kind === 'measure-arc' && item.geometry" class="arc-evidence">
    <dl>
      <dt>{{ zh ? '模型弧长 / 实测折线' : 'Model length / measured polyline' }}</dt>
      <dd>{{ number(modelLength) }} / {{ number(geometry.polyline_length) }} {{ unit }}</dd>
      <dt>{{ zh ? '支持角度 / 段间重叠角度' : 'Supported / inter-segment overlap angle' }}</dt>
      <dd>{{ number(geometry.coverage_angle) }} / {{ number(geometry.overlap_angle) }} rad</dd>
      <template v-if="geometry.start">
        <dt>{{ zh ? '方向（从 +N 看向评价面）' : 'Direction viewed from +N toward the plane' }}</dt>
        <dd>{{ direction }} · {{ number(geometry.signed_sweep) }} rad</dd>
      </template>
    </dl>
    <table>
      <thead><tr>
        <th>{{ zh ? '实测段' : 'Measured segment' }}</th>
        <th>{{ zh ? '原拓扑 / 源顺序扫角' : 'Topology / source-order sweep' }}</th>
        <th>{{ zh ? '折线长度' : 'Polyline length' }}</th>
      </tr></thead>
      <tbody><tr v-for="part in parts" :key="String(part.segment_id)">
        <td><button :aria-pressed="part.segment_id === selectedSegment" @click="emit('select-segment', String(part.segment_id))">{{ part.segment_id }}</button></td>
        <td>{{ part.closed ? (zh ? '闭合' : 'Closed') : (zh ? '开放' : 'Open') }} · {{ part.angular_reason ? measurementReason(String(part.angular_reason), zh) : `${number(part.signed_sweep)} rad` }}</td>
        <td>{{ number(part.polyline_length) }} {{ unit }}</td>
      </tr></tbody>
    </table>
    <dl v-for="key in endpoints" :key="key">
      <dt>{{ key === 'start' ? (zh ? '起点支持 / 圆上投影' : 'Start support / circle projection') : (zh ? '终点支持 / 圆上投影' : 'End support / circle projection') }}</dt>
      <dd>{{ coordinates(object(geometry[key]).point) }} / {{ coordinates(object(geometry[key]).projected) }} {{ unit }}</dd>
      <dt>{{ zh ? '原始行号 / 生成来源' : 'Source row / generated provenance' }}</dt>
      <dd v-if="object(geometry[key]).source_index !== null">{{ object(geometry[key]).source_index }}</dd>
      <dd v-else>
        {{ zh ? '源边' : 'Source edge' }}: {{ object(object(geometry[key]).lineage).source_edge }};
        {{ zh ? '权重' : 'Weights' }}: {{ coordinates(object(object(geometry[key]).lineage).weights) }};
        {{ zh ? '源面数' : 'Source faces' }}: {{ object(object(geometry[key]).lineage).source_face_count }}
        <details><summary>{{ zh ? '来源摘要' : 'Provenance digest' }}</summary>{{ object(object(geometry[key]).lineage).source_faces_sha256 }}</details>
      </dd>
    </dl>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { object } from './preview-data'
import type { MeasurementDisplay } from './measurement-display'
import { measurementReason } from './measurement-labels'

const props = defineProps<{ item?: MeasurementDisplay; unit: string; zh: boolean; precision?: number|'raw'; selectedSegment?: string }>()
const emit = defineEmits<{ 'select-segment': [id: string] }>()
function number(value: unknown) {
  if(typeof value !== 'number' || !Number.isFinite(value)) return '-'
  if(props.precision === 'raw') return String(value)
  const formatted=value.toFixed(props.precision ?? 4)
  return value !== 0 && Number(formatted) === 0 ? String(value) : formatted
}
function coordinates(value:unknown){return Array.isArray(value)?value.map(number).join(', '):'-'}
const geometry = computed(() => props.item?.geometry ?? {})
const parts = computed(() => Array.isArray(geometry.value.parts) ? geometry.value.parts.map(object) : [])
const endpoints = computed(() => geometry.value.start ? ['start', 'end'] : [])
const modelLength = computed(() => Number(object(geometry.value.circle).radius) * Number(geometry.value.coverage_angle))
const direction = computed(() => geometry.value.direction === 'ccw'
  ? (props.zh ? '逆时针' : 'Counterclockwise')
  : (props.zh ? '顺时针' : 'Clockwise'))
</script>

<style scoped>
.arc-evidence { min-width: 0; }
dl { display: grid; grid-template-columns: minmax(110px, 1fr) minmax(0, 2fr); gap: 6px; margin: 8px 0; }
dd { margin: 0; overflow-wrap: anywhere; }
table { width: 100%; border-collapse: collapse; }
th, td { padding: 6px; text-align: left; border-bottom: 1px solid var(--am-border); }
button { border: 0; background: transparent; color: var(--am-brand-primary); font: inherit; text-align: left; overflow-wrap: anywhere; cursor: pointer; padding: 0; }
button[aria-pressed="true"] { text-decoration: underline; }
</style>
