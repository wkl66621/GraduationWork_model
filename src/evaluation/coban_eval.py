"""
CoBAn 评估脚本模块。

职责：
- 基于已训练 CoBAn 模型对标注数据集进行批量打分；
- 输出 TPR/FPR、ROC/AUC 与推荐阈值；
- 提供可复用评估函数，供参数扫描脚本调用。
"""

from __future__ import annotations

import argparse
import json
import pickle
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from src.database.connection import get_connection
from src.processors.coban_clusterer import assign_document_to_clusters
from src.processors.coban_text_preprocessor import (
    CobanCorpusDocument,
    build_corpus_document,
    load_documents_from_directory,
    preprocess_text,
    split_term_to_tokens,
)


@dataclass
class RocPoint:
    """ROC 曲线点。"""

    threshold: float
    tpr: float
    fpr: float


@dataclass
class CobanEvalReport:
    """CoBAn 评估结果。"""

    sample_count: int
    conf_sample_count: int
    non_conf_sample_count: int
    auc: float
    recommended_threshold: float
    accuracy_at_recommended: float
    precision_at_recommended: float
    recall_at_recommended: float
    tpr_at_recommended: float
    fpr_at_recommended: float
    tp_at_recommended: int
    fp_at_recommended: int
    tn_at_recommended: int
    fn_at_recommended: int
    roc_points: List[Dict[str, float]]


def _parse_ngram_range(value: str) -> Tuple[int, int]:
    """解析 ngram 参数。"""
    pieces = [item.strip() for item in value.split(",")]
    if len(pieces) != 2:
        raise argparse.ArgumentTypeError("ngram_range 格式应为 min,max，例如 1,3")
    try:
        min_n = int(pieces[0])
        max_n = int(pieces[1])
    except ValueError as exc:
        raise argparse.ArgumentTypeError("ngram_range 需要两个整数") from exc
    if min_n < 1 or max_n < min_n:
        raise argparse.ArgumentTypeError("ngram_range 必须满足 1 <= min <= max")
    return min_n, max_n


def _mock_eval_documents(
    ngram_range: Tuple[int, int],
) -> List[CobanCorpusDocument]:
    """构造评估用 mock 语料。"""
    rows = [
        {
            "doc_name": "eval_mock_conf_01.txt",
            "is_confidential": True,
            "label": "finance",
            "raw_text": "投融资计划披露授信额度、估值区间与并购谈判策略，禁止外传。",
        },
        {
            "doc_name": "eval_mock_conf_02.txt",
            "is_confidential": True,
            "label": "tech",
            "raw_text": "核心算法参数、模型蒸馏细节和反作弊规则属于研发机密。",
        },
        {
            "doc_name": "eval_mock_non_conf_01.txt",
            "is_confidential": False,
            "label": "public",
            "raw_text": "新员工入职指引包含办公流程、考勤规范和福利说明，可公开阅读。",
        },
        {
            "doc_name": "eval_mock_non_conf_02.txt",
            "is_confidential": False,
            "label": "public",
            "raw_text": "产品帮助中心文档用于介绍基础功能和常见问题处理方式。",
        },
    ]
    docs: List[CobanCorpusDocument] = []
    for row in rows:
        docs.append(
            build_corpus_document(
                raw_text=row["raw_text"],
                doc_name=row["doc_name"],
                doc_path=f"mock://{row['doc_name']}",
                source_type="mock_eval",
                is_confidential=bool(row["is_confidential"]),
                label=row["label"],
                stopwords=None,
                ngram_range=ngram_range,
            )
        )
    return docs


def _resolve_model_path(run_id: Optional[str], model_path: Optional[str]) -> Path:
    """根据入参解析模型产物路径。"""
    if model_path:
        path = Path(model_path).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"模型文件不存在: {path}")
        return path

    if not run_id:
        raise ValueError("必须传入 run_id 或 model_path 之一。")

    sql = """
    SELECT model_artifact_path
    FROM coban_model_run
    WHERE run_id = %(run_id)s AND status = 'succeeded' AND is_deleted = 0
    LIMIT 1
    """
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql, {"run_id": run_id})
            row = cursor.fetchone()
    if row is None:
        raise ValueError(f"未找到成功训练批次: {run_id}")

    resolved = Path(row["model_artifact_path"]).expanduser().resolve()
    if not resolved.exists():
        raise FileNotFoundError(f"模型文件不存在: {resolved}")
    return resolved


def load_model_payload(run_id: Optional[str], model_path: Optional[str]) -> dict:
    """加载 CoBAn 模型 payload。"""
    resolved_path = _resolve_model_path(run_id=run_id, model_path=model_path)
    with resolved_path.open("rb") as f:
        payload = pickle.load(f)
    return payload


def load_eval_documents(
    conf_dirs: Iterable[str],
    non_conf_dirs: Iterable[str],
    ngram_range: Tuple[int, int],
    use_mock: bool,
) -> List[CobanCorpusDocument]:
    """加载评估样本。"""
    docs: List[CobanCorpusDocument] = []
    for directory in conf_dirs:
        docs.extend(
            load_documents_from_directory(
                directory=directory,
                source_type="real_eval",
                is_confidential=True,
                label="real_confidential_eval",
                stopwords=None,
                ngram_range=ngram_range,
            )
        )
    for directory in non_conf_dirs:
        docs.extend(
            load_documents_from_directory(
                directory=directory,
                source_type="real_eval",
                is_confidential=False,
                label="real_non_confidential_eval",
                stopwords=None,
                ngram_range=ngram_range,
            )
        )
    if use_mock:
        docs.extend(_mock_eval_documents(ngram_range=ngram_range))
    return docs


def _term_ratio(term_row: dict) -> float:
    """计算术语 irregular 比值。"""
    conf_support = float(term_row.get("support_conf_docs", 0))
    non_conf_support = float(term_row.get("support_non_conf_docs", 0))
    return (conf_support + 1.0) / (non_conf_support + 1.0)


def _expand_irregular_terms(
    matched_terms: Sequence[str],
    doc_tokens: Sequence[str],
    cluster_term_rows: Sequence[dict],
    irregular_ratio_threshold: float,
) -> List[str]:
    """执行 irregular 术语扩展。"""
    if not cluster_term_rows:
        return []
    matched_set = set(matched_terms)
    token_set = set(doc_tokens)
    expanded: List[str] = []
    for row in cluster_term_rows:
        term = row["term_value"]
        if term in matched_set:
            continue
        ratio = _term_ratio(row)
        if ratio < irregular_ratio_threshold:
            continue
        pieces = split_term_to_tokens(term)
        if not pieces:
            continue
        if token_set.intersection(pieces):
            expanded.append(term)
    return sorted(set(expanded))


def _cluster_score(
    similarity: float,
    matched_term_rows: Sequence[dict],
    expanded_term_rows: Sequence[dict],
    matched_context_rows: Sequence[dict],
    irregular_ratio_threshold: float,
) -> float:
    """计算单个簇机密分。"""
    import math

    term_score = sum(float(row["term_score"]) for row in matched_term_rows)
    irregular_score = 0.0
    for row in expanded_term_rows:
        base = float(row["term_score"])
        ratio = _term_ratio(row)
        bonus = min(2.0, ratio / max(1.0, irregular_ratio_threshold))
        irregular_score += base * bonus
    context_score = sum(float(row["context_score"]) for row in matched_context_rows)
    raw_score = max(0.0, float(similarity)) * (term_score + 0.7 * irregular_score + 0.5 * context_score)
    return float(1.0 - math.exp(-raw_score))


def score_document(
    text: str,
    model_payload: dict,
    top_k_clusters: int,
    cluster_similarity_threshold: Optional[float],
    irregular_ratio_threshold: float,
) -> float:
    """使用 CoBAn 模型对单文档打机密分。"""
    ngram_range = tuple(model_payload.get("params", {}).get("ngram_range", [1, 3]))
    _, doc_terms, normalized_text = preprocess_text(
        text=text,
        stopwords=None,
        ngram_range=ngram_range,
    )
    doc_tokens = normalized_text.split(" ") if normalized_text else []
    assigned_clusters = assign_document_to_clusters(
        text=normalized_text,
        vectorizer=model_payload["vectorizer"],
        centroid_vectors=model_payload["centroid_vectors"],
        top_k=max(1, int(top_k_clusters)),
        similarity_threshold=(
            float(cluster_similarity_threshold)
            if cluster_similarity_threshold is not None
            else float(model_payload.get("params", {}).get("cluster_similarity_threshold", 0.05))
        ),
    )
    conf_term_rows_all = model_payload.get("confidential_terms", [])
    context_term_rows_all = model_payload.get("context_terms", [])
    doc_term_set = set(doc_terms)
    doc_token_set = set(doc_tokens)

    cluster_scores: List[Tuple[float, float]] = []
    for cluster_id, similarity in assigned_clusters:
        cluster_conf_terms = [
            row for row in conf_term_rows_all if int(row["cluster_id"]) == int(cluster_id)
        ]
        matched_term_rows = [row for row in cluster_conf_terms if row["term_value"] in doc_term_set]
        matched_terms = sorted({row["term_value"] for row in matched_term_rows})
        expanded_terms = _expand_irregular_terms(
            matched_terms=matched_terms,
            doc_tokens=doc_tokens,
            cluster_term_rows=cluster_conf_terms,
            irregular_ratio_threshold=irregular_ratio_threshold,
        )
        expanded_term_rows = [row for row in cluster_conf_terms if row["term_value"] in set(expanded_terms)]

        effective_terms = set(matched_terms) | set(expanded_terms)
        cluster_context_rows = [
            row for row in context_term_rows_all if int(row["cluster_id"]) == int(cluster_id)
        ]
        matched_context_rows = [
            row
            for row in cluster_context_rows
            if row["conf_term"] in effective_terms and row["context_term"] in doc_token_set
        ]
        score = _cluster_score(
            similarity=float(similarity),
            matched_term_rows=matched_term_rows,
            expanded_term_rows=expanded_term_rows,
            matched_context_rows=matched_context_rows,
            irregular_ratio_threshold=irregular_ratio_threshold,
        )
        cluster_scores.append((float(similarity), float(score)))

    sim_sum = sum(item[0] for item in cluster_scores)
    if sim_sum > 0:
        return float(sum(sim * score for sim, score in cluster_scores) / sim_sum)
    return float(max((score for _, score in cluster_scores), default=0.0))


def _confusion_counts(
    y_true: Sequence[int],
    y_score: Sequence[float],
    threshold: float,
) -> Tuple[int, int, int, int]:
    """计算 TP/FP/TN/FN。"""
    tp = fp = tn = fn = 0
    for label, score in zip(y_true, y_score):
        pred = 1 if score >= threshold else 0
        if label == 1 and pred == 1:
            tp += 1
        elif label == 0 and pred == 1:
            fp += 1
        elif label == 0 and pred == 0:
            tn += 1
        else:
            fn += 1
    return tp, fp, tn, fn


def _rate(numerator: float, denominator: float) -> float:
    """安全除法。"""
    if denominator <= 0:
        return 0.0
    return float(numerator / denominator)


def _roc_points(y_true: Sequence[int], y_score: Sequence[float]) -> List[RocPoint]:
    """生成 ROC 曲线点。"""
    unique_thresholds = sorted(set(float(item) for item in y_score), reverse=True)
    thresholds = [1.000001] + unique_thresholds + [-0.000001]
    points: List[RocPoint] = []
    for threshold in thresholds:
        tp, fp, tn, fn = _confusion_counts(y_true=y_true, y_score=y_score, threshold=threshold)
        tpr = _rate(tp, tp + fn)
        fpr = _rate(fp, fp + tn)
        points.append(RocPoint(threshold=float(threshold), tpr=tpr, fpr=fpr))
    return points


def _auc_from_roc(points: Sequence[RocPoint]) -> float:
    """基于 ROC 点计算 AUC（梯形法）。"""
    if not points:
        return 0.0
    sorted_points = sorted(points, key=lambda item: item.fpr)
    area = 0.0
    for index in range(1, len(sorted_points)):
        prev_point = sorted_points[index - 1]
        curr_point = sorted_points[index]
        width = curr_point.fpr - prev_point.fpr
        height = (curr_point.tpr + prev_point.tpr) / 2.0
        area += width * height
    return float(max(0.0, min(1.0, area)))


def _recommend_threshold(
    y_true: Sequence[int],
    y_score: Sequence[float],
    points: Sequence[RocPoint],
) -> Tuple[float, Tuple[int, int, int, int]]:
    """基于 Youden 指数推荐阈值。"""
    if not points:
        return 0.5, (0, 0, 0, 0)
    best_threshold = 0.5
    best_youden = float("-inf")
    best_tpr = -1.0
    best_fpr = 2.0
    for point in points:
        youden = point.tpr - point.fpr
        if (
            youden > best_youden
            or (youden == best_youden and point.tpr > best_tpr)
            or (youden == best_youden and point.tpr == best_tpr and point.fpr < best_fpr)
        ):
            best_youden = youden
            best_tpr = point.tpr
            best_fpr = point.fpr
            best_threshold = point.threshold
    return best_threshold, _confusion_counts(y_true=y_true, y_score=y_score, threshold=best_threshold)


def evaluate_scores(y_true: Sequence[int], y_score: Sequence[float]) -> CobanEvalReport:
    """基于标签与分数计算完整评估报告。"""
    if len(y_true) != len(y_score):
        raise ValueError("评估失败：y_true 与 y_score 长度不一致。")
    if not y_true:
        raise ValueError("评估失败：样本为空。")

    roc_points = _roc_points(y_true=y_true, y_score=y_score)
    auc = _auc_from_roc(points=roc_points)
    threshold, (tp, fp, tn, fn) = _recommend_threshold(
        y_true=y_true,
        y_score=y_score,
        points=roc_points,
    )
    tpr = _rate(tp, tp + fn)
    fpr = _rate(fp, fp + tn)
    precision = _rate(tp, tp + fp)
    recall = tpr
    accuracy = _rate(tp + tn, len(y_true))
    return CobanEvalReport(
        sample_count=len(y_true),
        conf_sample_count=int(sum(y_true)),
        non_conf_sample_count=int(len(y_true) - sum(y_true)),
        auc=auc,
        recommended_threshold=float(threshold),
        accuracy_at_recommended=accuracy,
        precision_at_recommended=precision,
        recall_at_recommended=recall,
        tpr_at_recommended=tpr,
        fpr_at_recommended=fpr,
        tp_at_recommended=tp,
        fp_at_recommended=fp,
        tn_at_recommended=tn,
        fn_at_recommended=fn,
        roc_points=[asdict(item) for item in roc_points],
    )


def evaluate_model(
    model_payload: dict,
    docs: Sequence[CobanCorpusDocument],
    top_k_clusters: int,
    cluster_similarity_threshold: Optional[float],
    irregular_ratio_threshold: float,
) -> CobanEvalReport:
    """在样本集上评估 CoBAn 模型。"""
    y_true: List[int] = []
    y_score: List[float] = []
    for doc in docs:
        score = score_document(
            text=doc.raw_text,
            model_payload=model_payload,
            top_k_clusters=top_k_clusters,
            cluster_similarity_threshold=cluster_similarity_threshold,
            irregular_ratio_threshold=irregular_ratio_threshold,
        )
        y_true.append(1 if doc.is_confidential else 0)
        y_score.append(float(score))
    return evaluate_scores(y_true=y_true, y_score=y_score)


def _build_parser() -> argparse.ArgumentParser:
    """构建命令行解析器。"""
    parser = argparse.ArgumentParser(description="CoBAn 模型评估脚本")
    parser.add_argument("--run-id", type=str, default=None, help="训练批次 run_id")
    parser.add_argument("--model-path", type=str, default=None, help="模型文件路径（优先级高于 run_id）")
    parser.add_argument("--eval-conf-dir", action="append", default=[], help="评估机密语料目录，可重复传入")
    parser.add_argument(
        "--eval-non-conf-dir",
        action="append",
        default=[],
        help="评估非机密语料目录，可重复传入",
    )
    parser.add_argument("--use-mock", action="store_true", help="追加内置 mock 评估语料")
    parser.add_argument(
        "--ngram-range",
        type=_parse_ngram_range,
        default=(1, 3),
        help="评估语料预处理 ngram 范围，格式 min,max",
    )
    parser.add_argument("--top-k-clusters", type=int, default=3, help="检测阶段 TopK cluster")
    parser.add_argument(
        "--cluster-similarity-threshold",
        type=float,
        default=None,
        help="覆盖模型 cluster 相似度阈值",
    )
    parser.add_argument(
        "--irregular-ratio-threshold",
        type=float,
        default=20.0,
        help="irregular 术语扩展阈值",
    )
    parser.add_argument("--output-json", type=str, default=None, help="评估结果输出路径")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    """评估脚本主函数。"""
    parser = _build_parser()
    args = parser.parse_args(argv)

    model_payload = load_model_payload(run_id=args.run_id, model_path=args.model_path)
    docs = load_eval_documents(
        conf_dirs=args.eval_conf_dir,
        non_conf_dirs=args.eval_non_conf_dir,
        ngram_range=args.ngram_range,
        use_mock=bool(args.use_mock),
    )
    if not docs:
        raise ValueError("评估失败：未加载到任何评估样本。")

    report = evaluate_model(
        model_payload=model_payload,
        docs=docs,
        top_k_clusters=max(1, int(args.top_k_clusters)),
        cluster_similarity_threshold=(
            float(args.cluster_similarity_threshold)
            if args.cluster_similarity_threshold is not None
            else None
        ),
        irregular_ratio_threshold=max(1.0, float(args.irregular_ratio_threshold)),
    )
    payload = asdict(report)
    if args.run_id:
        payload["run_id"] = args.run_id
    if args.model_path:
        payload["model_path"] = str(Path(args.model_path).expanduser().resolve())
    output = json.dumps(payload, ensure_ascii=False, indent=2)
    print(output)

    if args.output_json:
        output_path = Path(args.output_json).expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(output, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

