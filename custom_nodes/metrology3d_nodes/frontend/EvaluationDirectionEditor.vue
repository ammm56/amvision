<template>
  <label>{{ label }}<select :value="axis?'axis':'vector'" @change="change(($event.target as HTMLSelectElement).value)"><option value="vector">{{ text('源坐标方向 XYZ','Source direction XYZ') }}</option><option value="axis">{{ text('评价面轴向','Evaluation axis') }}</option></select></label>
  <GeometryFields :model-value="{direction:modelValue}" :fields="fields" @update:model-value="$emit('update:modelValue',$event.direction)" />
</template>
<script setup lang="ts">
import {computed} from 'vue'
import {useI18n} from 'vue-i18n'
import GeometryFields from './GeometryFields.vue'
import {object,type Field} from './form'
import {evaluationAxes} from './evaluation-form'
const props=defineProps<{modelValue:unknown;label:string}>(),emit=defineEmits<{'update:modelValue':[value:unknown]}>()
const {locale}=useI18n(),text=(cn:string,en:string)=>locale.value==='zh-CN'?cn:en
const axis=computed(()=>object(props.modelValue).kind==='axis')
const fields=computed<Field[]>(()=>axis.value?[{path:'direction.axis',label:text('轴向','Axis'),type:'select',options:evaluationAxes}]:[{path:'direction',label:props.label,type:'vector'}])
function change(kind:string){emit('update:modelValue',kind==='axis'?{kind,axis:null}:[null,null,null])}
</script>
