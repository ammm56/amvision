import type { WidgetEventOptions } from "./BaseWidget"
import type { INumericWidget } from "@litegraph/types/widgets"

import { getWidgetStep } from "@litegraph/utils/widget"

import { BaseSteppedWidget } from "./BaseSteppedWidget"

function evaluateNumericExpression(expression: string): number | null {
  if (!/^[\d\s()+\-*\/.]+$/.test(expression)) return null

  let index = 0
  const skipSpaces = () => {
    while (/\s/.test(expression[index] ?? "")) index += 1
  }
  const parseNumber = (): number | null => {
    skipSpaces()
    const start = index
    while (/[\d.]/.test(expression[index] ?? "")) index += 1
    if (start === index) return null
    const value = Number(expression.slice(start, index))
    return Number.isFinite(value) ? value : null
  }
  const parseFactor = (): number | null => {
    skipSpaces()
    if (expression[index] === "+" || expression[index] === "-") {
      const sign = expression[index] === "-" ? -1 : 1
      index += 1
      const value = parseFactor()
      return value === null ? null : sign * value
    }
    if (expression[index] === "(") {
      index += 1
      const value = parseExpression()
      skipSpaces()
      if (expression[index] !== ")") return null
      index += 1
      return value
    }
    return parseNumber()
  }
  const parseTerm = (): number | null => {
    let value = parseFactor()
    if (value === null) return null
    while (true) {
      skipSpaces()
      const operator = expression[index]
      if (operator !== "*" && operator !== "/") return value
      index += 1
      const rightValue = parseFactor()
      if (rightValue === null) return null
      value = operator === "*" ? value * rightValue : value / rightValue
    }
  }
  function parseExpression(): number | null {
    let value = parseTerm()
    if (value === null) return null
    while (true) {
      skipSpaces()
      const operator = expression[index]
      if (operator !== "+" && operator !== "-") return value
      index += 1
      const rightValue = parseTerm()
      if (rightValue === null) return null
      value = operator === "+" ? value + rightValue : value - rightValue
    }
  }

  const result = parseExpression()
  skipSpaces()
  return result !== null && index === expression.length && Number.isFinite(result) ? result : null
}

export class NumberWidget extends BaseSteppedWidget<INumericWidget> implements INumericWidget {
  override type = "number" as const

  override get _displayValue() {
    if (this.computedDisabled) return ""
    return Number(this.value).toFixed(
      this.options.precision !== undefined
        ? this.options.precision
        : 3,
    )
  }

  override canIncrement(): boolean {
    const { max } = this.options
    return max == null || this.value < max
  }

  override canDecrement(): boolean {
    const { min } = this.options
    return min == null || this.value > min
  }

  override incrementValue(options: WidgetEventOptions): void {
    this.setValue(this.value + getWidgetStep(this.options), options)
  }

  override decrementValue(options: WidgetEventOptions): void {
    this.setValue(this.value - getWidgetStep(this.options), options)
  }

  override setValue(value: number, options: WidgetEventOptions) {
    let newValue = value
    if (this.options.min != null && newValue < this.options.min) {
      newValue = this.options.min
    }
    if (this.options.max != null && newValue > this.options.max) {
      newValue = this.options.max
    }
    super.setValue(newValue, options)
  }

  override onClick({ e, node, canvas }: WidgetEventOptions) {
    const x = e.canvasX - node.pos[0]
    const width = this.width || node.size[0]

    // 判断是否点中左右步进区域
    const delta = x < 40
      ? -1
      : (x > width - 40
        ? 1
        : 0)

    if (delta) {
      // 处理左右步进点击
      this.setValue(this.value + delta * getWidgetStep(this.options), { e, node, canvas })
      return
    }

    // 处理中间区域点击并弹出输入框
    canvas.prompt("Value", this.value, (v: string) => {
      const evaluatedValue = evaluateNumericExpression(v)
      const newValue = evaluatedValue ?? Number(v)
      if (!isNaN(newValue)) {
        this.setValue(newValue, { e, node, canvas })
      }
    }, e)
  }

  /**
  * 处理 number widget 的拖动事件
  * @param options 拖动事件处理参数
   */
  override onDrag({ e, node, canvas }: WidgetEventOptions) {
    const width = this.width || node.width
    const x = e.canvasX - node.pos[0]
    const delta = x < 40
      ? -1
      : (x > width - 40
        ? 1
        : 0)

    if (delta && (x > -3 && x < width + 3)) return
    this.setValue(this.value + (e.deltaX ?? 0) * getWidgetStep(this.options), { e, node, canvas })
  }
}
