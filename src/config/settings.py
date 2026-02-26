"""
应用配置管理模块。

职责：
- 从 YAML 配置文件中加载配置
- 提供类型化的配置对象，便于后续扩展（数据库、路径、ML 参数等）
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "config.yaml"


@dataclass
class AppConfig:
    """应用级配置。"""
    name: str = "TextFingerprint"
    env: str = "dev"
    log_level: str = "INFO"


@dataclass
class PathsConfig:
    """项目路径配置。"""
    base_dir: Path = PROJECT_ROOT
    input_dir: Path = PROJECT_ROOT / "data" / "input"
    output_dir: Path = PROJECT_ROOT / "data" / "output"
    log_dir: Path = PROJECT_ROOT / "data" / "logs"


@dataclass
class DatabaseConfig:
    """数据库连接配置。"""
    host: str = "localhost"
    port: int = 3306
    user: str = "gw"
    password: str = "569332"
    db: str = "graduation_work"
    charset: str = "utf8mb4"


@dataclass
class Settings:
    """全局配置聚合对象。"""
    app: AppConfig
    paths: PathsConfig
    database: DatabaseConfig

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Settings":
        """从字典构建强类型配置对象。

        Args:
            data: 原始配置字典，通常来源于 YAML 文件。

        Returns:
            Settings: 组装后的配置对象。
        """
        app_cfg = AppConfig(**data.get("app", {}))

        paths_raw = data.get("paths", {})
        paths_cfg = PathsConfig(
            base_dir=Path(paths_raw.get("base_dir", PROJECT_ROOT)),
            input_dir=Path(paths_raw.get("input_dir", PROJECT_ROOT / "data" / "input")),
            output_dir=Path(paths_raw.get("output_dir", PROJECT_ROOT / "data" / "output")),
            log_dir=Path(paths_raw.get("log_dir", PROJECT_ROOT / "data" / "logs")),
        )

        db_cfg = DatabaseConfig(**data.get("database", {}))

        return cls(app=app_cfg, paths=paths_cfg, database=db_cfg)


def _load_yaml_config(path: Path) -> Dict[str, Any]:
    """读取 YAML 配置文件并返回字典。

    Args:
        path: 配置文件路径。

    Returns:
        Dict[str, Any]: 配置字典；文件不存在时返回空字典。

    Raises:
        ValueError: YAML 顶层结构不是字典时抛出。
    """
    if not path.exists():
        # 如果没有配置文件，返回空字典，使用默认值
        return {}

    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    if not isinstance(raw, dict):
        raise ValueError(f"配置文件格式错误：{path}")

    return raw


def load_settings(config_path: Optional[str | Path] = None) -> Settings:
    """加载并合成全局配置。

    加载顺序（优先级从低到高）：
    1. dataclass 默认值
    2. YAML 配置
    3. 环境变量覆盖

    Args:
        config_path: 可选配置文件路径，未传时使用默认路径。

    Returns:
        Settings: 最终生效的配置对象。
    """
    final_path: Path = (
        Path(config_path).expanduser().resolve()
        if config_path is not None
        else DEFAULT_CONFIG_PATH
    )

    data = _load_yaml_config(final_path)
    settings = Settings.from_dict(data)

    # 环境变量简单覆盖示例（可后续扩展为更系统化的方案）
    env_db_host = os.getenv("TF_DB_HOST")
    if env_db_host:
        settings.database.host = env_db_host

    env_db_password = os.getenv("TF_DB_PASSWORD")
    if env_db_password:
        settings.database.password = env_db_password

    return settings


# 全局单例配置对象，项目中其他模块可直接 `from src.config import settings`
settings: Settings = load_settings()

