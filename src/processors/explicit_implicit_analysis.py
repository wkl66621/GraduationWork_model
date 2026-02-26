"""
显隐性关系分析核心计算模块。

基于论文中的信息熵、互信息、LR、PIC、Risk定义实现：
- LR(A -> S) = I(A; S) / H(S)
- Risk = LR * PIC
- RiskFinal = max_{Ci}(LR(Ci -> S) * PIC(Ci))
"""

from __future__ import annotations

import itertools
import math
import random
from collections import Counter
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


def _entropy(values: Sequence[str]) -> float:
    """计算离散序列的信息熵 H(X)。

    Args:
        values: 离散取值序列。

    Returns:
        float: 熵值（bit）。
    """
    total = len(values)
    if total == 0:
        return 0.0
    counter = Counter(values)
    result = 0.0
    for cnt in counter.values():
        p = cnt / total
        if p > 0:
            result -= p * math.log2(p)
    return result


def _mutual_information(x: Sequence[str], y: Sequence[str]) -> float:
    """计算两个离散变量的互信息 I(X;Y)。

    Args:
        x: 特征取值序列。
        y: 敏感属性取值序列。

    Returns:
        float: 互信息值（bit），下限截断为 0。

    Raises:
        ValueError: 输入长度不一致时抛出。
    """
    if len(x) != len(y):
        raise ValueError("互信息计算失败：输入长度不一致。")
    total = len(x)
    if total == 0:
        return 0.0
    cx = Counter(x)
    cy = Counter(y)
    cxy = Counter(zip(x, y))
    result = 0.0
    for (vx, vy), c in cxy.items():
        pxy = c / total
        px = cx[vx] / total
        py = cy[vy] / total
        if pxy > 0 and px > 0 and py > 0:
            result += pxy * math.log2(pxy / (px * py))
    return max(result, 0.0)


def _mutual_information_multi(features: Sequence[Tuple[str, ...]], y: Sequence[str]) -> float:
    """计算联合特征与敏感属性的互信息 I(C;S)。

    Args:
        features: 联合特征元组序列。
        y: 敏感属性取值序列。

    Returns:
        float: 联合互信息值（bit），下限截断为 0。

    Raises:
        ValueError: 输入长度不一致时抛出。
    """
    if len(features) != len(y):
        raise ValueError("联合互信息计算失败：输入长度不一致。")
    total = len(y)
    if total == 0:
        return 0.0
    c_features = Counter(features)
    c_y = Counter(y)
    c_joint = Counter(zip(features, y))
    result = 0.0
    for (feature_key, yv), c in c_joint.items():
        p_joint = c / total
        p_f = c_features[feature_key] / total
        p_y = c_y[yv] / total
        if p_joint > 0 and p_f > 0 and p_y > 0:
            result += p_joint * math.log2(p_joint / (p_f * p_y))
    return max(result, 0.0)


def _extract_valid_pairs(
    rows: Sequence[Dict[str, Optional[str]]],
    attrs: Sequence[str],
    sensitive_attr: str,
) -> Tuple[List[Tuple[str, ...]], List[str]]:
    """筛选可参与计算的完整样本对。

    Args:
        rows: 样本行集合。
        attrs: 候选特征属性编码序列。
        sensitive_attr: 敏感属性编码。

    Returns:
        Tuple[List[Tuple[str, ...]], List[str]]: 联合特征序列与敏感属性序列。
    """
    feature_values: List[Tuple[str, ...]] = []
    sensitive_values: List[str] = []
    for row in rows:
        sv = row.get(sensitive_attr)
        if sv is None or str(sv).strip() == "":
            continue
        values: List[str] = []
        valid = True
        for attr in attrs:
            av = row.get(attr)
            if av is None or str(av).strip() == "":
                valid = False
                break
            values.append(str(av))
        if not valid:
            continue
        feature_values.append(tuple(values))
        sensitive_values.append(str(sv))
    return feature_values, sensitive_values


def estimate_joint_pic(
    single_pics: Sequence[float],
    sampling_times: int = 200,
    random_seed: int = 42,
) -> float:
    """估计属性组合的联合 PIC。

    Args:
        single_pics: 单属性 PIC 列表。
        sampling_times: 在上下界区间采样次数。
        random_seed: 采样随机种子。

    Returns:
        float: 联合 PIC 估计值。
    """
    if not single_pics:
        return 0.0
    if len(single_pics) == 1:
        return max(0.0, min(1.0, single_pics[0]))

    lower = 1.0
    upper = 1.0
    for p in single_pics:
        cp = max(0.0, min(1.0, p))
        lower *= cp
        upper = min(upper, cp)
    if lower >= upper:
        return lower

    # 论文建议在上下界间采样近似联合PIC
    rnd = random.Random(random_seed)
    samples = [rnd.uniform(lower, upper) for _ in range(max(1, sampling_times))]
    return sum(samples) / len(samples)


def compute_explicit_implicit_scores(
    rows: Sequence[Dict[str, Optional[str]]],
    sensitive_attr: str,
    candidate_attrs: Sequence[str],
    pic_defaults: Optional[Dict[str, float]] = None,
    default_pic: float = 0.5,
    max_combination_size: int = 3,
    sampling_times: int = 200,
    theta: float = 0.2,
) -> dict:
    """计算候选属性组合到敏感属性的 LR/PIC/Risk。

    Args:
        rows: 样本集合，每行为属性值字典。
        sensitive_attr: 敏感属性编码。
        candidate_attrs: 候选属性编码列表。
        pic_defaults: 属性到 PIC 的默认映射。
        default_pic: 未配置属性的默认 PIC。
        max_combination_size: 最大组合阶数。
        sampling_times: 联合 PIC 采样次数。
        theta: 高风险阈值。

    Returns:
        dict: 含 `risk_final`、`top_results`、`all_results` 等字段的结果。

    Raises:
        ValueError: 输入为空、属性不合法或无法产生有效组合结果时抛出。
    """
    if not rows:
        raise ValueError("分析数据为空。")
    if not candidate_attrs:
        raise ValueError("候选属性为空。")
    if sensitive_attr in candidate_attrs:
        raise ValueError("敏感属性不能同时作为候选属性。")

    pic_map = pic_defaults or {}
    max_size = max(1, min(max_combination_size, len(candidate_attrs)))

    # H(S) 在所有候选组合上保持一致，单独计算一次
    base_features, base_sensitive = _extract_valid_pairs(rows, [candidate_attrs[0]], sensitive_attr)
    if not base_sensitive:
        raise ValueError("没有可用于计算的有效样本，请检查敏感属性是否有值。")
    hs = _entropy(base_sensitive)
    if hs <= 0:
        raise ValueError("敏感属性熵为0，无法计算LR（敏感属性可能常量化）。")

    combo_results: List[dict] = []
    for size in range(1, max_size + 1):
        for combo in itertools.combinations(candidate_attrs, size):
            feature_values, sensitive_values = _extract_valid_pairs(rows, list(combo), sensitive_attr)
            if not sensitive_values:
                continue

            if len(combo) == 1:
                mi = _mutual_information(
                    [fv[0] for fv in feature_values],
                    sensitive_values,
                )
            else:
                mi = _mutual_information_multi(feature_values, sensitive_values)

            lr = mi / hs if hs > 0 else 0.0
            single_pics = [
                float(pic_map.get(attr, default_pic))
                for attr in combo
            ]
            pic = estimate_joint_pic(
                single_pics=single_pics,
                sampling_times=sampling_times,
                random_seed=42 + size + len(combo_results),
            )
            risk = lr * pic

            combo_results.append(
                {
                    "combo_attrs": list(combo),
                    "sample_size": len(sensitive_values),
                    "entropy_sensitive": hs,
                    "mutual_information": mi,
                    "lr": lr,
                    "pic": pic,
                    "risk": risk,
                }
            )

    if not combo_results:
        raise ValueError("未产生有效组合结果，请检查样本完整性。")

    risk_final = max(item["risk"] for item in combo_results)
    top_results = sorted(combo_results, key=lambda x: x["risk"], reverse=True)
    return {
        "sensitive_attr": sensitive_attr,
        "theta": theta,
        "risk_final": risk_final,
        "is_high_risk": risk_final > theta,
        "top_results": top_results[:10],
        "all_results": top_results,
    }
