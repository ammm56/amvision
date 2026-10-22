"""文件编码的累计大小、取消与短写检查。"""

from backend.service.application.errors import InvalidRequestError


class BoundedBinaryOutput:
    """借用输出流；仅有调用者确认完成后才能交付文件。"""

    def __init__(self, stream, limit, cancel):
        """limit 为显式容量，不承担打开文件和关闭文件责任。"""
        if type(limit) is not int or limit <= 0:
            raise ValueError("输出限额必须是显式正整数")
        self.stream, self.limit, self.cancel, self.count = stream, limit, cancel, 0

    def tell(self):
        """累计实际字节数，不声明支持随机写入。"""
        return self.count

    def write(self, data):
        """写前检查预算，拒绝短写；不将部分结果当成功。"""
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise TypeError("输出流要求二进制数据")
        self.cancel()
        size = data.nbytes if isinstance(data, memoryview) else len(data)
        if self.count + size > self.limit:
            raise InvalidRequestError("文件输出超过显式大小限额")
        written = self.stream.write(data)
        if written != size:
            raise OSError("文件输出短写")
        self.count += written
        return written

    def flush(self):
        """刷新调用者流，不伪造持久提交完成。"""
        self.stream.flush()
