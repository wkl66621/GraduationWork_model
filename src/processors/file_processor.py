"""
文件读取与基础信息抽取。

当前聚焦 txt 文本文件，后续可扩展到 pdf/word 等。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class FileInfo:
    """文本文件元信息与内容载体。"""
    path: Path
    name: str
    size: int
    encoding: str
    doc_type: str
    content: str


def read_text_file(path: str | Path, encoding: Optional[str] = "utf-8") -> FileInfo:
    """读取 txt 文件并返回结构化文件信息。

    Args:
        path: 文件路径，支持 `str` 与 `Path`。
        encoding: 文本编码，默认 `utf-8`。

    Returns:
        FileInfo: 含路径、文件名、大小、编码和文本内容的对象。

    Raises:
        FileNotFoundError: 目标路径不存在或不是文件时抛出。
    """
    p = Path(path).expanduser().resolve()
    if not p.is_file():
        raise FileNotFoundError(f"文件不存在: {p}")

    # 这里只做简单实现，先假定编码正确；后续如有需要可引入 chardet 等库做自动探测
    enc = encoding or "utf-8"
    text = p.read_text(encoding=enc)

    stat = p.stat()
    return FileInfo(
        path=p,
        name=p.name,
        size=stat.st_size,
        encoding=enc,
        doc_type="txt",
        content=text,
    )

