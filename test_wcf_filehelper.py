# -*- coding: utf-8 -*-
"""
已重构迁移通知：
此测试脚本已升级并迁移至 smoketest/ 文件夹：
    smoketest/wcf_smoke_test.py
请优先运行：
    python smoketest/wcf_smoke_test.py
"""
import subprocess
import sys
import os

if __name__ == "__main__":
    smoke_script = os.path.join(os.path.dirname(__file__), "smoketest", "wcf_smoke_test.py")
    ret = subprocess.run([sys.executable, smoke_script] + sys.argv[1:]).returncode
    sys.exit(ret)
