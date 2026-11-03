"""只在验收侧记录建面逐行耗时，并保存同输入等价对照所需的局部数组。"""

from collections import defaultdict
import linecache
from pathlib import Path
import sys
from time import perf_counter

import numpy as np

from custom_nodes.metrology3d_nodes.shared import envelope_grid, extract_boundary


def capture_surface_compute(monkeypatch, report, directory):
    """同次捕获两半圆和十二包络；逐行成本不能冒充未插桩节拍。"""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    counts_by_kind = defaultdict(int)

    def measured(original, kind, *args, **kwargs):
        """只跟踪被测帧，原生调用计入调用行；输入写盘发生在计时之后。"""
        code = original.__code__
        timings, counts = defaultdict(float), defaultdict(int)
        previous_line, previous_time = None, None

        def trace(frame, event, arg):
            nonlocal previous_line, previous_time
            if frame.f_code is not code:
                return None
            now = perf_counter()
            if previous_line is not None:
                timings[previous_line] += now - previous_time
            previous_line, previous_time = frame.f_lineno, now
            counts[frame.f_lineno] += 1
            return trace

        old_trace = sys.gettrace()
        started = perf_counter()
        try:
            sys.settrace(trace)
            result = original(*args, **kwargs)
        finally:
            sys.settrace(old_trace)
        elapsed = perf_counter() - started
        index = counts_by_kind[kind]
        counts_by_kind[kind] += 1
        # 保存发生在建面计时之后，但仍处于节点内；整图必须标记为插桩。
        values = {
            key: value
            for key, value in kwargs.items()
            if key not in {"cancel", "capture"}
        }
        values["positions"] = args[0]
        if kind == "surface":
            values.update(
                faces=result.faces,
                boundary_edges=result.boundary_edges,
                candidate_face_count=result.candidate_face_count,
            )
            reason = result.reason
        elif kind == "section":
            values["faces"] = args[1]
            for key in (
                "positions",
                "edges",
                "source_vertices",
                "weights",
                "face_offsets",
                "face_indices",
            ):
                values["result_" + key] = getattr(result, key)
            reason = result.reason
        else:
            values["settings"] = args[1].model_dump_json()
            values["selected"] = result[1]
            values["component_count"] = result[3]
            if result[2] is not None:
                values["rows"], values["labels"], values["target"] = result[2]
            reason = result[0]
        np.savez(directory / f"{kind}-{index}.npz", **values)
        report.append(
            dict(
                kind=kind,
                index=index,
                points=len(args[0]),
                elapsed_seconds=elapsed,
                reason=reason,
                lines=[
                    dict(
                        line=number,
                        code=linecache.getline(code.co_filename, number).strip(),
                        seconds=timings[number],
                        events=counts[number],
                    )
                    for number in sorted(timings)
                ],
            )
        )
        return result

    for module, name, kind in (
        (extract_boundary, "build_surface", "surface"),
        (extract_boundary, "intersect_surface", "section"),
        (envelope_grid, "metric_membership", "metric"),
    ):
        original = getattr(module, name)

        def capture(*args, _original=original, _kind=kind, **kwargs):
            return measured(_original, _kind, *args, **kwargs)

        monkeypatch.setattr(module, name, capture)
