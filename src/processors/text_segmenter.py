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
    """规范化换行并去除首尾空白。

    Args:
        text: 原始文本。

    Returns:
        str: 规范化后的文本。
    """
    # 去掉两端空白，并规范换行
    return text.replace("\r\n", "\n").replace("\r", "\n").strip()


def split_sentences(
    text: str,
    max_length: int = 500,
) -> List[str]:
    """按标点进行基础分句，并控制句长上限。

    Args:
        text: 待分句文本。
        max_length: 单句最大长度，超过后继续等长切分。

    Returns:
        List[str]: 清洗后句子列表。
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
    """将超长句子按固定长度切分。

    Args:
        text: 待切分文本。
        max_length: 单段最大长度。

    Returns:
        Iterable[str]: 切分后的文本片段序列。
    """
    if len(text) <= max_length:
        return [text]
    return [text[i : i + max_length] for i in range(0, len(text), max_length)]

