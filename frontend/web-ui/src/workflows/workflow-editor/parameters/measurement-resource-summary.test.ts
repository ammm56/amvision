import { describe, expect, it } from 'vitest'
import { calibrationSummary, calibrationSummaryMessages } from './measurement-resource-summary'

const t = (key: string, values?: Record<string, string | number>) => {
  const message = calibrationSummaryMessages['zh-CN'][key as keyof typeof calibrationSummaryMessages['zh-CN']]
  return values ? message.replace('{count}', String(values.count)) : message
}
const calibration = { image_width:1280, image_height:800, plane_id:'test', unit:'millimeter', valid_polygon:[[0,0],[100,0],[0,100]], fit_rms:0, validation_max_error:0 }
describe('calibration evidence summary', () => {
  it('does not present a synthetic zero as independent validation', () => {
    const rows = calibrationSummary(calibration, t)
    expect(rows.at(-1)).toEqual(['独立验证最大误差', '未提供独立验证数据'])
    expect(rows.at(-2)).toEqual(['拟合 RMS', '未提供拟合点数据'])
    expect(calibration.validation_max_error).toBe(0)
  })
  it('reports counts and units for present evidence, including a genuine zero', () => {
    const value = {...calibration, evidence:{control_points:[1,2,3],validation_points:[1,2]}}
    expect(calibrationSummary(value,t).at(-1)?.[1]).toBe('0 mm · 2 个点')
    expect(calibrationSummary({...value,unit:'meter',validation_max_error:0.0012},t).at(-1)?.[1]).toBe('0.0012 m · 2 个点')
  })
  it('does not treat an empty or incomplete point set as verified', () => {
    for(const validation_points of [[],[1],null]) {
      expect(calibrationSummary({...calibration,evidence:{validation_points}},t).at(-1)?.[1]).toBe('未提供独立验证数据')
    }
  })
})
