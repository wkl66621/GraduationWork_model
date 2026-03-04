"""
CoBAn 文本预处理模块。

职责：
- 对原始文本进行标准化、分词、停用词过滤；
- 构建 1~3 gram 术语，供聚类与术语打分阶段复用；
- 读取目录语料，转换为统一训练样本结构。
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Set, Tuple

import jieba


TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]+")
DEFAULT_ALLOWED_SUFFIX = {".txt", ".md", ".log"}


@dataclass
class CobanCorpusDocument:
    """CoBAn 语料文档对象。"""

    doc_uid: str
    doc_name: str
    doc_path: str
    source_type: str
    is_confidential: bool
    label: Optional[str]
    raw_text: str
    tokens: List[str]
    terms: List[str]
    preprocessed_text: str


def load_stopwords(stopwords_path: Optional[str | Path] = None) -> Set[str]:
    """加载停用词集合。

    Args:
        stopwords_path: 停用词文件路径；未传或文件不存在时返回空集合。

    Returns:
        Set[str]: 停用词字符串集合。
    """

    if stopwords_path is None:
        return set()
    path = Path(stopwords_path).expanduser().resolve()
    if not path.exists():
        return set()
    words = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        item = line.strip()
        if item:
            words.add(item)
    return words


def tokenize_text(text: str, stopwords: Optional[Set[str]] = None) -> List[str]:
    """将中英文混合文本切分为 token 列表。

    Args:
        text: 输入文本。
        stopwords: 停用词集合。

    Returns:
        List[str]: 过滤后的 token 序列。
    """

    stopword_set = stopwords or set()
    lowered = text.lower()
    tokens: List[str] = []
    for match in TOKEN_PATTERN.finditer(lowered):
        piece = match.group(0)
        if not piece:
            continue
        if re.fullmatch(r"[\u4e00-\u9fff]+", piece):
            parts = [seg.strip() for seg in jieba.lcut(piece) if seg.strip()]
        else:
            parts = [piece]
        for token in parts:
            if token in stopword_set:
                continue
            if len(token) == 1 and not token.isdigit():
                continue
            tokens.append(token)
    return tokens


def build_ngram_terms(tokens: Sequence[str], ngram_range: Tuple[int, int] = (1, 3)) -> List[str]:
    """将 token 序列转换为 n-gram 术语序列。

    Args:
        tokens: token 列表。
        ngram_range: ngram 范围，格式为 `(min_n, max_n)`。

    Returns:
        List[str]: n-gram 术语列表（使用空格连接）。
    """

    if not tokens:
        return []
    min_n, max_n = ngram_range
    min_n = max(1, min_n)
    max_n = max(min_n, max_n)

    terms: List[str] = []
    total = len(tokens)
    for n in range(min_n, max_n + 1):
        if n > total:
            continue
        for idx in range(total - n + 1):
            terms.append(" ".join(tokens[idx : idx + n]))
    return terms


def preprocess_text(
    text: str,
    stopwords: Optional[Set[str]] = None,
    ngram_range: Tuple[int, int] = (1, 3),
) -> tuple[List[str], List[str], str]:
    """执行完整文本预处理并返回关键结果。

    Args:
        text: 待处理文本。
        stopwords: 停用词集合。
        ngram_range: ngram 范围。

    Returns:
        tuple[List[str], List[str], str]: 依次为 tokens、terms、标准化文本。
    """

    tokens = tokenize_text(text=text, stopwords=stopwords)
    terms = build_ngram_terms(tokens=tokens, ngram_range=ngram_range)
    normalized_text = " ".join(tokens)
    return tokens, terms, normalized_text


def split_term_to_tokens(term: str) -> List[str]:
    """将术语字符串拆分为 token 序列。

    Args:
        term: 由空格连接的术语字符串。

    Returns:
        List[str]: 术语 token 列表。
    """

    return [token.strip() for token in term.split(" ") if token.strip()]


def locate_term_token_ranges(tokens: Sequence[str], term: str) -> List[Tuple[int, int]]:
    """在 token 序列中定位术语出现区间。

    Args:
        tokens: 文档 token 序列。
        term: 待定位术语（允许 1~N gram，空格分隔）。

    Returns:
        List[Tuple[int, int]]: 命中区间列表，格式为 `(start, end_exclusive)`。
    """

    term_tokens = split_term_to_tokens(term)
    if not tokens or not term_tokens:
        return []
    window_size = len(term_tokens)
    if window_size > len(tokens):
        return []

    matched_ranges: List[Tuple[int, int]] = []
    for idx in range(len(tokens) - window_size + 1):
        if list(tokens[idx : idx + window_size]) == term_tokens:
            matched_ranges.append((idx, idx + window_size))
    return matched_ranges


def collect_context_tokens(
    tokens: Sequence[str],
    term_ranges: Sequence[Tuple[int, int]],
    context_span: int = 20,
) -> List[str]:
    """基于术语出现位置提取上下文 token。

    Args:
        tokens: 文档 token 序列。
        term_ranges: 术语命中区间列表，元素格式为 `(start, end_exclusive)`。
        context_span: 上下文窗口半径（左右各取多少 token）。

    Returns:
        List[str]: 去重后的上下文 token 列表。
    """

    if not tokens or not term_ranges:
        return []
    span = max(0, context_span)
    if span == 0:
        return []

    collected: Set[str] = set()
    token_length = len(tokens)
    for start, end in term_ranges:
        left_start = max(0, start - span)
        right_end = min(token_length, end + span)
        for idx in range(left_start, right_end):
            if start <= idx < end:
                continue
            item = tokens[idx].strip()
            if item:
                collected.add(item)
    return sorted(collected)


def _new_doc_uid() -> str:
    """生成文档 UID。"""

    return uuid.uuid4().hex


def build_corpus_document(
    raw_text: str,
    doc_name: str,
    doc_path: str,
    source_type: str,
    is_confidential: bool,
    label: Optional[str],
    stopwords: Optional[Set[str]] = None,
    ngram_range: Tuple[int, int] = (1, 3),
    doc_uid: Optional[str] = None,
) -> CobanCorpusDocument:
    """将原始文本封装为 CoBAn 训练文档对象。

    Args:
        raw_text: 文档全文。
        doc_name: 文档名称。
        doc_path: 文档路径。
        source_type: 来源类型（real/mock）。
        is_confidential: 是否机密标签。
        label: 业务标签。
        stopwords: 停用词集合。
        ngram_range: ngram 范围。
        doc_uid: 文档 UID，未传时自动生成。

    Returns:
        CobanCorpusDocument: 标准化后的文档结构。
    """

    tokens, terms, normalized_text = preprocess_text(
        text=raw_text,
        stopwords=stopwords,
        ngram_range=ngram_range,
    )
    return CobanCorpusDocument(
        doc_uid=doc_uid or _new_doc_uid(),
        doc_name=doc_name,
        doc_path=doc_path,
        source_type=source_type,
        is_confidential=is_confidential,
        label=label,
        raw_text=raw_text,
        tokens=tokens,
        terms=terms,
        preprocessed_text=normalized_text,
    )


def load_documents_from_directory(
    directory: str | Path,
    source_type: str,
    is_confidential: bool,
    label: Optional[str],
    stopwords: Optional[Set[str]] = None,
    ngram_range: Tuple[int, int] = (1, 3),
    allowed_suffix: Optional[Iterable[str]] = None,
) -> List[CobanCorpusDocument]:
    """从目录中读取文本文件并构造语料对象列表。

    Args:
        directory: 语料目录。
        source_type: 来源类型（real/mock）。
        is_confidential: 目录下文档是否机密。
        label: 目录标签。
        stopwords: 停用词集合。
        ngram_range: ngram 范围。
        allowed_suffix: 允许的后缀集合。

    Returns:
        List[CobanCorpusDocument]: 文档对象列表。
    """

    target_dir = Path(directory).expanduser().resolve()
    if not target_dir.exists():
        return []
    suffixes = {item.lower() for item in (allowed_suffix or DEFAULT_ALLOWED_SUFFIX)}
    docs: List[CobanCorpusDocument] = []
    for file_path in sorted(target_dir.rglob("*")):
        if not file_path.is_file():
            continue
        if file_path.suffix.lower() not in suffixes:
            continue
        raw_text = file_path.read_text(encoding="utf-8", errors="ignore")
        docs.append(
            build_corpus_document(
                raw_text=raw_text,
                doc_name=file_path.name,
                doc_path=str(file_path),
                source_type=source_type,
                is_confidential=is_confidential,
                label=label,
                stopwords=stopwords,
                ngram_range=ngram_range,
            )
        )
    return docs
