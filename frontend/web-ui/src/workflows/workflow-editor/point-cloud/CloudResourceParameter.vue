<template>
  <div class="cloud-parameter">
    <label>{{ t('source') }}<select :value="kind" :disabled="disabled" @change="changeMode(($event.target as HTMLSelectElement).value)">
      <option value="" disabled>{{ t('selectSource') }}</option>
      <option :value="liveKind">{{ t(liveKind) }}</option><option :value="assetKind">{{ t(assetKind) }}</option>
    </select></label>
    <label v-if="target && kind">{{ t('name') }}<input :value="name" maxlength="128" :disabled="disabled" @input="changeName(($event.target as HTMLInputElement).value)"></label>
    <CloudResourcePicker v-if="kind === assetKind" ref="picker" :model-value="reference" :disabled="disabled" @update:model-value="choose" @cancel="resetMode" />
  </div>
</template>
<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import CloudResourcePicker from './CloudResourcePicker.vue'
import type { MeasurementResourceReference } from '../services/measurement-resource.service'
const props = defineProps<{ modelValue: unknown; schema: Record<string, unknown>; disabled?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: unknown] }>()
const value = computed(() => props.modelValue && typeof props.modelValue === 'object' ? props.modelValue as Record<string, unknown> : {})
const target = computed(() => props.schema['x-ui-widget'] === 'cloud-target')
const liveKind = computed(() => target.value ? 'new' : String(props.schema['x-live-source-kind']))
const assetKind = computed(() => target.value ? 'new-version' : 'asset')
const kind = ref(''), name = ref('')
const picker = ref<InstanceType<typeof CloudResourcePicker>>()
function resetMode() { kind.value = String(value.value.kind || '') }
const reference = computed(() => value.value.reference as MeasurementResourceReference | undefined)
watch(() => [props.modelValue, props.schema], () => { resetMode(); name.value = String(value.value.name || '') }, { immediate: true })
function changeMode(mode: string) {
  kind.value = mode
  if (mode === liveKind.value) emit('update:modelValue', target.value ? {kind: mode, name: name.value} : {kind: mode})
  // 资产模式只在选择确定版本后提交，不向节点写入缺少 reference 的半成品。
  else void nextTick(() => picker.value?.show())
}
function changeName(text: string) {
  name.value = text
  if (kind.value === liveKind.value) emit('update:modelValue', {kind: kind.value, name: text})
  else if (reference.value) choose(reference.value)
}
function choose(selected: MeasurementResourceReference) {
  emit('update:modelValue', {kind: assetKind.value, reference: selected, ...(target.value ? {name: name.value} : {})})
}
const {t} = useI18n({useScope:'local',messages:{
  'zh-CN': {source:'来源',selectSource:'请选择',name:'资源名称',file:'本次文件输入',cloud:'本次点云输入',asset:'固定资源版本',new:'新建资源','new-version':'新增资源版本'},
  'en-US': {source:'Source',selectSource:'Select source',name:'Resource name',file:'Run file input',cloud:'Run cloud input',asset:'Fixed resource version',new:'New resource','new-version':'New resource version'},
}})
</script>
<style scoped>
.cloud-parameter {display:grid;gap:8px;min-width:0;}
.cloud-parameter label {display:grid;gap:4px;min-width:0;font-size:12px;}
.cloud-parameter input,.cloud-parameter select {width:100%;min-width:0;}
</style>
