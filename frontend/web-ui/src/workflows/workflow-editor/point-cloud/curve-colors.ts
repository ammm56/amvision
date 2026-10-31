/** 只着色服务端逐点证据，不从显示点重新计算权重或拟合残差。 */
import type {CurveDisplay} from './boundary-display'
export type CurveColorMode='support'|'weight'|'residual'
export function curveColorValues(curve:CurveDisplay,mode:CurveColorMode){return mode==='weight'?curve.fit_weights:mode==='residual'?curve.radial_residuals:undefined}
export function curveColorScale(curve:CurveDisplay,mode:CurveColorMode){
  const values=curveColorValues(curve,mode)
  if(!values?.length)return null
  let min=Infinity,max=-Infinity
  for(const value of values){min=Math.min(min,value);max=Math.max(max,value)}
  if(mode==='residual'){max=Math.max(Math.abs(min),Math.abs(max));min=-max}
  return {min,max}
}
export function curveColor(value:number,min:number,max:number):[number,number,number]{
  const t=max===min?0.5:Math.max(0,Math.min(1,(value-min)/(max-min)))
  return t<.5?[2*t,2*t,1]:[1,2*(1-t),2*(1-t)]
}
