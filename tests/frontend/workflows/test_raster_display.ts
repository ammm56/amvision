import { expect, it } from 'vitest'
import { rasterIdentity, sourcePixel } from '@/workflows/workflow-editor/point-cloud/raster-display'

it('preserves zero-based pixel identity across filtered source rows', () => {
  const grid = rasterIdentity({width:4,height:3,calibration_id:'camera',calibration_revision:'r1'},12)
  expect(sourcePixel('11',grid)).toEqual({row:2,column:3})
  expect(sourcePixel('2',grid)).toEqual({row:0,column:2})
  expect(sourcePixel(null,grid)).toBeNull()
  expect(sourcePixel('12',grid)).toBeNull()
  expect(() => rasterIdentity({width:4,height:2,calibration_id:'camera',calibration_revision:'r1'},12)).toThrow()
})
