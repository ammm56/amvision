"""将有限、无递归的参数 Schema 展开为既有表单可用结构。"""

from copy import deepcopy


def inline_model_schema(model) -> dict:
    """展开本地 $defs 引用；禁止递归模型，避免表单无限展开。"""
    schema = model.model_json_schema()
    definitions = schema.pop("$defs", {})

    def inline(value, active=()):
        """逐层展开数组和对象，保留 JSON Schema 的校验关键字。"""
        if isinstance(value, list):
            return [inline(v, active) for v in value]
        if isinstance(value, dict):
            if "$ref" in value:
                reference = value["$ref"]
                if not reference.startswith("#/$defs/") or reference in active:
                    raise ValueError("参数模型只支持无递归的本地 Schema 引用")
                return inline(
                    deepcopy(definitions[reference.split("/")[-1]])
                    | {k: v for k, v in value.items() if k != "$ref"},
                    (*active, reference),
                )
            return {k: inline(v, active) for k, v in value.items()}
        return value

    return inline(schema)
