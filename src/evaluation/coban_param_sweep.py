"""
CoBAn 参数扫描脚本模块。

职责：
- 批量组合训练参数并触发 CoBAn 训练；
- 对每组模型执行评估，输出 TPR/FPR/ROC/AUC 与推荐阈值；
- 选出最佳参数组合，生成结构化结果。
"""

from __future__ import annotations

import argparse
import itertools
import json
from dataclasses import asdict
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from src.evaluation.coban_eval import (
    evaluate_model,
    load_eval_documents,
    load_model_payload,
)
from src.services.coban_training_service import CobanTrainingRequest, train_coban_model


def _parse_int_list(value: str) -> List[int]:
    """解析整数列表参数。"""
    items = [item.strip() for item in value.split(",") if item.strip()]
    if not items:
        raise argparse.ArgumentTypeError("整数列表参数不能为空。")
    try:
        return [int(item) for item in items]
    except ValueError as exc:
        raise argparse.ArgumentTypeError("整数列表参数包含非法值。") from exc


def _parse_float_list(value: str) -> List[float]:
    """解析浮点数列表参数。"""
    items = [item.strip() for item in value.split(",") if item.strip()]
    if not items:
        raise argparse.ArgumentTypeError("浮点数列表参数不能为空。")
    try:
        return [float(item) for item in items]
    except ValueError as exc:
        raise argparse.ArgumentTypeError("浮点数列表参数包含非法值。") from exc


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


def _best_result_key(item: Dict[str, object]) -> Tuple[float, float, float]:
    """生成最佳结果排序键。"""
    auc = float(item.get("auc", 0.0))
    tpr = float(item.get("tpr_at_recommended", 0.0))
    fpr = float(item.get("fpr_at_recommended", 1.0))
    return auc, tpr - fpr, tpr


def _build_parser() -> argparse.ArgumentParser:
    """构建命令行解析器。"""
    parser = argparse.ArgumentParser(description="CoBAn 参数扫描脚本")
    parser.add_argument("--run-name-prefix", type=str, default="coban_sweep", help="训练任务名前缀")
    parser.add_argument("--dataset-name", type=str, default="coban_sweep_dataset", help="数据集名称")
    parser.add_argument("--real-conf-dir", action="append", default=[], help="训练机密语料目录，可重复传入")
    parser.add_argument(
        "--real-non-conf-dir",
        action="append",
        default=[],
        help="训练非机密语料目录，可重复传入",
    )
    parser.add_argument("--disable-mock-train", action="store_true", help="禁用训练 mock 语料")
    parser.add_argument("--eval-conf-dir", action="append", default=[], help="评估机密语料目录，可重复传入")
    parser.add_argument(
        "--eval-non-conf-dir",
        action="append",
        default=[],
        help="评估非机密语料目录，可重复传入",
    )
    parser.add_argument("--disable-mock-eval", action="store_true", help="禁用评估 mock 语料")
    parser.add_argument(
        "--ngram-range",
        type=_parse_ngram_range,
        default=(1, 3),
        help="训练与评估统一 ngram 范围，格式 min,max",
    )
    parser.add_argument(
        "--n-clusters-list",
        type=_parse_int_list,
        default=[3, 4, 5],
        help="聚类数列表，例如 3,4,5",
    )
    parser.add_argument(
        "--context-span-list",
        type=_parse_int_list,
        default=[15, 20, 25],
        help="上下文窗口列表，例如 15,20,25",
    )
    parser.add_argument(
        "--cluster-similarity-threshold-list",
        type=_parse_float_list,
        default=[0.03, 0.05, 0.08],
        help="簇相似度阈值列表，例如 0.03,0.05,0.08",
    )
    parser.add_argument(
        "--irregular-ratio-threshold-list",
        type=_parse_float_list,
        default=[10.0, 20.0, 30.0],
        help="irregular 比值阈值列表，例如 10,20,30",
    )
    parser.add_argument("--random-state", type=int, default=42, help="随机种子")
    parser.add_argument("--max-iter", type=int, default=300, help="聚类最大迭代次数")
    parser.add_argument("--top-k-conf-terms", type=int, default=120, help="每簇机密术语上限")
    parser.add_argument("--top-k-context-terms", type=int, default=30, help="每术语上下文上限")
    parser.add_argument("--min-edge-weight", type=float, default=0.0, help="图边最小权重")
    parser.add_argument("--top-k-clusters", type=int, default=3, help="评估阶段 TopK cluster")
    parser.add_argument("--artifact-dir", type=str, default=None, help="模型产物目录")
    parser.add_argument("--output-json", type=str, default=None, help="参数扫描结果输出路径")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    """参数扫描脚本主函数。"""
    parser = _build_parser()
    args = parser.parse_args(argv)

    eval_docs = load_eval_documents(
        conf_dirs=args.eval_conf_dir,
        non_conf_dirs=args.eval_non_conf_dir,
        ngram_range=args.ngram_range,
        use_mock=not args.disable_mock_eval,
    )
    if not eval_docs:
        raise ValueError("参数扫描失败：未加载到评估样本。")

    all_results: List[Dict[str, object]] = []
    grid_items = itertools.product(
        args.n_clusters_list,
        args.context_span_list,
        args.cluster_similarity_threshold_list,
        args.irregular_ratio_threshold_list,
    )
    for idx, (n_clusters, context_span, cluster_sim_threshold, irregular_threshold) in enumerate(
        grid_items,
        start=1,
    ):
        run_name = f"{args.run_name_prefix}_{idx:03d}"
        request = CobanTrainingRequest(
            run_name=run_name,
            dataset_name=args.dataset_name,
            source_type="mixed",
            real_confidential_dirs=args.real_conf_dir,
            real_non_confidential_dirs=args.real_non_conf_dir,
            use_mock=not args.disable_mock_train,
            stopwords_path=None,
            ngram_range=args.ngram_range,
            n_clusters=max(1, int(n_clusters)),
            random_state=int(args.random_state),
            max_iter=max(50, int(args.max_iter)),
            context_span=max(1, int(context_span)),
            top_k_conf_terms=max(10, int(args.top_k_conf_terms)),
            top_k_context_terms=max(5, int(args.top_k_context_terms)),
            min_edge_weight=max(0.0, float(args.min_edge_weight)),
            cluster_similarity_threshold=max(0.0, float(cluster_sim_threshold)),
            detection_threshold=0.8,
            artifact_dir=args.artifact_dir,
        )
        train_result = train_coban_model(request=request)
        model_payload = load_model_payload(run_id=None, model_path=train_result.model_artifact_path)
        eval_report = evaluate_model(
            model_payload=model_payload,
            docs=eval_docs,
            top_k_clusters=max(1, int(args.top_k_clusters)),
            cluster_similarity_threshold=float(cluster_sim_threshold),
            irregular_ratio_threshold=max(1.0, float(irregular_threshold)),
        )
        row = {
            "run_id": train_result.run_id,
            "run_name": run_name,
            "params": {
                "ngram_range": list(args.ngram_range),
                "n_clusters": int(n_clusters),
                "context_span": int(context_span),
                "cluster_similarity_threshold": float(cluster_sim_threshold),
                "irregular_ratio_threshold": float(irregular_threshold),
                "top_k_clusters": int(args.top_k_clusters),
            },
            **asdict(eval_report),
        }
        all_results.append(row)

    if not all_results:
        raise RuntimeError("参数扫描未产生任何结果。")
    best_result = sorted(all_results, key=_best_result_key, reverse=True)[0]
    payload = {
        "grid_size": len(all_results),
        "best_result": best_result,
        "all_results": all_results,
    }
    output = json.dumps(payload, ensure_ascii=False, indent=2)
    print(output)

    if args.output_json:
        output_path = Path(args.output_json).expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(output, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

