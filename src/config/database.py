"""
数据库相关的配置辅助函数。

目前主要负责把全局配置转换为 PyMySQL 等驱动可直接使用的参数。
"""

from __future__ import annotations

from typing import Dict, Any, Optional

from .settings import settings, DatabaseConfig


def get_db_config(override: Optional[DatabaseConfig] = None) -> DatabaseConfig:
    """获取数据库配置对象。

    Args:
        override: 可选覆盖配置，常用于测试场景。

    Returns:
        DatabaseConfig: 最终生效的数据库配置。
    """
    return override or settings.database


def get_pymysql_kwargs(db_cfg: Optional[DatabaseConfig] = None) -> Dict[str, Any]:
    """将数据库配置转换为 PyMySQL 连接参数。

    Args:
        db_cfg: 可选数据库配置，未传时使用全局配置。

    Returns:
        Dict[str, Any]: 可直接传给 `pymysql.connect` 的参数字典。
    """
    cfg = get_db_config(db_cfg)
    return {
        "host": cfg.host,
        "port": cfg.port,
        "user": cfg.user,
        "password": cfg.password,
        "database": cfg.db,
        "charset": cfg.charset,
        "cursorclass": None,  # 后续根据需要在数据库模块中指定
    }

