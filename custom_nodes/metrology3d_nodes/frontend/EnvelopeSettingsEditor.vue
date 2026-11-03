<template>
  <fieldset><legend>{{ label('可见包络','Visible envelope') }}</legend>
    <label>{{ label('目标分区','Target partition') }}<select :value="get(modelValue,'selection.kind')" @change="emit('update:modelValue',selectEnvelopePartition(modelValue,($event.target as HTMLSelectElement).value))"><option value="grid-connected">{{ label('栅格连通','Grid connectivity') }}</option><option value="distance-connected">{{ label('实际距离连通','Physical distance connectivity') }}</option></select></label>
    <GeometryFields :model-value="modelValue" :fields="fields" @update:model-value="emit('update:modelValue',$event)" />
    <label v-if="get(modelValue,'selection.kind')==='grid-connected'">{{ label('连通邻域','Connectivity') }}<select :value="get(modelValue,'selection.connectivity')??''" @change="set('selection.connectivity',Number(($event.target as HTMLSelectElement).value))"><option value="" disabled></option><option :value="4">4</option><option :value="8">8</option></select></label>
    <label>{{ label('前景方向','Foreground') }}<select :value="get(modelValue,'profiles.foreground')??''" @change="set('profiles.foreground',($event.target as HTMLSelectElement).value)"><option value="" disabled></option><option value="above">{{ label('高于截面','Above plane') }}</option><option value="below">{{ label('低于截面','Below plane') }}</option></select></label>
    <label>{{ label('边界位置','Edge position') }}<select :value="get(modelValue,'profiles.edge_policy')??''" @change="set('profiles.edge_policy',($event.target as HTMLSelectElement).value)"><option value="" disabled></option><option value="cell-edge">{{ label('格边','Cell edge') }}</option><option value="interpolate-or-cell-edge">{{ label('格中心阈值插值／格边估计','Threshold interpolation / cell edge') }}</option></select></label>
  </fieldset>
</template>
<script setup lang="ts">
import {computed} from 'vue'
import {useI18n} from 'vue-i18n'
import GeometryFields from './GeometryFields.vue'
import {get,put,type Form,type Field} from './form'
import {selectEnvelopePartition} from './envelope-form'
const props=defineProps<{modelValue:Form}>(),emit=defineEmits<{'update:modelValue':[value:Form]}>()
const {locale}=useI18n(),label=(cn:string,en:string)=>locale.value==='zh-CN'?cn:en
const fields=computed<Field[]>(()=>[
  {path:'grid.origin',label:label('栅格原点 U/V','Grid origin U/V'),type:'pair'},
  {path:'grid.step',label:label('栅格步长','Grid step'),type:'number'},
  {path:'grid.shape',label:label('栅格数 U/V','Grid counts U/V'),type:'pair'},
  {path:'grid.min_cell_count',label:label('每格最少观测数','Minimum observations per cell'),type:'number'},
  {path:'selection.seed_min',label:label('种子窗口最小 U/V','Seed minimum U/V'),type:'pair'},
  {path:'selection.seed_max',label:label('种子窗口最大 U/V','Seed maximum U/V'),type:'pair'},
  get(props.modelValue,'selection.kind')==='distance-connected'
    ?{path:'selection.connection_distance',label:label('面内连接距离','In-plane connection distance'),type:'number'}
    :{path:'selection.closing_radius_cells',label:label('闭运算半径（格，0 禁用）','Closing radius (cells, 0 off)'),type:'number'},
  {path:'profiles.min_observed_length',label:label('剖面最少观测长度','Minimum observed profile length'),type:'number'},
])
function set(path:string,value:unknown){emit('update:modelValue',put(props.modelValue,path,value))}
</script>
<style scoped>
fieldset{display:grid;gap:10px;min-width:0;border:1px solid var(--am-border);padding:8px}label{display:grid;gap:4px;font-size:12px;min-width:0}select{width:100%;min-width:0;padding:6px;background:var(--am-input);color:var(--am-text);border:1px solid var(--am-border);border-radius:4px}
</style>
