"""真实子进程验证已加载 BLAS 的线程策略，不修改测试主进程或系统环境。"""

import json
import subprocess
import sys

import pytest


@pytest.mark.parametrize("count", [1, 2])
def test_loaded_numpy_and_scipy_follow_workflow_thread_configuration(count):
    """导入次序与 spawn 一致；配置不能仅改变环境变量。"""
    code = """
import json, os, sys
import numpy as np
import scipy.linalg
from threadpoolctl import threadpool_info
from backend.service.application.workflows.process_threads import configure_workflow_process_threads
a = np.arange(3000, dtype=float).reshape(-1, 3)
b = np.array([[1., 0.], [0., 1.], [1., -1.]])
expected = a @ b
count = int(sys.argv[1])
before = threadpool_info()
configure_workflow_process_threads(count)
np.testing.assert_array_equal(a @ b, expected)
after = [p for p in threadpool_info() if p['user_api'] == 'blas']
assert len(after) >= 2, after
assert all(p['num_threads'] == count for p in after), after
assert os.environ['OPENBLAS_NUM_THREADS'] == str(count)
import cv2
assert cv2.getNumThreads() == count
print(json.dumps({'before': before, 'after': after}))
"""
    result = subprocess.run(
        [sys.executable, "-c", code, str(count)],
        capture_output=True,
        text=True,
        check=True,
        timeout=45,
    )
    assert json.loads(result.stdout)["after"]
