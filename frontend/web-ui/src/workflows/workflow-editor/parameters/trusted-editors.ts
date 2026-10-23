/** 随前端发行的显式注册表；manifest 不能注入任意浏览器代码。 */
import PinLayoutEditor from '../../../../../../custom_nodes/connector_nodes/frontend/PinLayoutEditor.vue'
import MeasurementEditor from '../../../../../../custom_nodes/connector_nodes/frontend/MeasurementEditor.vue'
import WorkflowCalibrationPointsEditor from '../components/WorkflowCalibrationPointsEditor.vue'
import WorkflowLimitRulesEditor from '../components/WorkflowLimitRulesEditor.vue'
import type { Component } from 'vue'
import RoiEditor from '../../../../../../custom_nodes/_metrology3d_nodes/frontend/RoiEditor.vue'
import GeometrySettingsEditor from '../../../../../../custom_nodes/_metrology3d_nodes/frontend/GeometrySettingsEditor.vue'

const editors: Record<string, Component> = { 'core.rule.check-limits:rules':WorkflowLimitRulesEditor, 'custom.connector.pin-array-locate:layout': PinLayoutEditor, 'custom.connector.measure:items': MeasurementEditor,
  'custom.opencv.planar-calibrate:control_points':WorkflowCalibrationPointsEditor, 'custom.opencv.planar-calibrate:validation_points':WorkflowCalibrationPointsEditor }
export function trustedParameterEditor(nodeType: string, parameter: string): Component | undefined {
  if(nodeType==='custom.metrology3d.crop-roi'&&parameter==='source')return RoiEditor
  if(['custom.metrology3d.fit-plane','custom.metrology3d.build-frame'].includes(nodeType)&&parameter==='settings')return GeometrySettingsEditor
  return editors[`${nodeType}:${parameter}`]
}
