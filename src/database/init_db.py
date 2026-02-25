"""
数据库初始化：创建基础表结构。

表设计考虑到后续可扩展性：
- documents：存储文档级信息
- segments：存储分段/分句后的片段
- fingerprints：抽象的指纹表，支持文档级、片段级、不同算法（md5、embedding 等）
"""

from __future__ import annotations

from typing import Iterable

from .connection import get_connection


CREATE_TABLE_DOCUMENTS = """
CREATE TABLE IF NOT EXISTS documents (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    file_path VARCHAR(512) NOT NULL,
    file_name VARCHAR(255) NOT NULL,
    file_size BIGINT UNSIGNED NOT NULL DEFAULT 0,
    encoding VARCHAR(64) DEFAULT NULL,
    full_md5 CHAR(32) DEFAULT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'active',
    extra JSON NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_documents_path (file_path)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""


CREATE_TABLE_SEGMENTS = """
CREATE TABLE IF NOT EXISTS segments (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    document_id BIGINT UNSIGNED NOT NULL,
    idx INT NOT NULL,
    start_offset INT NULL,
    end_offset INT NULL,
    text LONGTEXT NOT NULL,
    md5 CHAR(32) DEFAULT NULL,
    extra JSON NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_segments_document
        FOREIGN KEY (document_id) REFERENCES documents(id)
        ON DELETE CASCADE,
    UNIQUE KEY uq_segments_doc_idx (document_id, idx)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""


CREATE_TABLE_FINGERPRINTS = """
CREATE TABLE `digital_fingerprint_doc` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `doc_unique_id` varchar(64) NOT NULL COMMENT '文档唯一标识（如UUID）',
  `doc_name` varchar(255) NOT NULL COMMENT '文档名称',
  `doc_type` varchar(32) NOT NULL COMMENT '文档类型（pdf/word/txt等）',
  `doc_size` bigint DEFAULT NULL COMMENT '文档大小（字节）',
  `fingerprint_type` varchar(32) NOT NULL COMMENT '指纹类型（md5/sha256/simhash等）',
  `fingerprint_value` varchar(256) NOT NULL COMMENT '数字指纹值',
  `doc_shard_id` int DEFAULT NULL COMMENT '文档分片ID（用于大文档拆分）',
  `shard_fingerprint` varchar(256) DEFAULT NULL COMMENT '分片指纹值（大文档时非空）',
  `doc_source` varchar(128) DEFAULT NULL COMMENT '文档来源（如上传/系统导入）',
  `sensitive_level` tinyint DEFAULT '0' COMMENT '敏感等级（0-无，1-低，2-中，3-高）',
  `create_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `update_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  `is_deleted` tinyint(1) DEFAULT '0' COMMENT '逻辑删除标识（0-未删，1-已删）',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_doc_unique_id_shard` (`doc_unique_id`,`doc_shard_id`),
  KEY `idx_fingerprint_value` (`fingerprint_value`),
  KEY `idx_doc_type` (`doc_type`),
  KEY `idx_create_time` (`create_time`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='数字指纹文档库主表（与DLP检测表隔离）';
"""


# def _execute_statements(statements: Iterable[str]) -> None:
#     from pymysql import OperationalError
#
#     with get_connection() as conn:
#         with conn.cursor() as cursor:
#             for sql in statements:
#                 try:
#                     cursor.execute(sql)
#                 except OperationalError as e:
#                     # 这里简单抛出，后续可以接入日志系统
#                     raise RuntimeError(f"执行建表语句失败: {e}") from e


# def init_database() -> None:
#     """
#     初始化数据库，创建需要的表。
#     在项目首次运行或部署时调用一次即可。
#     """
#     _execute_statements(
#         [
#             CREATE_TABLE_DOCUMENTS,
#             CREATE_TABLE_SEGMENTS,
#             CREATE_TABLE_FINGERPRINTS,
#         ]
#     )

