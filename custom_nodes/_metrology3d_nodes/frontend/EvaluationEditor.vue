<template>
  <label>{{ label('评价面来源','Evaluation source') }}<select :value="kind" :disabled="pose" @change="change(($event.target as HTMLSelectElement).value)">
    <option v-if="!pose" value="configured">{{ label('显式配置','Configured') }}</option>
    <option v-if="allowFeature" value="feature">{{ label('继承所选特征','Selected feature') }}</option>
    <option v-if="pose" value="pose">{{ label('本次位姿与等高值','Current pose and contour height') }}</option>
  </select></label>
  <GeometryFields :model-value="{evaluation:object(modelValue)}" :fields="fields" :suggestions="suggestions" @update:model-value="$emit('update:modelValue',$event.evaluation)" />
</template>
<script setup lang="ts">
import {computed} from 'vue'
import {useI18n} from 'vue-i18n'
import GeometryFields from './GeometryFields.vue'
import {object,type Field} from './form'
import {newEvaluation} from './evaluation-form'
const props=defineProps<{modelValue:unknown;allowFeature?:boolean;pose?:boolean;suggestions?:Record<string,string[]>}>()
const emit=defineEmits<{'update:modelValue':[value:unknown]}>()
const {locale}=useI18n(),label=(cn:string,en:string)=>locale.value==='zh-CN'?cn:en
const kind=computed(()=>String(object(props.modelValue).kind??'configured'))
const fields=computed<Field[]>(()=>[
  {path:'evaluation.frame_id',label:label('源坐标系','Source frame')},
  {path:'evaluation.length_unit',label:label('长度单位','Length unit'),type:'select',options:['m','mm','um']},
  ...(kind.value==='pose'?[{path:'evaluation.pose_id',label:label('本次位姿 ID','Current pose ID')},{path:'evaluation.target_frame_id',label:label('基准坐标系','Datum frame')}]:kind.value==='feature'?[]:[{path:'evaluation.origin',label:label('评价原点 XYZ','Evaluation origin XYZ'),type:'vector' as const},{path:'evaluation.rotation',label:label('评价 U/V/N','Evaluation U/V/N'),type:'matrix' as const}]),
])
function change(value:string){emit('update:modelValue',newEvaluation(value,props.modelValue))}
</script>
