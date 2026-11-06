<template>
  <div class="sample-details">
    <dl class="sample-details__metadata">
      <dt>{{ label('样本名称', 'Sample name') }}</dt><dd>{{ sample.file_name }}</dd>
      <dt>{{ label('图像尺寸', 'Image dimensions') }}</dt><dd>{{ sample.width }} × {{ sample.height }}</dd>
      <dt>{{ label('数据划分', 'Split') }}</dt><dd>{{ sample.split }}</dd>
      <dt>{{ label('标注来源', 'Annotation source') }}</dt><dd>{{ source }}</dd>
    </dl>
    <section class="sample-details__section">
      <h3>{{ classification ? label('图像标签', 'Image labels') : label('对象列表', 'Objects') }} ({{ sample.annotations.length }})</h3>
      <ResourceTable class="dataset-table sample-details__table" :label="text('objects')">
        <thead><tr><th class="sample-details__index">#</th><th>{{ text('classes') }}</th><th v-if="!classification">{{ geometryHeading }}<small v-if="task === 'detection'">X / Y / {{ label('宽 / 高', 'Width / Height') }}</small></th></tr></thead>
        <tbody><tr v-for="(item, index) in sample.annotations" :key="item.annotation_id" :class="{ 'is-selected': selected === item.annotation_id }" class="is-clickable" @click="emit('select', item.annotation_id)">
          <td>{{ index + 1 }}</td><td><button class="sample-details__object" :title="category(item.category_id)" @click.stop="emit('select', item.annotation_id)"><span class="sample-details__dot" :style="{ background: annotationColor(item.category_id) }" /><span>{{ category(item.category_id) }}</span></button></td>
          <td v-if="!classification" :title="geometry(item)">{{ geometry(item) }}</td>
        </tr></tbody>
      </ResourceTable>
      <p v-if="!sample.annotations.length" class="dataset-muted">{{ text('unannotated') }}</p>
    </section>
    <section v-if="active" class="sample-details__section">
      <h3>{{ classification ? label('选中标签', 'Selected label') : label('选中对象', 'Selected object') }}</h3>
      <div class="sample-details__category"><span>{{ text('classes') }}</span><span class="sample-details__dot" :style="{ background: annotationColor(active.category_id) }" /><strong>{{ category(active.category_id) }}</strong></div>
      <div v-if="active.bbox_xywh && task === 'detection'" class="sample-details__coordinate-row">
        <span>{{ label('原图坐标', 'Image coordinates') }}</span>
        <div class="sample-details__coordinates">
        <div v-for="(value, index) in active.bbox_xywh" :key="index"><span>{{ ['X', 'Y', label('宽', 'Width'), label('高', 'Height')][index] }}</span><strong>{{ number(value) }}</strong></div>
        <small>{{ label('单位：px', 'Unit: px') }}</small>
        </div>
      </div>
      <ResourceTable v-if="task === 'obb' && points.length" class="dataset-table sample-details__table" :label="label('顶点坐标', 'Vertices')">
        <thead><tr><th>{{ label('顶点', 'Vertex') }}</th><th>X (px)</th><th>Y (px)</th></tr></thead>
        <tbody><tr v-for="(point, index) in points" :key="index"><td>P{{ index + 1 }}</td><td>{{ number(point[0]) }}</td><td>{{ number(point[1]) }}</td></tr></tbody>
      </ResourceTable>
      <ResourceTable v-if="active.keypoints" class="dataset-table sample-details__table" :label="label('关键点', 'Keypoints')">
        <thead><tr><th>#</th><th>X / Y (px)</th><th>{{ label('可见性', 'Visibility') }}</th></tr></thead>
        <tbody><tr v-for="(point, index) in keypoints" :key="index"><td>{{ index + 1 }}</td><td>{{ point[2] ? `${number(point[0])} / ${number(point[1])}` : '—' }}</td><td>{{ point[2] === 2 ? label('可见', 'Visible') : point[2] === 1 ? label('遮挡', 'Occluded') : label('未标注', 'Unlabelled') }}</td></tr></tbody>
      </ResourceTable>
      <dl v-if="active.segmentation" class="sample-details__metadata sample-details__geometry"><dt>{{ label('标注形式', 'Representation') }}</dt><dd>{{ Array.isArray(active.segmentation) ? label('多边形', 'Polygon') : 'RLE mask' }}</dd><template v-if="Array.isArray(active.segmentation)"><dt>{{ label('轮廓数量', 'Contours') }}</dt><dd>{{ active.segmentation.length }}</dd><dt>{{ label('轮廓点数', 'Contour points') }}</dt><dd>{{ active.segmentation.reduce((sum, contour) => sum + contour.length / 2, 0) }}</dd></template></dl>
      <p v-if="active.is_anomalous != null">{{ active.is_anomalous ? label('异常样本', 'Anomalous') : label('正常样本', 'Normal') }}</p>
    </section>
    <details v-if="active" class="sample-details__raw"><summary>{{ label('原始标注', 'Raw annotation') }}</summary><pre class="dataset-json">{{ JSON.stringify(active, null, 2) }}</pre></details>
  </div>
</template>
<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import ResourceTable from '@/shared/ui/data-display/ResourceTable.vue'
import { annotationColor, annotationPoints } from '../annotations'
import { useDatasetText } from '../dataset-workspace'
import type { DatasetSample, DatasetAnnotation } from '../services/dataset-workspace.service'
const props = defineProps<{ sample: DatasetSample; categories: { category_id: number; name: string }[]; selected: string; task: string; source: string }>()
const emit = defineEmits<{ select: [id: string] }>()
const text = useDatasetText(), { locale } = useI18n()
const label = (zh: string, en: string) => locale.value.startsWith('zh') ? zh : en
const number = (value: number) => Number.isFinite(value) ? String(Number(value.toFixed(2))) : '—'
const category = (id: number | null) => props.categories.find(item => item.category_id === id)?.name || String(id ?? '—')
const active = computed(() => props.sample.annotations.find(item => item.annotation_id === props.selected))
const classification = computed(() => props.task === 'classification')
const points = computed(() => active.value ? annotationPoints(active.value) : [])
const keypoints = computed(() => { const values = active.value?.keypoints || []; return Array.from({ length: Math.floor(values.length / 3) }, (_, index) => values.slice(index * 3, index * 3 + 3)) })
const geometryHeading = computed(() => props.task === 'obb' ? label('顶点', 'Vertices') : props.task === 'pose' ? label('关键点', 'Keypoints') : ['segmentation', 'semantic_segmentation'].includes(props.task) ? label('轮廓 / 掩膜', 'Contours / Mask') : label('边界框 (px)', 'Bounding box (px)'))
function geometry(item: DatasetAnnotation) {
  if (item.polygon_xy) return `${item.polygon_xy.length / 2} ${label('个顶点', 'vertices')}`
  if (item.keypoints) return `${item.keypoints.length / 3} ${label('个点', 'points')}`
  if (item.segmentation) return Array.isArray(item.segmentation) ? `${item.segmentation.length} ${label('个轮廓', 'contours')}` : 'RLE mask'
  return item.bbox_xywh?.map(number).join(', ') || '—'
}
</script>
<style scoped>
.sample-details { min-width:0; }
.sample-details__metadata { display:grid; grid-template-columns:100px minmax(0,1fr); gap:16px; margin:0; padding:4px 0 24px; font-size:14px; }
.sample-details__metadata dt { color:var(--am-text-muted); }
.sample-details__metadata dd { margin:0; overflow-wrap:anywhere; }
.sample-details__section { padding-top:22px; margin-bottom:24px; }
.sample-details h3 { font-size:15px; font-weight:600; margin:0 0 16px; }
.sample-details__table :deep(th),.sample-details__table :deep(td) { padding:12px 10px; font-size:13px; }
.sample-details__table :deep(th:first-child) { width:40px; }
.sample-details__table :deep(th:nth-child(2)) { width:32%; }
.sample-details__table small { display:block; font-size:11px; font-weight:400; color:var(--am-text-muted); margin-top:4px; }
.sample-details__object { display:flex; align-items:center; gap:8px; min-width:0; width:100%; border:0; color:inherit; background:none; padding:0; cursor:pointer; text-align:left; }
.sample-details__object > span:last-child { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.sample-details__dot { display:inline-block; width:9px; height:9px; border-radius:50%; flex-shrink:0; }
.sample-details__category { display:flex; align-items:center; gap:8px; font-size:14px; margin-bottom:20px; }
.sample-details__category > span:first-child { width:92px; color:var(--am-text-muted); }
.sample-details strong { font-weight:400; }
.sample-details__coordinate-row { display:grid; grid-template-columns:100px minmax(0,1fr); gap:8px; font-size:14px; }
.sample-details__coordinate-row > span { color:var(--am-text-muted); }
.sample-details__coordinates { display:grid; grid-template-columns:1fr 1fr; gap:12px 16px; }
.sample-details__coordinates > div { display:flex; align-items:center; gap:8px; font-size:14px; }
.sample-details__coordinates > div > span { background:var(--am-surface-muted); padding:2px 5px; border-radius:3px; }
.sample-details__coordinates span,.sample-details__coordinates > small { color:var(--am-text-muted); }
.sample-details__coordinates > small { grid-column:1/-1; text-align:right; }
.sample-details__geometry { margin-top:16px; padding-bottom:0; }
.sample-details__raw summary { padding:14px 4px; cursor:pointer; font-size:14px; }
.sample-details__raw pre { margin:0; padding:16px; }
</style>
