"""
指纹计算模块。

当前仅提供 MD5 计算，后续可以在此扩展为：
- SHA256
- SimHash
- 向量化指纹（embedding 等）
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Union


def md5_text(text: str) -> str:
    """计算文本内容的 MD5 值。

    Args:
        text: 待计算哈希的文本内容。

    Returns:
        str: 32 位十六进制 MD5 字符串。
    """
    m = hashlib.md5()
    # 明确指定 utf-8，避免平台差异
    m.update(text.encode("utf-8"))
    return m.hexdigest()


def md5_file(path: Union[str, Path], chunk_size: int = 8192) -> str:
    """计算文件内容的 MD5 值（分块读取）。

    Args:
        path: 文件路径。
        chunk_size: 单次读取字节数。

    Returns:
        str: 32 位十六进制 MD5 字符串。

    Raises:
        FileNotFoundError: 文件不存在时抛出。
    """
    p = Path(path).expanduser().resolve()
    if not p.is_file():
        raise FileNotFoundError(f"文件不存在: {p}")

    m = hashlib.md5()
    with p.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            m.update(chunk)
    return m.hexdigest()

