"""测试夹具与公共工具。"""
import sys
from pathlib import Path

# 确保 tests 能导入 finsight 包
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
