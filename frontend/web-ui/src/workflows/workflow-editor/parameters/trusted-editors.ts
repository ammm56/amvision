/** 随前端发行的显式注册表；manifest 不能注入任意浏览器代码。 */
import PinLayoutEditor from '../../../../../../custom_nodes/connector_nodes/frontend/PinLayoutEditor.vue'
import MeasurementEditor from '../../../../../../custom_nodes/connector_nodes/frontend/MeasurementEditor.vue'
import WorkflowCalibrationPointsEditor from '../components/WorkflowCalibrationPointsEditor.vue'
import type { Component } from 'vue'

const editors: Record<string, Component> = { 'custom.connector.pin-array-locate:layout': PinLayoutEditor, 'custom.connector.measure:items': MeasurementEditor,
  'custom.opencv.planar-calibrate:control_points':WorkflowCalibrationPointsEditor, 'custom.opencv.planar-calibrate:validation_points':WorkflowCalibrationPointsEditor }
export function trustedParameterEditor(nodeType: string, parameter: string): Component | undefined {
  return editors[`${nodeType}:${parameter}`]
}
