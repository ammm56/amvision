/** PIN 配置的编辑模型：名义身份由配置定义，不由本次检测排序。 */
export interface EndpointPair { first_id: string; second_id: string; sampling_type: string; center_offset: [number, number] }
export interface CandidateBand { band_id: string; center: [number, number]; length: number; sampling_type: string }
export interface PinDefinition { pin_id: string; row_id: string; pin_type: string; center: [number, number]; expected_present: boolean; endpoint_pairs?: EndpointPair[] }
export interface SamplingType {
  type_id: string; search_length: number; band_width: number; scan_lines: number; sample_step: number;
  angle_degrees: number; polarity: 'bright' | 'dark'; gradient_threshold: number; relative_gradient_threshold: number; min_width: number; max_width: number; min_coverage: number; max_residual: number
}
export interface PinLayout { reference_id: string; reference_sha256: string | null; pins: PinDefinition[]; types: SamplingType[]; candidate_bands?: CandidateBand[]; diagnostic_pin_id?: string | null }
export function createPinLayout(): PinLayout {
  return { reference_id: 'reference', reference_sha256: null, pins: [], types: [{ type_id: 'normal', search_length: 48, band_width: 8, scan_lines: 9, sample_step: .5, angle_degrees: 0, polarity: 'bright', gradient_threshold: .03, relative_gradient_threshold: 0, min_width: 2, max_width: 40, min_coverage: .7, max_residual: 1 }] }
}
/** 补齐当前 Schema 允许省略的默认参数，不修改导入文档或接受旧字段。 */
export function hydratePinLayout(value: PinLayout): PinLayout {
  const defaults=createPinLayout().types[0]!
  return {...value,reference_sha256:value.reference_sha256??null,diagnostic_pin_id:value.diagnostic_pin_id??null,
    types:value.types.map(type=>({...defaults,...type})),
    pins:value.pins.map(pin=>({...pin,center:[...pin.center] as [number,number],expected_present:pin.expected_present===undefined?true:pin.expected_present,
      endpoint_pairs:(pin.endpoint_pairs??[]).map(pair=>({...pair,center_offset:[...(pair.center_offset??[0,0])] as [number,number]}))})),
    candidate_bands:(value.candidate_bands??[]).map(band=>({...band,center:[...band.center] as [number,number]}))}
}
export function generatePins(rows: number, columns: number, origin: [number, number], pitch: number, rowPitch: number, stagger: number, typeId: string): PinDefinition[] {
  if (!Number.isInteger(rows) || !Number.isInteger(columns) || rows < 1 || columns < 1 || rows * columns > 1024 || ![...origin, pitch, rowPitch, stagger].every(Number.isFinite) || pitch <= 0 || (rows > 1 && rowPitch <= 0)) throw new Error('Invalid array dimensions')
  return Array.from({ length: rows * columns }, (_, index) => {
    const row = Math.floor(index / columns), column = index % columns
    return { pin_id: `R${row + 1}P${String(column + 1).padStart(2, '0')}`, row_id: `R${row + 1}`, pin_type: typeId, center: [origin[0] + column * pitch + (row % 2) * stagger, origin[1] + row * rowPitch], expected_present: true }
  })
}
export interface PinArraySettings { rows:number; columns:number; x:number; y:number; pitch:number; rowPitch:number; stagger:number }

/** 仅反推标准编号、等间距阵列；不将不规则布局悄悄吸附到规则网格。 */
export function inferPinArray(pins: PinDefinition[]): PinArraySettings | null {
  if (!pins.length) return null
  const rows = [...new Set(pins.map(p => p.row_id))]
  const first = pins.filter(p => p.row_id === 'R1').sort((a,b) => a.center[0]-b.center[0])
  if (first.length < 2 || pins.length !== rows.length * first.length) return null
  const x=first[0]!.center[0], y=first[0]!.center[1], pitch=(first.at(-1)!.center[0]-x)/(first.length-1)
  const second=pins.find(p=>p.pin_id==='R2P01')
  const rowPitch=second ? second.center[1]-y : 50, stagger=second ? second.center[0]-x : 0
  try {
    const generated=generatePins(rows.length,first.length,[x,y],pitch,rowPitch,stagger,first[0]!.pin_type)
    const actual=new Map(pins.map(p=>[p.pin_id,p]))
    if (generated.some(p => { const a=actual.get(p.pin_id); return !a || a.row_id!==p.row_id || Math.hypot(a.center[0]-p.center[0],a.center[1]-p.center[1])>1e-3 })) return null
    return {rows:rows.length,columns:first.length,x,y,pitch,rowPitch,stagger}
  } catch { return null }
}

/** 同一稳定 ID 的业务属性保留，只有显式生成的中心/行位置发生变化。 */
export function replacePinArray(previous: PinDefinition[], generated: PinDefinition[]): PinDefinition[] {
  const old=new Map(previous.map(pin=>[pin.pin_id,pin]))
  return generated.map(pin=>{
    const retained=old.get(pin.pin_id)
    return retained ? {...JSON.parse(JSON.stringify(retained)),center:pin.center,row_id:pin.row_id} : pin
  })
}
export function isPinLayoutValid(layout: PinLayout): boolean {
  if (!layout || !Array.isArray(layout.pins) || !Array.isArray(layout.types)) return false
  if (layout.pins.some(p => !p || typeof p !== 'object') || layout.types.some(t => !t || typeof t !== 'object')) return false
  const id = /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/
  if (!id.test(layout.reference_id) || (layout.reference_sha256 !== null && !/^[a-f0-9]{64}$/.test(layout.reference_sha256)) || !layout.pins.length || layout.pins.length > 1024 || !layout.types.length || layout.types.length > 64) return false
  const types = new Map(layout.types.map(t => [t.type_id, t]))
  if (types.size !== layout.types.length || new Set(layout.pins.map(p => p.pin_id)).size !== layout.pins.length) return false
  if (layout.diagnostic_pin_id != null && !layout.pins.some(p => p.pin_id === layout.diagnostic_pin_id)) return false
  let samples = 0
  for (const t of layout.types) {
    if (!id.test(t.type_id) || ![t.search_length,t.band_width,t.scan_lines,t.sample_step,t.angle_degrees,t.gradient_threshold,t.relative_gradient_threshold,t.min_width,t.max_width,t.min_coverage,t.max_residual].every(Number.isFinite)) return false
    if (t.search_length < 4 || t.search_length > 2048 || t.band_width < 1 || t.band_width > 256 || !Number.isInteger(t.scan_lines) || t.scan_lines < 3 || t.scan_lines > 65 || t.sample_step < .25 || t.sample_step > 2 || t.gradient_threshold <= 0 || t.gradient_threshold > 1 || t.relative_gradient_threshold < 0 || t.relative_gradient_threshold > 1 || t.min_width <= 0 || t.max_width < t.min_width || t.max_width >= t.search_length || t.min_coverage <= 0 || t.min_coverage > 1 || t.max_residual <= 0 || t.max_residual > 10 || !['bright','dark'].includes(t.polarity)) return false
  }
  for (const p of layout.pins) {
    if (!p || !Array.isArray(p.center)) return false
    const t = types.get(p.pin_type)
    if (!id.test(p.pin_id) || `presence:${p.pin_id}`.length > 128 || !id.test(p.row_id) || !t || p.center.length !== 2 || !p.center.every(Number.isFinite) || typeof p.expected_present !== 'boolean') return false
    samples += (Math.floor(t.search_length / t.sample_step) + 2) * t.scan_lines
    if (p.endpoint_pairs && (!Array.isArray(p.endpoint_pairs) || p.endpoint_pairs.length > 2)) return false
    const names = ['left','right','center']
    for (const pair of p.endpoint_pairs ?? []) {
      if (!pair || typeof pair !== 'object') return false
      const scan = types.get(pair.sampling_type)
      if (!scan || !id.test(pair.first_id) || !id.test(pair.second_id) || !Array.isArray(pair.center_offset) || pair.center_offset.length !== 2 || !pair.center_offset.every(Number.isFinite)) return false
      names.push(pair.first_id,pair.second_id)
      samples += (Math.floor(scan.search_length / scan.sample_step) + 2) * scan.scan_lines
    }
    if (new Set(names).size !== names.length || names.some(n => `${p.pin_id}:${n}`.length > 128)) return false
  }
  const bands = layout.candidate_bands ?? []
  if (!Array.isArray(bands) || bands.length > 64 || bands.some(b => !b || typeof b !== 'object') || new Set(bands.map(b => b.band_id)).size !== bands.length) return false
  for (const b of bands) {
    const scan = types.get(b.sampling_type)
    if (!id.test(b.band_id) || `extra:${b.band_id}`.length > 128 || !scan || !Array.isArray(b.center) || b.center.length !== 2 || !b.center.every(Number.isFinite) || !Number.isFinite(b.length) || b.length < scan.search_length || b.length > 8190) return false
    samples += (Math.floor(b.length / scan.sample_step) + 2) * scan.scan_lines
  }
  if (layout.pins.reduce((n,p) => n + 3 + 2*(p.endpoint_pairs?.length ?? 0),0) > 6144) return false
  return samples <= 4_000_000
}

/** 比较完整采样草稿，补齐省略的可选字段；旧预览不能冒充新配置的结果。 */
export function samePinLayout(a: unknown, b: PinLayout): boolean {
  const normalize = (value: unknown): unknown => {
    const layout = value as PinLayout | undefined
    if (!layout || !Array.isArray(layout.pins)) return null
    try { return hydratePinLayout(layout) } catch { return null }
  }
  const canonical = (value: unknown): unknown => Array.isArray(value) ? value.map(canonical) : value && typeof value === 'object' ? Object.fromEntries(Object.entries(value).sort(([a],[b])=>a.localeCompare(b)).map(([k,v])=>[k,canonical(v)])) : value
  return JSON.stringify(canonical(normalize(a))) === JSON.stringify(canonical(normalize(b)))
}
