import { describe, it, expect } from 'vitest'
import { currentCalibration } from './calibration-preview'
import type { PreviewNodeDisplay } from '../preview/useWorkflowPreviewDisplays'
describe('calibration result ownership',()=>{
  const parameters={image_width:1280,image_height:800,model:'affine',unit:'millimeter',plane_id:'fixture',control_points:[{image:[10,20],world:[1,2]}],validation_points:[],max_validation_error:.02}
  const resource={plane_id:'fixture',validation_max_error:.001}
  const display={previewRunId:'run',payload:{parameter_snapshot:parameters,calibration_resource:resource}} as unknown as PreviewNodeDisplay
  it('requires the same successful run and exact parameter values, independent of key order',()=>{
    expect(currentCalibration(display,parameters,{runId:'run',succeeded:true})).toEqual(resource)
    expect(currentCalibration(display,{...parameters,max_validation_error:.019},{runId:'run',succeeded:true})).toBeNull()
    expect(currentCalibration(display,parameters,{runId:'next',succeeded:true})).toBeNull()
    expect(currentCalibration(display,parameters,{runId:'run',succeeded:false})).toBeNull()
    expect(currentCalibration({...display,stale:true},parameters,{runId:'run',succeeded:true})).toBeNull()
    expect(currentCalibration(display,parameters,undefined)).toBeNull()
    const {model:_,unit:__,...omitted}=parameters
    expect(currentCalibration(display,omitted,{runId:'run',succeeded:true})).toEqual(resource)
  })
})
