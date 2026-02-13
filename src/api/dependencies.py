"""
FastAPI 依赖注入定义。

目前主要提供：
- 获取全局 settings
后续可扩展：
- 数据库 session 管理
- 当前用户 / 鉴权信息
"""

from __future__ import annotations

from typing import Generator

from fastapi import Depends

from src.config import settings
from src.database.connection import get_connection


def get_settings():
    """
    返回全局配置对象。
    直接暴露 settings，便于在路由中读取数据库或路径配置。
    """
    return settings


def get_db_connection():
    """
    提供一个数据库连接的依赖。

    注意：目前大部分写入都封装在 service 层中使用自己的 get_connection，
    若要在接口层直接访问数据库，可使用该依赖。
    """
    from pymysql.connections import Connection

    def _conn() -> Generator[Connection, None, None]:
        with get_connection() as conn:
            yield conn

    return Depends(_conn)

