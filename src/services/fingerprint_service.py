"""
数字指纹业务逻辑：

最小闭环：
1. 从本地读取 txt 文件
2. 计算整篇文档 MD5
3. 分句后为每个片段计算 MD5
4. 将结果写入 digital_fingerprint_doc 表

这里的设计与 Java DLP 系统对接约定：
- digital_fingerprint_doc 是“权威指纹库”
- doc_unique_id：文档在整个系统中的唯一标识（默认使用 UUID，可由外部传入覆盖）
- 对于整篇文档级指纹：
    - doc_shard_id: NULL
    - fingerprint_value: 文档整体 MD5
    - shard_fingerprint: NULL
- 对于分片/分句级指纹：
    - doc_shard_id: 从 0 开始递增
    - fingerprint_value: 分片 MD5（便于通过 idx_fingerprint_value 索引查询）
    - shard_fingerprint: 同 fingerprint_value（语义上标明其为分片指纹）
"""

from __future__ import annotations

import uuid
from typing import List, Optional

from src.database.connection import get_connection
from src.processors.file_processor import FileInfo, read_text_file
from src.processors.fingerprint import md5_text
from src.processors.text_segmenter import split_sentences


def _generate_doc_unique_id() -> str:
    return uuid.uuid4().hex


def ingest_text_file(
    file_path: str,
    doc_unique_id: Optional[str] = None,
    doc_source: str = "local_import",
    sensitive_level: int = 0,
    max_sentence_length: int = 500,
) -> str:
    """
    处理一个本地 txt 文件，并写入 digital_fingerprint_doc。

    :param file_path: 本地文件路径
    :param doc_unique_id: 可选，外部指定的文档唯一标识；为空则自动生成 UUID
    :param doc_source: 文档来源描述，默认 'local_import'
    :param sensitive_level: 敏感等级（0-3），与现有 DLP 体系对齐
    :param max_sentence_length: 分句时的最大长度控制
    :return: 实际使用的 doc_unique_id（便于调用方记录）
    """
    doc_id = doc_unique_id or _generate_doc_unique_id()

    file_info = read_text_file(file_path)
    document_md5 = md5_text(file_info.content)

    # 分句
    sentences: List[str] = split_sentences(file_info.content, max_length=max_sentence_length)

    # 构造待插入的数据行
    rows = _build_rows_for_digital_fingerprint_doc(
        doc_id=doc_id,
        file_info=file_info,
        document_md5=document_md5,
        sentences=sentences,
        doc_source=doc_source,
        sensitive_level=sensitive_level,
    )

    _insert_digital_fingerprints(rows)
    return doc_id


def _build_rows_for_digital_fingerprint_doc(
    doc_id: str,
    file_info: FileInfo,
    document_md5: str,
    sentences: List[str],
    doc_source: str,
    sensitive_level: int,
) -> List[dict]:
    """
    根据文件信息和分句结果，生成插入 digital_fingerprint_doc 的记录。
    """
    rows: List[dict] = []

    # 1. 文档整体指纹记录（doc_shard_id = NULL）
    rows.append(
        {
            "doc_unique_id": doc_id,
            "doc_name": file_info.name,
            "doc_type": file_info.doc_type,
            "doc_size": file_info.size,
            "fingerprint_type": "md5",
            "fingerprint_value": document_md5,
            "doc_shard_id": None,
            "shard_fingerprint": None,
            "doc_source": doc_source,
            "sensitive_level": sensitive_level,
        }
    )

    # 2. 分片/分句指纹记录（doc_shard_id 从 0 开始）
    for idx, sentence in enumerate(sentences):
        seg_md5 = md5_text(sentence)
        rows.append(
            {
                "doc_unique_id": doc_id,
                "doc_name": file_info.name,
                "doc_type": file_info.doc_type,
                "doc_size": None,  # 分片级记录不单独记录大小
                "fingerprint_type": "md5",
                "fingerprint_value": seg_md5,
                "doc_shard_id": idx,
                "shard_fingerprint": seg_md5,
                "doc_source": doc_source,
                "sensitive_level": sensitive_level,
            }
        )

    return rows


def _insert_digital_fingerprints(rows: List[dict]) -> None:
    """
    批量插入 digital_fingerprint_doc。
    """
    if not rows:
        return

    sql = """
    INSERT INTO digital_fingerprint_doc (
        doc_unique_id,
        doc_name,
        doc_type,
        doc_size,
        fingerprint_type,
        fingerprint_value,
        doc_shard_id,
        shard_fingerprint,
        doc_source,
        sensitive_level,
        is_deleted
    ) VALUES (
        %(doc_unique_id)s,
        %(doc_name)s,
        %(doc_type)s,
        %(doc_size)s,
        %(fingerprint_type)s,
        %(fingerprint_value)s,
        %(doc_shard_id)s,
        %(shard_fingerprint)s,
        %(doc_source)s,
        %(sensitive_level)s,
        0
    )
    """

    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.executemany(sql, rows)

