<template>
  <button class="geometry-open" :disabled="disabled" @click="show">{{ label('标定轮廓', 'Calibrated profiles') }}</button>
  <Teleport to="body">
    <ConfirmDialog v-if="open" class="geometry-dialog" :title="label('扫描轮廓转点云', 'Profiles to cloud')" size="wide" scroll-body
      :confirm-label="label('应用', 'Apply')" :cancel-label="label('取消', 'Cancel')" :confirm-disabled="disabled || !profilesValid(draft)" @confirm="apply" @cancel="open = false">
      <MetrologyWorkspace>
        <template #parameters>
          <label>{{ label('输入来源', 'Input source') }}
            <select aria-label="Input source" :value="draft.kind" @change="changeInput">
              <option value="file">{{ label('NPZ 文件', 'NPZ file') }}</option>
              <option value="local-array">{{ label('同机标定数组', 'Same-host calibrated array') }}</option>
            </select>
          </label>
          <dl v-if="draft.kind === 'local-array'"><dt>{{ label('标定来源', 'Calibration source') }}</dt><dd>{{ label('本次载荷', 'Current payload') }}</dd></dl>
          <template v-else>
            <GeometryFields v-model="draft" :fields="inputFields" />
            <label class="mask"><input v-model="draft.has_validity" type="checkbox">{{ label('包含 validity 有效标记', 'Includes validity mask') }}</label>
            <fieldset><legend>{{ label('标定身份与坐标', 'Calibration and coordinates') }}</legend><GeometryFields v-model="draft" :fields="identityFields" /></fieldset>
            <fieldset><legend>{{ label('采集坐标基', 'Acquisition basis') }}</legend><GeometryFields v-model="draft" :fields="basisFields" /></fieldset>
            <label>{{ label('扫描位移', 'Scan displacement') }}
              <select aria-label="Scan displacement" :value="displacement.kind" @change="changeMethod">
                <option value="fixed-step">{{ label('原采集行号固定步距', 'Fixed step by acquisition ID') }}</option>
                <option value="encoder-positions">{{ label('逐行编码器位置', 'Per-profile encoder positions') }}</option>
              </select>
            </label>
            <GeometryFields v-model="draft" :fields="methodFields" />
            <p v-if="!profilesValid(draft)" role="status">{{ label('标定参数不完整或无效', 'Calibration parameters are incomplete or invalid') }}</p>
          </template>
        </template>
        <template #view="{ presentation }">
          <section class="profile-view">
            <CloudPreviewSelector v-model="previewId" :previews="previews" :changed="changed" />
            <CloudViewer v-if="preview" :key="preview.id" :presentation="presentation" :payload="preview.payload" :project-id="preview.projectId" allow-pick />
          </section>
        </template>
      </MetrologyWorkspace>
    </ConfirmDialog>
  </Teleport>
</template>
<script setup lang="ts">
import { computed, defineAsyncComponent, inject, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import ConfirmDialog from '@/shared/ui/components/ConfirmDialog.vue'
import { parameterCloudPreviewsKey, parameterPreviewStateKey, type ParameterEditorSources } from '@/workflows/workflow-editor/parameters/editor-context'
import GeometryFields from './GeometryFields.vue'
import MetrologyWorkspace from './MetrologyWorkspace.vue'
import CloudPreviewSelector from './CloudPreviewSelector.vue'
import { copy, object, put, type Form, type Field } from './form'
import { newDisplacement, newProfileInput, profilesValid } from './profile-form'

defineOptions({ inheritAttrs: false })
const props = defineProps<{ modelValue: unknown; nodeType: string; disabled?: boolean; inputSources?: ParameterEditorSources }>()
const emit = defineEmits<{ 'update:modelValue': [value: Form] }>()
const CloudViewer = defineAsyncComponent(() => import('@/workflows/workflow-editor/point-cloud/CloudViewer.vue'))
const { locale } = useI18n(), label = (cn: string, en: string) => locale.value === 'zh-CN' ? cn : en
const open = ref(false), draft = ref<Form>(newProfileInput()), initial = ref(''), previewId = ref('')
const displacement = computed(() => object(object(draft.value.profiles).displacement))
const resolve = inject(parameterCloudPreviewsKey, () => []), state = inject(parameterPreviewStateKey, () => ({ runId: '', succeeded: false }))
const previews = computed(() => state().succeeded ? resolve() : []), preview = computed(() => previews.value.find(p => p.id === previewId.value))
const changed = computed(() => JSON.stringify(draft.value) !== initial.value)
const field = (path: string, cn: string, en: string, type?: Field['type'], options?: string[]): Field => ({ path, label: label(cn,en), type, options })
const inputFields = computed(() => [field('profiles.point_count','原始样点总数','Original sample count','number'), field('profiles.profile_count','采集行数（含空行）','Profile count (including empty)','number'), field('profiles.dtype','原值类型','Raw type','select',['float32','float64']), field('profiles.position_dtype','坐标存储类型','Position type','select',['float32','float64'])])
const identityFields = computed(() => [field('profiles.calibration_id','标定 ID','Calibration ID'), field('profiles.calibration_revision','标定修订','Calibration revision'), field('profiles.spatial.frame_id','输出坐标系','Output frame'), field('profiles.spatial.length_unit','长度单位','Length unit','select',['m','mm','um'])])
const basisFields = computed(() => [field('profiles.origin','扫描零位原点','Scan-zero origin','vector'), field('profiles.x_direction','轮廓 X 单位方向','Profile X unit direction','vector'), field('profiles.scan_direction','扫描单位方向','Scan unit direction','vector'), field('profiles.height_direction','高度单位方向','Height unit direction','vector')])
const methodFields = computed(() => displacement.value.kind === 'encoder-positions'
  ? [field('profiles.displacement.dtype','编码器原值类型','Encoder raw type','select',['float32','float64']),field('profiles.displacement.scale','编码器物理乘数','Encoder physical multiplier','number'),field('profiles.displacement.origin','编码器零位原值','Encoder zero raw value','number')]
  : [field('profiles.displacement.origin_line_id','零位采集行号','Zero-position acquisition ID','number'),field('profiles.displacement.step','物理步距','Physical spacing','number')])
function show() { draft.value = props.modelValue && typeof props.modelValue === 'object' ? copy(object(props.modelValue)) : newProfileInput(); initial.value = JSON.stringify(draft.value); previewId.value = ''; open.value = true }
function changeInput(e: Event) { draft.value = newProfileInput((e.target as HTMLSelectElement).value) }
function changeMethod(e: Event) { draft.value = put(draft.value,'profiles.displacement',newDisplacement((e.target as HTMLSelectElement).value)) }
function apply() { if (!props.disabled && profilesValid(draft.value)) { emit('update:modelValue',copy(draft.value)); open.value = false } }
watch([() => props.modelValue, () => props.nodeType, () => props.disabled, () => JSON.stringify(props.inputSources)], () => { open.value = false; previewId.value = '' })
watch(() => [state().runId,state().succeeded], () => { previewId.value = '' })
</script>
<style src="./editor.css" scoped></style>
<style scoped>
label { display:grid; gap:6px; margin:10px 0; min-width:0 }
select { width:100%; min-width:0; background:var(--am-input); color:var(--am-text); border:1px solid var(--am-border); border-radius:4px; padding:6px }
fieldset { margin:12px 0; padding:10px; border:1px solid var(--am-border); min-width:0 }
legend,p { font-size:13px }
.mask { display:flex; align-items:center; gap:8px }
.profile-view { display:grid; gap:10px; min-width:0 }
.geometry-dialog :deep(.confirm-dialog) { width:min(1240px,calc(100vw - 36px)) }
</style>
