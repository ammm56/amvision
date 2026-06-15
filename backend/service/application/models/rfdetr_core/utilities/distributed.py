"""RF-DETR core 工具函数模块：`utilities.distributed`。"""

import pickle
from typing import Any

import torch
import torch.distributed as dist


def is_dist_avail_and_initialized() -> bool:
    """执行 `is_dist_avail_and_initialized`。
    
    返回：
    - 当前函数的执行结果。
    """
    if not dist.is_available():
        return False
    if not dist.is_initialized():
        return False
    return True


def get_world_size() -> int:
    """执行 `get_world_size`。
    
    返回：
    - 当前函数的执行结果。
    """
    if not is_dist_avail_and_initialized():
        return 1
    return dist.get_world_size()


def get_rank() -> int:
    """执行 `get_rank`。
    
    返回：
    - 当前函数的执行结果。
    """
    if not is_dist_avail_and_initialized():
        return 0
    return dist.get_rank()


def is_main_process() -> bool:
    """执行 `is_main_process`。
    
    返回：
    - 当前函数的执行结果。
    """
    return get_rank() == 0


def save_on_master(obj: Any, f: Any, *args: Any, **kwargs: Any) -> None:
    """执行 `save_on_master`。
    
    参数：
    - `obj`：传入的 `obj` 参数。
    - `f`：传入的 `f` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    if is_main_process():
        torch.save(obj, f, *args, **kwargs)


def all_gather(data: Any) -> list[Any]:
    """执行 `all_gather`。
    
    参数：
    - `data`：传入的 `data` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    world_size = get_world_size()
    if world_size == 1:
        return [data]

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    buffer = pickle.dumps(data)
    tensor = torch.tensor(bytearray(buffer), dtype=torch.uint8, device=device)

    local_size = tensor.numel()
    local_size_tensor = torch.tensor([local_size], device=device)
    size_list = [torch.tensor([0], device=device) for _ in range(world_size)]
    dist.all_gather(size_list, local_size_tensor)
    size_list = [int(size.item()) for size in size_list]
    max_size = max(size_list)

    tensor_list = []
    for _ in size_list:
        tensor_list.append(torch.empty((max_size,), dtype=torch.uint8, device=device))
    if local_size != max_size:
        padding = torch.empty(size=(max_size - local_size,), dtype=torch.uint8, device=device)
        tensor = torch.cat((tensor, padding), dim=0)
    dist.all_gather(tensor_list, tensor)

    data_list = []
    for size, tensor in zip(size_list, tensor_list):
        buffer = tensor.cpu().numpy().tobytes()[:size]
        data_list.append(pickle.loads(buffer))

    return data_list


def reduce_dict(input_dict: dict[str, torch.Tensor], average: bool = True) -> dict[str, torch.Tensor]:
    """执行 `reduce_dict`。
    
    参数：
    - `input_dict`：传入的 `input_dict` 参数。
    - `average`：传入的 `average` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    world_size = get_world_size()
    if world_size < 2:
        return input_dict
    with torch.no_grad():
        names = []
        values = []
        for k in sorted(input_dict.keys()):
            names.append(k)
            values.append(input_dict[k])
        values = torch.stack(values, dim=0)
        dist.all_reduce(values)
        if average:
            values /= world_size
        reduced_dict = {k: v for k, v in zip(names, values)}
    return reduced_dict


