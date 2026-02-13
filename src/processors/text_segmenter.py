"""
文本分段/分句模块。

当前提供一个简单、可配置的分句实现：
- 按中英文句号、问号、感叹号以及换行符切分
- 支持设置最大长度，过长句子会再次切分

后续可以在此基础上增加：
- 基于 jieba 的更精细中文分词
- 基于统计或 ML 的语义分段
"""

from __future__ import annotations

import re
from typing import Iterable, List


SENTENCE_DELIMITERS = r"[。！？!?；;]+"


def _normalize_text(text: str) -> str:
    # 去掉两端空白，并规范换行
    return text.replace("\r\n", "\n").replace("\r", "\n").strip()


def split_sentences(
    text: str,
    max_length: int = 500,
) -> List[str]:
    """
    基础分句：
    1. 先按中英文句号/问号/感叹号/分号切分
    2. 对于单个句子超过 max_length 的，再按固定长度继续切分
    """
    norm = _normalize_text(text)
    if not norm:
        return []

    # 保留分隔符到句尾
    parts = re.split(f"({SENTENCE_DELIMITERS})", norm)

    sentences: List[str] = []
    buf = ""
    for i in range(0, len(parts), 2):
        seg = parts[i]
        if not seg:
            continue
        tail = parts[i + 1] if i + 1 < len(parts) else ""
        candidate = (seg + tail).strip()
        if not candidate:
            continue

        sentences.extend(_split_by_length(candidate, max_length))

    return [s for s in sentences if s.strip()]


def _split_by_length(text: str, max_length: int) -> Iterable[str]:
    """
    将过长的句子按固定长度拆分，避免后续处理（如向量化）时过长。
    """
    if len(text) <= max_length:
        return [text]
    return [text[i : i + max_length] for i in range(0, len(text), max_length)]

