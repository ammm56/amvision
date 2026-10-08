import type { PinLayout } from './pin-layout'

export interface MeasurementItem { item_id:string;kind:string;enabled:boolean;pin_a:string;pin_b:string|null;direction:[number,number];section:number|null;distance_mode:string;feature_a:string|null;feature_b:string|null }
export const batchKinds=['width','offset','pitch','gap','total_pitch'] as const

/** 批量配置仅使用名义布局，不从上一次成功观测推导应测对象。 */
export function buildMeasurementBatch(layout:PinLayout, selectedIds:string[], kinds:string[]):MeasurementItem[] {
  const selected=new Set(selectedIds), result:MeasurementItem[]=[]
  const add=(kind:string,a:string,b:string|null,section:number|null,id:string)=>result.push({item_id:id,kind,enabled:true,pin_a:a,pin_b:b,direction:[1,0],section,distance_mode:'projected',feature_a:null,feature_b:null})
  for(const row of new Set(layout.pins.map(pin=>pin.row_id))){
    const pins=layout.pins.filter(pin=>pin.row_id===row).sort((a,b)=>a.center[0]-b.center[0]||a.center[1]-b.center[1])
    const wanted=(id:string)=>selected.has(id)&&pins.find(p=>p.pin_id===id)?.expected_present
    for(const p of pins)if(wanted(p.pin_id))for(const kind of ['width','offset'])if(kinds.includes(kind))add(kind,p.pin_id,null,kind==='width'?p.center[1]:null,`${kind}:${p.pin_id}`)
    // 相邻由完整名义排列决定；设计空位不会导致跨空位的配对或编号移动。
    for(let i=1;i<pins.length;i++){
      const a=pins[i-1]!,b=pins[i]!
      if(wanted(a.pin_id)&&wanted(b.pin_id))for(const kind of ['pitch','gap'])if(kinds.includes(kind))add(kind,a.pin_id,b.pin_id,kind==='gap'?(a.center[1]+b.center[1])/2:null,`${kind}:${a.pin_id}:${b.pin_id}`)
    }
    const endPins=pins.filter(p=>wanted(p.pin_id))
    if(kinds.includes('total_pitch')&&endPins.length>1)add('total_pitch',endPins[0]!.pin_id,endPins.at(-1)!.pin_id,null,`total:${row}`)
  }
  return result
}

export function endpointIds(layout:PinLayout,pinId:string):string[] {
  const pin=layout.pins.find(p=>p.pin_id===pinId)
  if(!pin?.expected_present)return []
  return (pin.endpoint_pairs??[]).flatMap(pair=>[`${pinId}:${pair.first_id}`,`${pinId}:${pair.second_id}`])
}

/** 返回失效的名义引用；不为缺失引用构造默认测量对象。 */
export function invalidMeasurementReferences(items:MeasurementItem[],layout:PinLayout):string[] {
  const ids=new Set(layout.pins.map(pin=>pin.pin_id))
  return items.filter(item=>!ids.has(item.pin_a)||(item.pin_b!=null&&!ids.has(item.pin_b))||
    (item.kind==='length'&&(!endpointIds(layout,item.pin_a).includes(item.feature_a??'')||!endpointIds(layout,item.pin_b??'').includes(item.feature_b??''))))
    .map(item=>item.item_id)
}
