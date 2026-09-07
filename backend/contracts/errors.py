"""公开错误响应规则。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, model_validator


class ErrorContract(BaseModel):
    """描述所有公开调用面共用的错误对象。

    字段：
    - code：稳定的机器错误码。
    - message：可直接显示的错误摘要。
    - details：错误码对应的结构化附加信息。
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    message: str
    details: dict[str, object]

    @model_validator(mode="after")
    def validate_contract(self) -> ErrorContract:
        """保证错误码和消息均为非空文本。"""

        if not self.code.strip():
            raise ValueError("code 不能为空")
        if not self.message.strip():
            raise ValueError("message 不能为空")
        return self
