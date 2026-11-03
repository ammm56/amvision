<template>
  <fieldset class="arc-fields"><legend>{{ band?label('选点环带','Selection band'):label('目标角域','Target angular domain') }}</legend>
    <GeometryFields :model-value="value" :fields="fields" @update:model-value="emit('update:modelValue',$event)" />
    <label v-for="field in angles" :key="field.key">{{ field.label }} (°)<input type="number" step="any" :value="degrees(value[field.key])" @change="angle(field.key,$event)"></label>
    <label>{{ label('三维手柄','3D handle') }}<select :value="handle" @change="emit('update:handle',($event.target as HTMLSelectElement).value as ArcHandle)"><option value="none">{{ label('关闭','Off') }}</option><option value="center">{{ label('中心 U/V','Center U/V') }}</option><option v-if="band" value="inner">{{ label('内半径','Inner radius') }}</option><option v-if="band" value="outer">{{ label('外半径','Outer radius') }}</option><option value="start">{{ label('起始角','Start angle') }}</option><option value="end">{{ label('结束角 / 扫角','End / sweep') }}</option></select></label>
    <p v-if="handle!=='none'&&!available" role="status">{{ label('当前输入与评价面未就绪','Current input and evaluation plane unavailable') }}</p>
  </fieldset>
</template>
<script setup lang="ts">
import {computed} from 'vue'
import {useI18n} from 'vue-i18n'
import GeometryFields from './GeometryFields.vue'
import {object,type Form,type Field} from './form'
import type {ArcHandle} from '@/workflows/workflow-editor/point-cloud/arc-edit'
const props=defineProps<{modelValue:unknown;band:boolean;unit:string;handle:ArcHandle|'none';available:boolean}>()
const emit=defineEmits<{'update:modelValue':[Form];'update:handle':[ArcHandle|'none']}>()
const {locale}=useI18n(),label=(cn:string,en:string)=>locale.value==='zh-CN'?cn:en
const value=computed(()=>object(props.modelValue))
const fields=computed<Field[]>(()=>[{path:'center',label:label('中心','Center'),type:'pair',components:['U','V'],unit:props.unit},...(props.band?[{path:'radius_range',label:label('半径范围','Radius range'),type:'pair' as const,unit:props.unit}]:[])])
const angles=computed(()=>[{key:'start_angle',label:label('起始角','Start angle')},{key:'sweep',label:label('扫角','Sweep')},...(props.band?[{key:'max_overlap_angle',label:label('片段最大角重叠','Maximum fragment overlap')}]:[])])
function degrees(value:unknown){return typeof value==='number'&&Number.isFinite(value)?value*180/Math.PI:''}
function angle(key:string,event:Event){const text=(event.target as HTMLInputElement).value;const number=text.trim()===''?null:Number(text)*Math.PI/180;emit('update:modelValue',{...value.value,[key]:number})}
</script>
<style scoped>
.arc-fields{display:grid;gap:8px;border:1px solid var(--am-border);padding:10px;min-width:0}.arc-fields label{display:grid;grid-template-columns:minmax(0,1fr) minmax(80px,130px);gap:8px;align-items:center;font-size:12px}.arc-fields input,.arc-fields select{min-width:0;width:100%;font:inherit;color:var(--am-text);background:var(--am-surface);border:1px solid var(--am-border);border-radius:4px;padding:6px}.arc-fields p{margin:0;font-size:12px}
</style>
