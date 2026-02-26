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
    """返回全局配置对象。

    Returns:
        Settings: 项目级配置单例，包含 app/paths/database 三类配置。
    """
    return settings


def get_db_connection():
    """构造 FastAPI 数据库连接依赖。

    Returns:
        fastapi.Depends: 注入后可获得单次请求范围内的数据库连接。
    """
    from pymysql.connections import Connection

    def _conn() -> Generator[Connection, None, None]:
        with get_connection() as conn:
            yield conn

    return Depends(_conn)

