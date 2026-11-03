<template>
  <button type="button" class="roi-visibility" :aria-label="title" :title="title" :aria-pressed="state==='partial'?'mixed':state==='visible'" :disabled="disabled||state==='unavailable'" @click="$emit('toggle')">
    <EyeOff v-if="state==='hidden'" :size="17" /><Eye v-else :size="17" />
    <span v-if="state==='partial'" class="roi-mixed" aria-hidden="true" />
  </button>
</template>
<script setup lang="ts">
import {computed} from 'vue'
import {useI18n} from 'vue-i18n'
import {Eye, EyeOff} from '@lucide/vue'
import type {RoiVisibility} from './roi-visibility'
const props=defineProps<{state:RoiVisibility;roiId:string;disabled?:boolean}>()
defineEmits<{toggle:[]}>()
const {locale}=useI18n()
const title=computed(()=>{
  const zh=locale.value==='zh-CN'
  const text=props.disabled||props.state==='unavailable'?(zh?'区域显示不可用':'Region display unavailable'):props.state==='partial'?(zh?'部分显示，点击全部显示':'Partly visible; show all'):props.state==='visible'?(zh?'隐藏区域':'Hide region'):(zh?'显示区域':'Show region')
  return `${text} · ${props.roiId}`
})
</script>
<style scoped>
.roi-visibility{position:relative;display:inline-grid;place-items:center;flex:none;width:30px;height:30px;padding:0;border:1px solid var(--am-border);border-radius:4px;background:var(--am-surface);color:var(--am-text);cursor:pointer}.roi-visibility:disabled{opacity:.5;cursor:default}.roi-mixed{position:absolute;bottom:3px;width:10px;height:2px;background:currentColor}.roi-visibility:focus-visible{outline:2px solid var(--am-brand-primary);outline-offset:2px}
</style>
