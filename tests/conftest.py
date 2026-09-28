"""pytest 配置：让测试套件共用一个隔离的战绩数据库，避免污染仓库里的
geom_aim_stats.db，也避免测试之间互相影响。Game() 构造时 LocalStatsStore 会读
GEOM_AIM_STATS_DB 这个环境变量，所以这里在导入任何被测模块之前就设好。
"""

import os
import tempfile


def _make_isolated_db():
    fd, path = tempfile.mkstemp(suffix=".db", prefix="geom_aim_test_")
    os.close(fd)
    os.unlink(path)          # 只借路径，文件由 LocalStatsStore 自建
    return path


os.environ.setdefault("GEOM_AIM_STATS_DB", _make_isolated_db())
