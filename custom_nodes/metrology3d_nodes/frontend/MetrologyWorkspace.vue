<template>
  <div ref="host" class="metrology-workspace" :class="{compact}">
    <div v-if="compact" class="workspace-tabs" role="tablist" :aria-label="zh?'测量编辑区域':'Measurement workspace'">
      <button v-for="tab in tabs" :id="`${id}-${tab.id}`" :key="tab.id" type="button" role="tab" :aria-selected="selected===tab.id" :aria-controls="`${id}-${tab.id==='parameters'?'parameters':'view'}-panel`" :tabindex="selected===tab.id?0:-1" @click="selected=tab.id" @keydown="navigateTab($event,tabs.map(t=>t.id),selected,value=>selected=value)">{{ tab.label }}</button>
    </div>
    <div class="workspace-content">
      <section v-show="!compact||selected==='parameters'" :id="`${id}-parameters-panel`" class="workspace-parameters" :role="compact?'tabpanel':undefined" :aria-labelledby="compact?`${id}-parameters`:undefined"><slot name="parameters" /><slot name="advanced" /></section>
      <section v-show="!compact||selected!=='parameters'" :id="`${id}-view-panel`" class="workspace-view" :role="compact?'tabpanel':undefined" :aria-labelledby="compact?`${id}-${selected}`:undefined"><slot name="view" :presentation="presentation" /></section>
    </div>
    <div class="workspace-issues"><slot name="issues" /></div>
  </div>
</template>
<script setup lang="ts">
import {computed,onBeforeUnmount,onMounted,ref,useId} from 'vue'
import {useI18n} from 'vue-i18n'
import {navigateTab} from '@/workflows/workflow-editor/point-cloud/tab-navigation'
const {locale}=useI18n(),zh=computed(()=>locale.value==='zh-CN'),id=useId()
const host=ref<HTMLElement>(),compact=ref(false),selected=ref('parameters')
const tabs=computed(()=>[{id:'parameters',label:zh.value?'参数':'Parameters'},{id:'view',label:zh.value?'三维':'3D'},{id:'evidence',label:zh.value?'证据':'Evidence'}])
const presentation=computed<'full'|'hidden'|'view'|'evidence'>(()=>!compact.value?'full':selected.value==='parameters'?'hidden':selected.value==='view'?'view':'evidence')
let observer:ResizeObserver|undefined
let frame=0,closed=false
function measure(){
  if(!host.value)return
  const height=host.value.ownerDocument.documentElement.clientHeight
  compact.value=host.value.getBoundingClientRect().width<900||(height>0&&height<640)
}
// 布局切换会改变被观察区域高度；延后写入，避免同次 ResizeObserver 交付循环。
function scheduleMeasure(){
  if(closed||frame)return
  frame=requestAnimationFrame(()=>{frame=0;if(!closed)measure()})
}
onMounted(()=>{
  observer=new ResizeObserver(scheduleMeasure);if(host.value)observer.observe(host.value);measure()
  window.addEventListener('resize',scheduleMeasure)
})
onBeforeUnmount(()=>{closed=true;observer?.disconnect();cancelAnimationFrame(frame);frame=0;window.removeEventListener('resize',scheduleMeasure)})
</script>
<style scoped>
.metrology-workspace{min-width:0;display:grid;gap:10px}.workspace-content{display:grid;grid-template-columns:minmax(280px,370px) minmax(0,1fr);gap:12px;align-items:start;min-width:0}.workspace-parameters,.workspace-view{display:grid;gap:12px;min-width:0;min-height:0}.workspace-parameters{max-height:60dvh;overflow:auto;padding-right:4px}.workspace-view{position:sticky;top:0}.workspace-view :deep(.cloud-viewer){height:min(60dvh,660px)}.workspace-issues:empty{display:none}.workspace-issues{min-width:0;overflow-wrap:anywhere}.workspace-tabs{display:flex;border-bottom:1px solid var(--am-border);gap:4px}.workspace-tabs button{flex:1;min-width:0;font:inherit;font-size:13px;padding:8px 12px;border:0;background:transparent;color:var(--am-text);cursor:pointer}.workspace-tabs button[aria-selected=true]{box-shadow:inset 0 -2px var(--am-brand-primary);font-weight:600}.workspace-tabs button:focus-visible{outline:2px solid var(--am-brand-primary);outline-offset:-2px}.compact .workspace-content{grid-template-columns:minmax(0,1fr)}.compact .workspace-parameters{max-height:55dvh}.compact .workspace-view{position:static}.compact .workspace-view :deep(.cloud-viewer){height:55dvh;min-height:260px}
</style>
