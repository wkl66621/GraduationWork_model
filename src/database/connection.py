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
    """
    创建一个新的数据库连接。
    """
    kwargs = get_pymysql_kwargs()
    # 使用 DictCursor 便于后续以字典形式访问字段
    kwargs["cursorclass"] = DictCursor
    return pymysql.connect(**kwargs)


@contextmanager
def get_connection() -> Iterator[pymysql.connections.Connection]:
    """
    上下文管理形式获取连接，自动处理提交与关闭。
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

