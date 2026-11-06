<template>
  <section class="height-map-panel">
    <p v-if="error" role="alert">{{ errorText }}</p><p v-else-if="loading" role="status">{{ label('正在读取高度图','Loading height map') }}</p>
    <template v-if="grid">
      <div class="height-controls"><strong>{{ label('高度图','Height map') }}</strong><span>{{ methods[grid.aggregation] }} · {{ grid.width }} × {{ grid.height }} · {{ grid.unit }}</span><span>{{ label('有数据格','Occupied cells') }} {{ grid.occupied }} · {{ label('格外点','Outside points') }} {{ grid.outside }}</span></div>
      <div class="height-controls"><label>{{ label('行（从 0 开始）','Row (zero-based)') }}<input v-model.number="row" type="number" min="0" :max="grid.height-1" step="1" @change="select" /></label><label>{{ label('列（从 0 开始）','Column (zero-based)') }}<input v-model.number="column" type="number" min="0" :max="grid.width-1" step="1" @change="select" /></label><button :disabled="!selected?.corners" :title="label('聚焦所选格','Focus selected cell')" :aria-label="label('聚焦所选格','Focus selected cell')" @click="emit('focus',{payload:loadedPayload!,corners:selected!.corners!})"><Focus :size="18" /></button></div>
      <div class="height-image"><canvas ref="canvas" :style="{aspectRatio:`${grid.width*grid.columnStep} / ${grid.height*grid.rowStep}`,width:`min(100%, ${400*grid.width*grid.columnStep/(grid.height*grid.rowStep)}px)`}" :aria-label="label('物理高度网格','Physical height grid')" @click="pick" /></div>
      <div class="height-legend"><span>{{ format(grid.minimum) }}</span><i/><span>{{ format(grid.maximum) }} {{ grid.unit }}</span><span class="empty-key"/>{{ label('无数据','No data') }}</div>
      <dl v-if="selected"><dt>{{ label('高度','Height') }}</dt><dd>{{ format(selected.height) }} {{ selected.height===null?'':grid.unit }}</dd><dt>{{ label('贡献点数','Contributors') }}</dt><dd>{{ selected.count }}</dd><dt>{{ label('高度范围','Height range') }}</dt><dd>{{ format(selected.min) }} .. {{ format(selected.max) }}</dd></dl>
    </template>
  </section>
</template>
<script setup lang="ts">
import {computed,nextTick,onBeforeUnmount,ref,shallowRef,watch} from 'vue'
import {useI18n} from 'vue-i18n'
import {Focus} from '@lucide/vue'
import {readCloudCapabilities} from '../services/measurement-resource.service'
import {decodeHeightMap,type HeightCell} from './height-map-display'
import {coordinateColor,displayNumber} from './view-presentation'
const props=defineProps<{payload:Record<string,unknown>;projectId:string}>()
const emit=defineEmits<{select:[value:{payload:Record<string,unknown>;corners:number[][]|null}];focus:[value:{payload:Record<string,unknown>;corners:number[][]}]}>()
const {locale}=useI18n(),label=(cn:string,en:string)=>locale.value==='zh-CN'?cn:en
const methods=computed<Record<string,string>>(()=>({minimum:label('最小值','Minimum'),maximum:label('最大值','Maximum'),mean:label('平均值','Mean'),median:label('中位数','Median')}))
const canvas=ref<HTMLCanvasElement>(),grid=shallowRef<Awaited<ReturnType<typeof decodeHeightMap>>|null>(null),selected=ref<HeightCell|null>(null),row=ref(0),column=ref(0),loading=ref(false),error=ref('')
let controller:AbortController|null=null,generation=0,loadedPayload:Record<string,unknown>|null=null
const format=(value:number|null)=>value===null?label('无数据','No data'):displayNumber(value)
const errorText=computed(()=>['preview_size_limit','cloud_preview_capacity','cloud_cpu_capacity','cloud_canvas_capacity'].includes(error.value)?label('完整高度网格超过显示预算','Complete height grid exceeds display budget'):error.value==='preview_allocation_failed'?label('高度图显示内存不足','Height map display allocation failed'):label('高度图数据不可用或校验失败','Height map unavailable or invalid'))
function release(){generation++;controller?.abort();controller=null;grid.value?.dispose();grid.value=null;selected.value=null;if(loadedPayload)emit('select',{payload:loadedPayload,corners:null});loadedPayload=null;if(canvas.value){canvas.value.width=1;canvas.value.height=1}}
function draw(){const c=canvas.value,g=grid.value;if(!c||!g)return;c.width=g.width;c.height=g.height;const context=c.getContext('2d');if(!context)throw new Error('cloud_canvas_capacity');const image=context.createImageData(g.width,g.height)
  for(let i=0;i<g.width*g.height;i++){const value=g.value(i),color=Number.isFinite(value)?coordinateColor(value,{min:g.minimum!,max:g.maximum!}):[.32,.34,.36],target=((g.height-1-Math.floor(i/g.width))*g.width+i%g.width)*4;for(let k=0;k<3;k++)image.data[target+k]=Math.round(color[k]!*255);image.data[target+3]=255}
  context.putImageData(image,0,0);if(selected.value){context.strokeStyle='#ffffff';context.lineWidth=.15;context.strokeRect(selected.value.column+.075,g.height-1-selected.value.row+.075,.85,.85)}}
function select(){const g=grid.value,payload=loadedPayload;if(!g||!payload)return;try{selected.value=g.cell(row.value,column.value)}catch{selected.value=null}emit('select',{payload,corners:selected.value?.corners??null});draw()}
function pick(event:MouseEvent){const g=grid.value,c=canvas.value;if(!g||!c)return;const rect=c.getBoundingClientRect();if(!rect.width||!rect.height)return;column.value=Math.min(g.width-1,Math.max(0,Math.floor((event.clientX-rect.left)/rect.width*g.width)));row.value=g.height-1-Math.min(g.height-1,Math.max(0,Math.floor((event.clientY-rect.top)/rect.height*g.height)));select()}
async function load(){release();error.value='';loading.value=true;const token=generation,payload=props.payload;controller=new AbortController();const signal=controller.signal
  try{const raw=payload.height_map as Record<string,unknown>;if(raw?.state!=='ready')throw new Error(String(raw?.reason??'cloud_preview_invalid'));const policy=(await readCloudCapabilities(props.projectId,signal)).renderer;if(!policy)throw new Error('cloud_renderer_unconfigured');const value=await decodeHeightMap(payload,policy,signal);if(signal.aborted||token!==generation){value.dispose();return}loadedPayload=payload;grid.value=value;row.value=0;column.value=0;await nextTick();if(signal.aborted||token!==generation)return;draw()}
  catch(e){if(!signal.aborted&&token===generation){grid.value?.dispose();grid.value=null;error.value=e instanceof Error?e.message:'cloud_preview_invalid'}}
  finally{if(token===generation)loading.value=false}}
watch(()=>[props.payload,props.projectId],()=>void load(),{immediate:true})
onBeforeUnmount(release)
</script>
<style scoped>
.height-map-panel{min-width:0;display:grid;gap:10px}.height-controls{display:flex;flex-wrap:wrap;gap:10px;align-items:center;font-size:12px}.height-controls label{display:flex;align-items:center;gap:6px}.height-controls input{width:72px;min-width:0;color:var(--am-text);background:var(--am-input);border:1px solid var(--am-border);padding:5px;border-radius:4px}.height-controls button{width:30px;height:30px;display:grid;place-items:center}.height-image{display:flex;justify-content:center;max-height:420px;overflow:auto;background:#202326}.height-image canvas{display:block;max-width:100%;max-height:400px;object-fit:contain;image-rendering:pixelated;width:auto;height:auto;cursor:crosshair}.height-legend{display:flex;gap:8px;align-items:center;font-size:12px;flex-wrap:wrap}.height-legend i{width:100px;height:10px;background:linear-gradient(90deg,#313695,#74add1,#ffffbf,#f46d43,#a50026)}.empty-key{width:12px;height:12px;background:#52575c}dl{display:grid;grid-template-columns:auto 1fr;gap:6px 12px;font-size:12px;margin:0}dd{margin:0;overflow-wrap:anywhere}p{font-size:13px}
.height-image canvas{object-fit:fill;height:auto;max-height:none;align-self:flex-start;flex:none}.height-legend i{background:linear-gradient(90deg,#00f,#0ff,#0f0,#ff0,#f00)}
</style>
