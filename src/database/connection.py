"""
数据库连接管理。

当前使用 PyMySQL 直连 MySQL，后续如果需要可以在这里替换为连接池实现。
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

import pymysql
from pymysql.cursors import DictCursor

from src.config.database import get_pymysql_kwargs


def create_connection() -> pymysql.connections.Connection:
    """创建数据库连接对象。

    Returns:
        pymysql.connections.Connection: 可执行 SQL 的连接实例。
    """
    kwargs = get_pymysql_kwargs()
    # 使用 DictCursor 便于后续以字典形式访问字段
    kwargs["cursorclass"] = DictCursor
    return pymysql.connect(**kwargs)


@contextmanager
def get_connection() -> Iterator[pymysql.connections.Connection]:
    """以上下文管理器方式提供数据库连接。

    Yields:
        pymysql.connections.Connection: 当前代码块使用的数据库连接。

    Raises:
        Exception: 上下文内出现异常时回滚并继续抛出原异常。
    """
    conn = create_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

