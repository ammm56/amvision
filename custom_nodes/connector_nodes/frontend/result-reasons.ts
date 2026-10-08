/** 行业结果解释属于节点包，通用表格不根据 PIN ID 推断结果。 */
export const connectorResultReasons={
  pin_not_found:['未获得有效 PIN 位置','Valid PIN position unavailable'],
  multiple_edge_pairs:['存在多组候选边缘','Multiple edge-pair candidates'],
  expected_pin_missing:['预期 PIN 未检出','Expected PIN missing'],
  unexpected_pin:['设计空位存在物体','Object in designed empty position'],
} as const
