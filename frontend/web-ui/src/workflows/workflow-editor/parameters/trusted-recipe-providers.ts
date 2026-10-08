/** 与可信编辑器同属发行组合入口；不运行 manifest 中的任意浏览器代码。 */
import { connectorNumericItems } from '../../../../../../custom_nodes/connector_nodes/frontend/numeric-items'
import { connectorRecipeValidator } from '../../../../../../custom_nodes/connector_nodes/frontend/recipe-validation'
import type { NumericItemProviders } from './static-numeric-items'
import type { RecipeValidator } from './recipe-validation'

export const trustedNumericItemProviders:NumericItemProviders={
  'custom.connector.measure':connectorNumericItems,
  'custom.connector.pin-array-locate':connectorNumericItems,
}
export const trustedRecipeValidators:Readonly<Record<string,RecipeValidator>>={
  'custom.connector.measure':connectorRecipeValidator,
  'custom.connector.pin-array-locate':connectorRecipeValidator,
}
