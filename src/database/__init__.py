"""
数据库模块。

职责：
- 提供获取数据库连接的统一接口
- 提供初始化数据库表结构的函数
- 暴露基础的仓储（Repository）类
"""

from .connection import get_connection
# from .init_db import init_database

__all__ = ["get_connection"]

