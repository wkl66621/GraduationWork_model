"""
FastAPI 应用入口。

说明：
- 保留原有的领域逻辑（processors/services/database/config）
- 通过 FastAPI 提供 HTTP 接口，便于与 Java DLP 系统或本地工具集成
"""

from __future__ import annotations

from fastapi import FastAPI

from src.api.routers import api_router
from src.database import init_database


def create_app() -> FastAPI:
    """
    创建并配置 FastAPI 应用实例。
    """
    app = FastAPI(
        title="Text Fingerprint Service",
        description="用于生成并管理文本类文档数字指纹的本地服务。",
        version="1.0.0",
    )

    # 注册路由
    app.include_router(api_router)

    # 启动时初始化数据库（幂等）
    @app.on_event("startup")
    def _init_db_on_startup() -> None:
        init_database()

    return app


app = create_app()

"""
项目入口文件（命令行接口 CLI）。

功能：
- show-config: 打印当前配置
- init-db: 初始化数据库表结构
- ingest-file: 导入单个 txt 文件的数字指纹（文档级 + 分片级）
"""

from __future__ import annotations

import click

from src.config import settings
from src.database import init_database
from src.services.fingerprint_service import ingest_text_file


@click.group()
def cli() -> None:
    """文本数字指纹工具。"""


@cli.command("show-config")
def show_config() -> None:
    """打印当前配置（应用、路径、数据库）。"""
    app_cfg = settings.app
    paths_cfg = settings.paths
    db_cfg = settings.database

    click.echo(f"应用名称: {app_cfg.name}  (env={app_cfg.env})")
    click.echo(f"输入目录: {paths_cfg.input_dir}")
    click.echo(f"输出目录: {paths_cfg.output_dir}")
    click.echo(
        f"数据库: mysql://{db_cfg.user}:***@{db_cfg.host}:{db_cfg.port}/{db_cfg.db}"
    )


@cli.command("init-db")
def init_db_cmd() -> None:
    """初始化数据库表结构（包括 digital_fingerprint_doc 等）。"""
    click.echo("开始初始化数据库表结构...")
    init_database()
    click.echo("数据库初始化完成。")


@cli.command("ingest-file")
@click.argument(
    "file_path",
    type=click.Path(exists=True, dir_okay=False, readable=True, path_type=str),
)
@click.option(
    "--doc-unique-id",
    type=str,
    default=None,
    help="可选，指定文档唯一ID；不传则自动生成UUID。",
)
@click.option(
    "--doc-source",
    type=str,
    default="local_import",
    show_default=True,
    help="文档来源描述（如 upload/system_import 等）。",
)
@click.option(
    "--sensitive-level",
    type=click.IntRange(0, 3),
    default=0,
    show_default=True,
    help="敏感等级（0-无，1-低，2-中，3-高）。",
)
@click.option(
    "--max-sentence-length",
    type=int,
    default=500,
    show_default=True,
    help="分句时的最大长度控制，过长句子会再切分。",
)
def ingest_file_cmd(
    file_path: str,
    doc_unique_id: str | None,
    doc_source: str,
    sensitive_level: int,
    max_sentence_length: int,
) -> None:
    """
    导入单个 txt 文件的数字指纹，并写入 digital_fingerprint_doc。
    """
    doc_id = ingest_text_file(
        file_path=file_path,
        doc_unique_id=doc_unique_id,
        doc_source=doc_source,
        sensitive_level=sensitive_level,
        max_sentence_length=max_sentence_length,
    )
    click.echo(f"导入完成，doc_unique_id = {doc_id}")


if __name__ == "__main__":
    cli()

"""
项目入口文件。

当前阶段：
- 测试配置管理模块是否正常工作
- 提供一个用于初始化数据库表结构的入口

后续会在此接入 Click 命令行接口。
"""

from __future__ import annotations

from src.config import settings
from src.database import init_database


def main() -> None:
    app_cfg = settings.app
    paths_cfg = settings.paths
    db_cfg = settings.database

    print(f"应用名称: {app_cfg.name}  (env={app_cfg.env})")
    print(f"输入目录: {paths_cfg.input_dir}")
    print(f"输出目录: {paths_cfg.output_dir}")
    print(
        f"数据库: mysql://{db_cfg.user}:***@{db_cfg.host}:{db_cfg.port}/{db_cfg.db}"
    )

    # 初始化数据库表结构
    print("开始初始化数据库表结构...")
    init_database()
    print("数据库初始化完成。")


if __name__ == "__main__":
    main()


