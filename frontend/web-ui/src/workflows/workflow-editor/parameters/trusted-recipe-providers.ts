/** 与可信编辑器同属发行组合入口；不运行 manifest 中的任意浏览器代码。 */
import { connectorNumericItems } from '../../../../../../custom_nodes/connector_nodes/frontend/numeric-items'
import { connectorRecipeValidator } from '../../../../../../custom_nodes/connector_nodes/frontend/recipe-validation'
import type { NumericItemProviders } from './static-numeric-items'
import type { RecipeValidator } from './recipe-validation'
import {geometryRecipeValidator} from '../../../../../../custom_nodes/_metrology3d_nodes/frontend/recipe-validation'
import {measurementNumericItems,measurementRecipeValidator} from '../../../../../../custom_nodes/_metrology3d_nodes/frontend/measurement-form'
import {boundaryRecipeValidator} from '../../../../../../custom_nodes/_metrology3d_nodes/frontend/boundary-form'

export const trustedNumericItemProviders:NumericItemProviders={
  'custom.metrology3d.height-query':measurementNumericItems,
  'custom.metrology3d.measure-step':measurementNumericItems,
  'custom.connector.measure':connectorNumericItems,
  'custom.connector.pin-array-locate':connectorNumericItems,
}
export const trustedRecipeValidators:Readonly<Record<string,RecipeValidator>>={
  'custom.metrology3d.extract-boundary':boundaryRecipeValidator,
  'custom.metrology3d.fit-line':boundaryRecipeValidator,
  'custom.metrology3d.fit-circle':boundaryRecipeValidator,
  'custom.metrology3d.height-query':measurementRecipeValidator,
  'custom.metrology3d.measure-step':measurementRecipeValidator,
  'custom.metrology3d.crop-roi':geometryRecipeValidator,
  'custom.metrology3d.fit-plane':geometryRecipeValidator,
  'custom.metrology3d.build-frame':geometryRecipeValidator,
  'custom.connector.measure':connectorRecipeValidator,
  'custom.connector.pin-array-locate':connectorRecipeValidator,
}
