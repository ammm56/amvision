<template>
  <section class="training-task-rules field--wide" :aria-label="label('任务规则', 'Task rules')">
    <h3>{{ label('任务规则', 'Task rules') }} · {{ taskLabel }}</h3>
    <dl v-if="taskType === 'classification'" class="training-task-rules__details">
      <div>
        <dt>{{ label('类别顺序', 'Class order') }}</dt>
        <dd class="training-task-rules__classes" :class="{ 'is-empty': !datasetExport?.category_names?.length }">
          <TrainingCategoryList :categories="datasetExport?.category_names" :label="label('类别顺序', 'Class order')" ordered />
        </dd>
      </div>
      <div><dt>{{ label('验证主指标', 'Primary validation metric') }}</dt><dd>Top-1 Accuracy</dd></div>
    </dl>
    <template v-else-if="taskType === 'segmentation'">
      <dl class="training-task-rules__details">
        <div><dt>{{ label('标注类型', 'Annotation type') }}</dt><dd>{{ label('实例 mask', 'Instance masks') }}</dd></div>
      </dl>
      <slot />
    </template>
    <template v-else-if="taskType === 'pose'">
      <dl class="training-task-rules__details">
        <div>
          <dt>{{ label('关键点定义', 'Keypoint definition') }}</dt>
          <dd>
            <span v-if="poseShape">{{ poseShape[0] }} {{ label('点', 'points') }} · {{ poseShape[1] === 3 ? 'x, y, v' : 'x, y' }}</span>
            <span v-else-if="poseLoading" role="status">{{ label('正在读取…', 'Loading…') }}</span>
            <span v-else-if="poseSchemas.length">{{ poseKeypointCounts }} {{ label('点', 'points') }}</span>
            <span v-else-if="poseLoadError" role="status">{{ label('读取失败', 'Could not read definition') }}</span>
            <span v-else>{{ label('暂无可显示的定义', 'No definition to display') }}</span>
          </dd>
        </div>
        <div><dt>OKS sigma</dt><dd>{{ label('由训练后端按关键点数确定', 'Resolved by the trainer for the keypoint count') }}</dd></div>
      </dl>
      <Button v-if="poseLoadError" type="button" size="sm" @click="retryPoseDefinition">{{ label('重试读取关键点', 'Retry keypoint definition') }}</Button>
      <details v-if="poseSchemas.length" class="training-task-rules__skeleton">
        <summary>{{ exportPoseSchemas.length ? label('查看导出的类别关键点和骨架', 'View exported keypoints and skeletons') : label('查看数据集版本的关键点和骨架', 'View source version keypoints and skeletons') }}</summary>
        <ul>
          <li v-for="schema in poseSchemas" :key="schema.id">
            <strong>{{ schema.name }}</strong>
            <span>{{ schema.keypoints.join('、') }}</span>
            <span v-if="schema.edgeCount !== null" class="training-task-rules__edges">{{ label('骨架连线', 'Skeleton links') }} {{ schema.edgeCount }}</span>
          </li>
        </ul>
      </details>
    </template>
    <template v-else-if="taskType === 'obb'">
      <dl class="training-task-rules__details">
        <div><dt>{{ label('角度约定', 'Angle convention') }}</dt><dd>{{ label('x 向右，y 向下，顺时针为正', 'x right, y down, clockwise positive') }}</dd></div>
      </dl>
      <slot />
    </template>
  </section>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import Button from '@/shared/ui/components/Button.vue'
import { getDatasetExportManifest, getDatasetExportText, type DatasetExportSummary } from '@/modules/datasets/services/dataset.service'
import type { DatasetWorkspace } from '@/modules/datasets/services/dataset-workspace.service'
import type { ModelTaskType } from '../services/model.service'
import TrainingCategoryList from './TrainingCategoryList.vue'

const props = defineProps<{
  taskType: ModelTaskType
  datasetExport: DatasetExportSummary | null
  workspace: DatasetWorkspace | null
}>()
const { locale } = useI18n()
const label = (zh: string, en: string) => locale.value.startsWith('zh') ? zh : en
const taskLabel = computed(() => ({
  classification: label('分类', 'Classification'),
  segmentation: label('实例分割', 'Instance segmentation'),
  pose: label('关键点', 'Pose'),
  obb: label('旋转框', 'Oriented boxes'),
  detection: label('目标检测', 'Detection'),
})[props.taskType])
const poseShape = ref<[number, 2 | 3] | null>(null)
interface PoseCategory {
  id: number
  name: string
  keypoints: string[]
  edgeCount: number | null
}
const exportPoseSchemas = ref<PoseCategory[]>([])
const poseLoading = ref(false)
const poseLoadError = ref(false)
const poseRetry = ref(0)
const poseExport = computed(() => props.taskType === 'pose' ? props.datasetExport : null)
const poseSchemas = computed(() => {
  if (exportPoseSchemas.value.length) return exportPoseSchemas.value
  const workspace = props.workspace
  if (workspace?.dataset_version_id !== props.datasetExport?.dataset_version_id) return []
  const schemas = workspace?.metadata.pose_category_schemas
  if (!workspace || !schemas || typeof schemas !== 'object' || Array.isArray(schemas)) return []
  return workspace.categories.flatMap(category => {
    const schema = (schemas as Record<string, { keypoints?: unknown; skeleton?: unknown } | undefined>)[category.category_id]
    return readPoseCategory(category.category_id, category.name, schema?.keypoints, schema?.skeleton)
  })
})
const poseKeypointCounts = computed(() => [...new Set(poseSchemas.value.map(schema => schema.keypoints.length))].join(' / '))

function readPoseCategory(id: number, name: string, points: unknown, skeleton: unknown): PoseCategory[] {
  if (!Number.isSafeInteger(id) || typeof name !== 'string'
    || !Array.isArray(points) || points.length === 0 || !points.every(point => typeof point === 'string' && point.trim())) return []
  return [{ id, name, keypoints: points, edgeCount: Array.isArray(skeleton) ? skeleton.length : null }]
}

function retryPoseDefinition(): void {
  poseRetry.value += 1
}

watch([poseExport, poseRetry], async ([selected], _, onCleanup) => {
  poseShape.value = null
  exportPoseSchemas.value = []
  poseLoadError.value = false
  poseLoading.value = Boolean(selected)
  if (!selected) return
  const controller = new AbortController()
  onCleanup(() => controller.abort())
  try {
    if (selected.format_id === 'coco-keypoints-v1') {
      if (poseSchemas.value.length) return
      const split = ['train', 'val', 'test'].find(name => selected.split_names.includes(name))
      if (!split) return
      const file = await getDatasetExportText(selected.dataset_export_id, `annotations/person_keypoints_${split}.json`, controller.signal)
      if (controller.signal.aborted || file.truncated) return
      const payload = JSON.parse(file.content) as { categories?: { id: number; name: string; keypoints?: unknown; skeleton?: unknown }[] }
      if (Array.isArray(payload.categories)) {
        exportPoseSchemas.value = payload.categories.flatMap(item => readPoseCategory(item.id, item.name, item.keypoints, item.skeleton))
      }
      return
    }
    if (selected.format_id !== 'yolo-pose-v1') return
    const manifest = await getDatasetExportManifest(selected.dataset_export_id, controller.signal)
    if (controller.signal.aborted) return
    if (manifest.dataset_version_id !== selected.dataset_version_id) {
      poseLoadError.value = true
      return
    }
    const shape = manifest.metadata?.kpt_shape
    if (Array.isArray(shape) && shape.length === 2 && Number.isSafeInteger(shape[0]) && shape[0] > 0 && (shape[1] === 2 || shape[1] === 3)) {
      poseShape.value = [shape[0], shape[1]]
    }
  } catch {
    if (!controller.signal.aborted) poseLoadError.value = true
  } finally {
    if (!controller.signal.aborted) poseLoading.value = false
  }
}, { immediate: true })
</script>

<style scoped>
.training-task-rules {
  display: grid;
  gap: 12px;
  min-width: 0;
  padding: 12px 16px;
  background: var(--am-surface);
  border: 1px solid var(--am-border);
  border-radius: 8px;
}
.training-task-rules h3 { margin: 0; font-size: 15px; }
.training-task-rules__details {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  align-items: start;
  gap: 8px 24px;
  margin: 0;
}
.training-task-rules__details > div {
  display: grid;
  min-width: 0;
  grid-template-columns: minmax(124px, 39%) minmax(0, 1fr);
  align-items: start;
  gap: 8px;
}
.training-task-rules dt { padding-block: 8px; color: var(--am-text-muted); }
.training-task-rules dd {
  min-width: 0;
  margin: 0;
  padding: 7px 10px;
  border: 1px solid var(--am-border);
  border-radius: var(--am-radius-sm);
  background: var(--am-surface-muted);
  overflow-wrap: anywhere;
}
.training-task-rules__classes:not(.is-empty) { padding: 0; border: 0; background: transparent; }
.training-task-rules :deep(.ui-button) { justify-self: start; }
.training-task-rules__skeleton summary { cursor: pointer; }
.training-task-rules__skeleton ul { display: grid; gap: 6px; padding-inline-start: 20px; }
.training-task-rules__skeleton li { overflow-wrap: anywhere; }
.training-task-rules__skeleton li span { margin-inline-start: 8px; color: var(--am-text-muted); }
.training-task-rules__edges { display: inline-block; }
@media (max-width: 760px) {
  .training-task-rules__details { grid-template-columns: minmax(0, 1fr); }
}
@media (max-width: 440px) {
  .training-task-rules__details > div { grid-template-columns: minmax(0, 1fr); gap: 4px; }
  .training-task-rules dt { padding-block: 0; }
}
</style>
