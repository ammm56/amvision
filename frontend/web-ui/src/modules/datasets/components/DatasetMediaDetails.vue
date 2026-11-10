<template>
  <dl class="dataset-details">
    <dt>{{ l('样本', 'Sample') }}</dt>
    <dd>{{ sample.file_name }}</dd>
    <dt>{{ l('来源', 'Source') }}</dt>
    <dd>{{ media.source || l('导入资料', 'Imported data') }}</dd>
    <dt>{{ l('数据划分', 'Split') }}</dt>
    <dd>{{ sample.split }}</dd>
    <template v-if="media.kind === 'anomaly'">
      <dt>{{ l('图像标签', 'Image label') }}</dt>
      <dd>
        {{
          media.label === 'normal' ? l('正常', 'Normal') : l('异常', 'Anomaly')
        }}
      </dd>
      <dt v-if="media.defect">{{ l('异常类型', 'Defect') }}</dt>
      <dd v-if="media.defect">{{ media.defect }}</dd>
      <dt>{{ l('区域标注', 'Region annotation') }}</dt>
      <dd>
        {{
          media.assets.includes('mask')
            ? l('真值掩膜', 'Ground truth mask')
            : l('未提供', 'Not provided')
        }}
      </dd>
      <dt>{{ l('预测结果', 'Prediction') }}</dt>
      <dd>{{ l('未载入', 'Not loaded') }}</dd>
    </template>
    <template v-if="media.kind === 'connector-reference'">
      <dt>{{ l('参考来源', 'Reference source') }}</dt>
      <dd>
        {{
          media.synthetic
            ? l('合成资源', 'Synthetic')
            : l('实物资料', 'Physical part')
        }}
      </dd>
      <dt v-if="media.pitch">{{ l('设计节距', 'Design pitch') }}</dt>
      <dd v-if="media.pitch">{{ media.pitch }} {{ media.unit }}</dd>
      <dt v-if="media.plane">{{ l('参考平面', 'Reference plane') }}</dt>
      <dd v-if="media.plane">{{ media.plane }}</dd>
      <dt>{{ l('独立实测参考', 'Independent measurements') }}</dt>
      <dd>
        <div v-for="(r, i) in media.measured" :key="i">
          {{ r.name }} · {{ r.value }} {{ r.unit }} · {{ r.source }}
        </div>
        <template v-if="!media.measured?.length">{{
          l('未提供', 'Not provided')
        }}</template>
      </dd>
    </template>
    <template v-if="media.kind === 'rgbd'">
      <dt>{{ l('配对 ID', 'Pair ID') }}</dt>
      <dd>{{ media.id }}</dd>
      <dt>RGB / {{ l('深度', 'Depth') }}</dt>
      <dd>
        {{ sample.width }} × {{ sample.height }} /
        {{ media.depth_size?.join(' × ') }}
      </dd>
      <dt>{{ l('深度比例', 'Depth scale') }}</dt>
      <dd>{{ media.scale }} {{ media.unit }} / {{ l('计数', 'count') }}</dd>
      <dt>{{ l('无效原值', 'Invalid raw value') }}</dt>
      <dd>{{ media.invalid }}</dd>
      <dt>{{ l('配准状态', 'Registration') }}</dt>
      <dd>{{ alignment }}</dd>
    </template>
    <template v-if="media.kind === 'point-cloud'">
      <dt>{{ l('坐标系', 'Frame') }}</dt>
      <dd>{{ media.frame }}</dd>
      <dt>{{ l('单位', 'Unit') }}</dt>
      <dd>{{ media.unit }}</dd>
      <dt>{{ l('总点数', 'Points') }}</dt>
      <dd>{{ media.point_count?.toLocaleString() }}</dd>
      <dt>{{ l('有效 / 无效', 'Valid / invalid') }}</dt>
      <dd>
        {{ media.valid_count?.toLocaleString() }} /
        {{ media.invalid_count?.toLocaleString() }}
      </dd>
    </template>
  </dl>
  <details v-if="media.calibration_name" @toggle="openCalibration">
    <summary>
      {{ l('标定资料', 'Calibration') }} · {{ media.calibration_name }}
    </summary>
    <InlineError v-if="error" :message="error" />
    <pre v-if="calibration" class="dataset-json">{{ calibration }}</pre>
  </details>
  <div v-if="originalAsset" class="dataset-actions">
    <Button :loading="downloading" @click="download">{{
      l('下载原始附件', 'Download source asset')
    }}</Button>
    <InlineError v-if="downloadError" :message="downloadError" />
  </div>
</template>
<script setup lang="ts">
import { computed, ref, onBeforeUnmount } from 'vue'
import { useI18n } from 'vue-i18n'
import Button from '@/shared/ui/components/Button.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import { readSampleAsset, type SampleMedia } from '../sample-media'
import type { DatasetSample } from '../services/dataset-workspace.service'
const props = defineProps<{
  sample: DatasetSample
  media: SampleMedia
  dataset: string
}>()
const { locale } = useI18n(),
  l = (zh: string, en: string) => (locale.value.startsWith('zh') ? zh : en)
const alignment = computed(() =>
  props.media.alignment === 'registered'
    ? l('导入时已配准', 'Registered at import')
    : props.media.alignment === 'unregistered'
      ? l('未配准', 'Unregistered')
      : l('未知', 'Unknown'),
)
const calibration = ref(''),
  error = ref(''),
  controller = new AbortController()
async function openCalibration(e: Event) {
  if (!(e.target as HTMLDetailsElement).open || calibration.value) return
  error.value = ''
  try {
    const blob = await readSampleAsset(
      props.dataset,
      props.sample,
      'calibration',
      controller.signal,
    )
    calibration.value = JSON.stringify(JSON.parse(await blob.text()), null, 2)
  } catch (e) {
    if (!controller.signal.aborted) error.value = String(e)
  }
}
const originalAsset = computed(() =>
  props.media.assets.find((k) => ['depth', 'cloud', 'mask'].includes(k)),
)
const downloading = ref(false),
  downloadError = ref('')
async function download() {
  const kind = originalAsset.value
  if (!kind || downloading.value) return
  downloadError.value = ''
  downloading.value = true
  try {
    const blob = await readSampleAsset(
      props.dataset,
      props.sample,
      kind,
      controller.signal,
    )
    if (controller.signal.aborted) return
    const link = document.createElement('a')
    link.href = URL.createObjectURL(blob)
    link.download =
      kind === 'cloud'
        ? props.sample.file_name
        : props.media.id + '-' + kind + '.png'
    link.click()
    setTimeout(() => URL.revokeObjectURL(link.href), 1000)
  } catch (e) {
    if (!controller.signal.aborted) downloadError.value = String(e)
  } finally {
    downloading.value = false
  }
}
onBeforeUnmount(() => controller.abort())
</script>
