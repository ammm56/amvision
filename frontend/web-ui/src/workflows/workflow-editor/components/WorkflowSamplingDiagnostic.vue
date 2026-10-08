<template>
  <section class="sampling-diagnostic" :aria-label="text.title">
    <strong>{{ text.title }} · {{ diagnostic.pin_id }}</strong>
    <p>{{ diagnostic.state }}<span v-if="diagnostic.reason"> · {{ diagnostic.reason }}</span></p>
    <p v-if="available">{{ text.coverage }} {{ coverage }} · {{ text.residual }} {{ residual }} px</p>
    <template v-if="available">
      <figure v-for="chart in charts" :key="chart.label">
        <figcaption>{{ chart.label }}</figcaption>
        <svg viewBox="0 0 640 130" role="img" :aria-label="chart.label">
          <path d="M32 10 V110 H624" class="axis" />
          <line v-for="(threshold,index) in chart.thresholds" :key="index" x1="32" x2="624" :y1="threshold" :y2="threshold" class="threshold" />
          <polyline :points="chart.points" class="curve" />
          <text x="32" y="127">{{ extent[0].toFixed(1) }}</text><text x="622" y="127" text-anchor="end">{{ extent[1].toFixed(1) }} px</text>
          <text x="32" y="9">{{ chart.max.toPrecision(3) }}</text><text x="32" y="108">{{ chart.min.toPrecision(3) }}</text>
        </svg>
      </figure>
      <p>{{ text.note }} · {{ diagnostic.scan_lines }} {{ text.lines }} · {{ diagnostic.polarity }}</p>
      <div class="sampling-pairs"><table><thead><tr><th>{{ text.across }}</th><th>{{ text.left }}</th><th>{{ text.right }}</th><th>{{ text.fit }}</th></tr></thead>
        <tbody><tr v-for="(pair,index) in pairs" :key="index"><td>{{ pair.values[0].toFixed(3) }}</td><td>{{ pair.values[1].toFixed(3) }}</td><td>{{ pair.values[2].toFixed(3) }}</td><td>{{ pair.inlier ? text.kept : text.rejected }}</td></tr></tbody>
      </table></div>
    </template>
    <p v-else>{{ text.noProfile }}</p>
  </section>
</template>
<script setup lang="ts">
import {computed} from 'vue'
import {useI18n} from 'vue-i18n'
const props=defineProps<{diagnostic:Record<string,unknown>}>()
const {locale}=useI18n()
const text=computed(()=>locale.value==='zh-CN'?{title:'上次预览剖面',coverage:'覆盖率',residual:'最大拟合残差',intensity:'平均灰度（0–1）',gradient:'按极性归一化的平均梯度',note:'曲线最多显示 1024 点；检测使用全部采样。虚线为各扫描线的梯度阈值范围。',lines:'条扫描线',across:'横向位置 px',left:'左边缘 px',right:'右边缘 px',fit:'拟合',kept:'保留',rejected:'剔除 / 无有效拟合',noProfile:'本次没有有效采样区域，不能显示剖面。'}:{title:'Last preview profile',coverage:'Coverage',residual:'Max fit residual',intensity:'Mean intensity (0–1)',gradient:'Polarity-normalized mean gradient',note:'At most 1024 display points; detection uses every sample. Dashed lines show the scan-line threshold range.',lines:'scan lines',across:'Across px',left:'Left px',right:'Right px',fit:'Fit',kept:'Inlier',rejected:'Rejected / no valid fit',noProfile:'No valid sampling area in this observation.'})
const vector=(value:unknown):number[]=>Array.isArray(value)&&value.length<=1024&&value.every(v=>typeof v==='number'&&Number.isFinite(v))?value:[]
const distances=computed(()=>vector(props.diagnostic.distance_px))
const intensity=computed(()=>vector(props.diagnostic.intensity)), gradient=computed(()=>vector(props.diagnostic.gradient))
const available=computed(()=>distances.value.length>1&&intensity.value.length===distances.value.length&&gradient.value.length===distances.value.length&&distances.value.every((v,i)=>i===0||v>distances.value[i-1]!))
const extent=computed(()=>[distances.value[0]??0,distances.value.at(-1)??1])
const coverage=computed(()=>typeof props.diagnostic.coverage==='number'&&Number.isFinite(props.diagnostic.coverage)?`${(100*props.diagnostic.coverage).toFixed(1)}%`:'—')
const residual=computed(()=>typeof props.diagnostic.residual_px==='number'&&Number.isFinite(props.diagnostic.residual_px)?props.diagnostic.residual_px.toFixed(4):'—')
const charts=computed(()=>{
  if(!available.value)return []
  const threshold=typeof props.diagnostic.gradient_threshold==='number'&&Number.isFinite(props.diagnostic.gradient_threshold)?props.diagnostic.gradient_threshold:0
  const range=vector(props.diagnostic.gradient_threshold_range)
  const limits=[...new Set((range.length===2?range:[threshold]).flatMap(v=>[v,-v]))]
  return [{values:intensity.value,label:text.value.intensity,min:0,max:1,limits:[] as number[]},{values:gradient.value,label:text.value.gradient,min:Math.min(...gradient.value,...limits),max:Math.max(...gradient.value,...limits),limits}].map(chart=>{
    const span=chart.max-chart.min||1, y=(value:number)=>110-(value-chart.min)/span*100
    return {...chart,points:chart.values.map((v,i)=>`${32+(distances.value[i]!-extent.value[0]!)/(extent.value[1]!-extent.value[0]!)*592},${y(v)}`).join(' '),thresholds:chart.limits.map(y)}
  })
})
const pairs=computed(()=>{
  const list=(v:unknown)=>Array.isArray(v)?v.slice(0,65).map(vector).filter(a=>a.length===3):[]
  const inliers=list(props.diagnostic.inlier_pairs)
  return list(props.diagnostic.observed_pairs).map(values=>({values,inlier:inliers.some(p=>p.every((v,i)=>v===values[i]))}))
})
</script>
<style scoped>
.sampling-diagnostic{display:grid;gap:10px;padding:12px;border:1px solid var(--am-border);border-radius:var(--am-radius-sm);background:var(--am-surface);color:var(--am-text);font-size:12px}
p,figure{margin:0}p,figcaption{color:var(--am-text-muted)}svg{width:100%;max-height:160px}svg text{font-size:10px;fill:var(--am-text-muted)}.axis{stroke:var(--am-border);fill:none}.curve{stroke:var(--am-brand-primary);fill:none;stroke-width:1.7}.threshold{stroke:var(--am-text-muted);stroke-dasharray:4 4}
.sampling-pairs{max-height:170px;overflow:auto}table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}th,td{padding:5px;text-align:left;border-bottom:1px solid var(--am-border)}th{position:sticky;top:0;background:var(--am-surface)}
</style>
