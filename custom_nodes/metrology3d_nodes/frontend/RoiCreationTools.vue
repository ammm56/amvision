<template><div class="roi-create">
  <template v-if="supported">
    <label>{{ zh?'创建平面':'Creation plane' }}<select v-model="plane"><option value="xy">XY</option><option value="xz">XZ</option><option value="yz">YZ</option></select></label>
    <template v-if="!section">
      <label>{{ zh?'轴向下限':'Axial minimum' }}<input v-model.number="low" type="number" step="any" /></label>
      <label>{{ zh?'轴向上限':'Axial maximum' }}<input v-model.number="high" type="number" step="any" /></label>
      <button :disabled="!payload" :title="zh?'取输入点云轴向范围':'Use input axial bounds'" @click="bounds"><Maximize :size="16" /></button>
    </template>
    <button :disabled="!valid" :aria-pressed="active" :title="section&&!valid?(zh?'先配置厚度和有限边界，再查看输入点云':'Configure thickness, finite bound and input preview first'):undefined" @click="active?cancel():start()"><Crosshair :size="16" />{{ section?(active?(zh?'选择截面原点':'Select section origin'):(zh?'拾取截面原点':'Pick section origin')):active?(first?(zh?'选择第二点':'Select second point'):(zh?'选择第一点':'Select first point')):(zh?'两点创建':'Create with two points') }}</button>
    <p v-if="error" role="alert">{{ error }}</p>
  </template>
</div></template>
<script setup lang="ts">
import {computed,onBeforeUnmount,ref,watch} from 'vue'
import {useI18n} from 'vue-i18n'
import {Crosshair,Maximize} from '@lucide/vue'
import {object,type Form} from './form'
import {createPickedRoi,createPickedSection,previewAxisRange} from './roi-creation'
const props=defineProps<{roi?:Form;payload?:Form;scope:string}>(),emit=defineEmits<{change:[roi:Form];active:[value:boolean]}>()
const {locale}=useI18n(),zh=computed(()=>locale.value==='zh-CN'),plane=ref('xy'),low=ref<number|string>(''),high=ref<number|string>(''),active=ref(false),first=ref<number[]|null>(null),error=ref('')
const section=computed(()=>props.roi?.kind==='section-band'),supported=computed(()=>['box','cylinder','section-band'].includes(String(props.roi?.kind)))
const valid=computed(()=>{const g=object(props.roi?.geometry);return supported.value&&!!props.payload&&(section.value?typeof g.thickness==='number'&&Number.isFinite(g.thickness)&&g.thickness>0&&typeof g.bounds_roi_id==='string'&&!!g.bounds_roi_id&&g.bounds_roi_id!==props.roi?.roi_id:typeof low.value==='number'&&typeof high.value==='number'&&Number.isFinite(low.value)&&Number.isFinite(high.value)&&high.value>low.value)})
function cancel(){active.value=false;first.value=null}
function start(){if(valid.value){first.value=null;error.value='';active.value=true}}
function bounds(){const range=previewAxisRange(props.payload??{},plane.value);if(range){low.value=range[0]!;high.value=range[1]!}}
function pick(event:{payload:Form;xyz:number[]}){
  if(!active.value||event.payload!==props.payload||!valid.value)return
  if(section.value){try{const value=createPickedSection(props.roi!,object(props.payload?.spatial),plane.value,event.xyz);cancel();emit('change',value)}catch{error.value=zh.value?'截面参数或拾取位置无效':'Invalid section parameters or picked position'};return}
  if(!first.value){first.value=[...event.xyz];return}
  try{const value=createPickedRoi(props.roi!,object(props.payload?.spatial),plane.value,first.value,event.xyz,Number(low.value),Number(high.value));cancel();emit('change',value)}catch{error.value=zh.value?'两点不能定义有限 ROI，请重新选择':'These points do not define a finite ROI';first.value=null}
}
watch(active,value=>emit('active',value),{flush:'sync'})
watch(()=>[props.scope,props.payload,JSON.stringify(props.roi),plane.value,low.value,high.value],()=>{cancel();error.value=''})
onBeforeUnmount(cancel)
defineExpose({pick})
</script>
<style scoped>.roi-create{display:flex;gap:6px;align-items:end;flex-wrap:wrap}.roi-create label{display:grid;gap:3px;font-size:12px;min-width:80px;flex:1}.roi-create input,.roi-create select{width:100%;min-width:0}.roi-create button{display:flex;gap:4px;align-items:center}.roi-create p{width:100%;margin:0}</style>
