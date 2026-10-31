import {Color,SRGBColorSpace} from 'three'

/** 显示色标和比例尺；不参与测量、过滤或持久化配方。 */
export type CoordinateRange = { min: number; max: number }
export type CloudColorMode = 'original' | 'coordinate-z' | 'support' | 'residual'

export function coordinateRange(payload: Record<string, unknown>): CoordinateRange | null {
  const bounds = payload.bounds as { min?: unknown[]; max?: unknown[] } | undefined
  const min = bounds?.min?.[2], max = bounds?.max?.[2]
  return typeof min === 'number' && typeof max === 'number' && Number.isFinite(min) && Number.isFinite(max) && min <= max ? { min, max } : null
}

/** 蓝、青、绿、黄、红连续映射，端外饱和而非删除点。 */
export function coordinateColor(value: number, range: CoordinateRange): [number, number, number] {
  const t = range.min === range.max ? .5 : Math.max(0, Math.min(1, (value - range.min) / (range.max - range.min)))
  return [Math.max(0, Math.min(1, 4 * t - 2)), Math.max(0, Math.min(1, 4 * t, 4 - 4 * t)), Math.max(0, Math.min(1, 2 - 4 * t))]
}

export function fillCoordinateColors(target: Float32Array, positions: Float32Array, originZ: number, range: CoordinateRange) {
  if (![originZ, range.min, range.max].every(Number.isFinite) || range.min > range.max || target.length !== positions.length) throw new Error('cloud_preview_invalid')
  for (let i = 2; i < positions.length; i += 3) target.set(coordinateColor(positions[i]! + originZ, range), i - 2)
}

/** UI 色标与源 RGB 使用 sRGB；Three.js 顶点属性使用线性色，避免二次增亮。 */
export function linearizeDisplayColors(colors:Float32Array){
  const color=new Color()
  for(let i=0;i<colors.length;i+=3){color.setRGB(colors[i]!,colors[i+1]!,colors[i+2]!,SRGBColorSpace);colors[i]=color.r;colors[i+1]=color.g;colors[i+2]=color.b}
}

/** 正交视图按实际像素跨度生成 1/2/5 刻度，透视视图不显示虚假的统一比例。 */
export function scaleBar(worldWidth: number, pixels: number): { value: number; pixels: number } | null {
  if (!Number.isFinite(worldWidth) || worldWidth <= 0 || !Number.isFinite(pixels) || pixels < 80) return null
  const limit = worldWidth * Math.min(120, pixels * .22) / pixels
  const power = 10 ** Math.floor(Math.log10(limit))
  const step = [5, 2, 1].find(value => value * power <= limit) ?? 1
  const value = step * power
  return { value, pixels: value / worldWidth * pixels }
}

export function displayNumber(value: number): string {
  if (value === 0) return '0'
  return Number(value.toPrecision(6)).toString()
}
