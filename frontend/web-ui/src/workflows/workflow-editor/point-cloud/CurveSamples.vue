<template>
  <section v-if="curve.angular_weights" class="curve-samples">
    <div class="sample-tools"><span>{{ zh?'逐点证据':'Point evidence' }} · {{ zh?'完整已选支持':'Complete selected support' }} {{ rowCount }}</span><button :aria-label="zh?'上一页':'Previous page'" :title="zh?'上一页':'Previous page'" :disabled="page===0" @click="page--"><ChevronLeft :size="16" /></button><span>{{ page+1 }} / {{ pages }}</span><button :aria-label="zh?'下一页':'Next page'" :title="zh?'下一页':'Next page'" :disabled="page+1>=pages" @click="page++"><ChevronRight :size="16" /></button></div>
    <table><thead><tr><th>{{ zh?'支持序号 / 片段':'Support index / segment' }}</th><th>{{ zh?'角区':'Sector' }}</th><th>{{ zh?'均衡权重':'Balancing weight' }}</th><th>{{ zh?'拟合几何径向残差':'Fitted-geometry radial residual' }}</th><th>{{ zh?'残差分类':'Residual class' }}</th></tr></thead><tbody><tr v-for="row in visible" :key="row.index" :class="{selected:row.index===selectedIndex}"><td><button :aria-pressed="row.index===selectedIndex" @click="emit('select-point',row.index)">{{ row.index }}</button> / {{ row.segment }}</td><td>{{ curve.angular_sectors?.[row.index] }}</td><td>{{ curve.angular_weights[row.index] }}</td><td>{{ curve.radial_residuals?.[row.index] }} {{ unit }}</td><td>{{ curve.inlier_flags?.[row.index]?(zh?'内点':'Inlier'):(zh?'外点':'Outlier') }}</td></tr></tbody></table>
  </section>
</template>
<script setup lang="ts">
import {computed,ref,watch} from 'vue'
import {useI18n} from 'vue-i18n'
import {ChevronLeft,ChevronRight} from '@lucide/vue'
import type {CurveDisplay} from './boundary-display'
const props=defineProps<{curve:CurveDisplay;segment:string;unit:string;selectedIndex?:number|null}>()
const emit=defineEmits<{'select-point':[index:number]}>()
const {locale}=useI18n(),zh=computed(()=>locale.value==='zh-CN'),page=ref(0)
const segments=computed(()=>props.curve.topology?.segments.filter(s=>!props.segment||s.segment_id===props.segment||s.group_id===props.segment)??[])
const rowCount=computed(()=>segments.value.reduce((total,s)=>total+s.count,0))
const pages=computed(()=>Math.max(1,Math.ceil(rowCount.value/20))),visible=computed(()=>{
  const rows:{index:number;segment:string}[]=[];let offset=page.value*20
  for(const s of segments.value){if(offset>=s.count){offset-=s.count;continue}for(let i=offset;i<s.count&&rows.length<20;i++)rows.push({index:s.start+i,segment:s.segment_id});offset=0;if(rows.length===20)break}
  return rows
})
watch(()=>[props.curve,props.segment],()=>{page.value=0},{flush:'sync'})
watch(()=>[props.selectedIndex,props.segment],()=>{let offset=0;for(const s of segments.value){if(props.selectedIndex!=null&&props.selectedIndex>=s.start&&props.selectedIndex<s.start+s.count){page.value=Math.floor((offset+props.selectedIndex-s.start)/20);return}offset+=s.count}},{flush:'post',immediate:true})
</script>
<style scoped>
.sample-tools{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.sample-tools button{display:grid;place-items:center;width:28px;height:28px;background:var(--am-surface);border:1px solid var(--am-border);border-radius:4px;color:var(--am-text)}table{width:100%;border-collapse:collapse;font-size:12px}th,td{text-align:left;padding:5px;border-bottom:1px solid var(--am-border);overflow-wrap:anywhere}
</style>
<style scoped>.selected{background:var(--am-surface-soft)}td button{font:inherit;color:var(--am-text);background:var(--am-surface);border:1px solid var(--am-border);border-radius:4px;min-width:28px;min-height:28px}</style>
