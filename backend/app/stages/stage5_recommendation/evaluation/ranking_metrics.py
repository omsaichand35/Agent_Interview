"""Ranking and shortlist evaluation metrics for candidate resume ranking.

Implements standard Information Retrieval (IR) and ranking metrics:
- Precision@K
- Recall@K
- DCG@K and NDCG@K
- Spearman rank correlation
- Kendall tau rank correlation
- Mean Reciprocal Rank (MRR)
"""

import math
from typing import Sequence, Union


def precision_at_k(
    predicted_ranked_ids: Sequence[str],
    ground_truth_relevant_ids: Union[set[str], Sequence[str]],
    k: int = 10,
) -> float:
    """Calculate Precision@K: proportion of top-K predicted candidates that are relevant.

    Args:
        predicted_ranked_ids: List of candidate IDs ranked by prediction score descending.
        ground_truth_relevant_ids: Set or list of candidate IDs considered suitable/relevant by human reference.
        k: Cutoff rank (e.g., 5, 10).

    Returns:
        Precision@K as a float between 0.0 and 1.0.
    """
    if k <= 0 or not predicted_ranked_ids:
        return 0.0

    relevant_set = set(ground_truth_relevant_ids)
    top_k = list(predicted_ranked_ids[:k])
    actual_k = len(top_k)
    if actual_k == 0:
        return 0.0

    hits = sum(1 for cid in top_k if cid in relevant_set)
    return round(hits / actual_k, 4)


def recall_at_k(
    predicted_ranked_ids: Sequence[str],
    ground_truth_relevant_ids: Union[set[str], Sequence[str]],
    k: int = 10,
) -> float:
    """Calculate Recall@K: proportion of total relevant candidates captured in the top-K.

    Args:
        predicted_ranked_ids: List of candidate IDs ranked by prediction score descending.
        ground_truth_relevant_ids: Set or list of candidate IDs considered suitable/relevant by human reference.
        k: Cutoff rank.

    Returns:
        Recall@K as a float between 0.0 and 1.0.
    """
    if k <= 0 or not predicted_ranked_ids:
        return 0.0

    relevant_set = set(ground_truth_relevant_ids)
    total_relevant = len(relevant_set)
    if total_relevant == 0:
        return 0.0

    top_k = list(predicted_ranked_ids[:k])
    hits = sum(1 for cid in top_k if cid in relevant_set)
    return round(hits / total_relevant, 4)


def dcg_at_k(relevance_scores: Sequence[float], k: int = 10) -> float:
    """Discounted Cumulative Gain at rank K using exponential relevance weighting.

    DCG@K = sum_{i=1}^K (2^{rel_i} - 1) / log2(i + 1)
    """
    if k <= 0:
        return 0.0
    dcg = 0.0
    for i, rel in enumerate(relevance_scores[:k]):
        # i is 0-indexed, rank is (i + 1)
        rank = i + 1
        gain = (2.0 ** float(rel)) - 1.0
        discount = math.log2(rank + 1)
        dcg += gain / discount
    return dcg


def ndcg_at_k(
    predicted_ranked_ids: Sequence[str],
    ground_truth_relevance: dict[str, float],
    k: int = 10,
) -> float:
    """Calculate Normalized Discounted Cumulative Gain (NDCG@K).

    Args:
        predicted_ranked_ids: Candidate IDs in order of predicted rank.
        ground_truth_relevance: Mapping of candidate_id -> human relevance rating (e.g., 1-5).
        k: Cutoff rank.

    Returns:
        NDCG@K value between 0.0 and 1.0.
    """
    if k <= 0 or not predicted_ranked_ids or not ground_truth_relevance:
        return 0.0

    # Predicted relevance sequence
    pred_relevances = [
        float(ground_truth_relevance.get(cid, 0.0))
        for cid in predicted_ranked_ids[:k]
    ]
    dcg = dcg_at_k(pred_relevances, k=k)

    # Ideal relevance sequence: sort all available ground truth relevance scores descending
    all_relevances = sorted(
        [float(r) for r in ground_truth_relevance.values()],
        reverse=True,
    )
    idcg = dcg_at_k(all_relevances, k=k)

    if idcg <= 0.0:
        return 0.0

    return round(min(1.0, dcg / idcg), 4)


def _compute_fractional_ranks(values: Sequence[float]) -> list[float]:
    """Compute average/fractional ranks for ties (1-based ranking)."""
    n = len(values)
    # Sort indices by value
    sorted_indices = sorted(range(n), key=lambda i: values[i])
    ranks = [0.0] * n

    i = 0
    while i < n:
        j = i
        while j + 1 < n and values[sorted_indices[j + 1]] == values[sorted_indices[i]]:
            j += 1
        # Indices from i to j have tied values. Average rank:
        tied_rank = (i + 1 + j + 1) / 2.0
        for k_idx in range(i, j + 1):
            ranks[sorted_indices[k_idx]] = tied_rank
        i = j + 1
    return ranks


def spearman_correlation(
    predicted_scores: Sequence[float],
    true_scores: Sequence[float],
) -> float:
    """Calculate Spearman rank correlation coefficient between predictions and ground truth.

    Handles tied ranks via Pearson correlation of fractional ranks.
    Returns float in [-1.0, 1.0].
    """
    if len(predicted_scores) != len(true_scores) or len(predicted_scores) < 2:
        return 0.0

    pred_ranks = _compute_fractional_ranks(predicted_scores)
    true_ranks = _compute_fractional_ranks(true_scores)

    mean_p = sum(pred_ranks) / len(pred_ranks)
    mean_t = sum(true_ranks) / len(true_ranks)

    cov = sum((p - mean_p) * (t - mean_t) for p, t in zip(pred_ranks, true_ranks))
    var_p = sum((p - mean_p) ** 2 for p in pred_ranks)
    var_t = sum((t - mean_t) ** 2 for t in true_ranks)

    denom = math.sqrt(var_p * var_t)
    if denom == 0.0:
        return 0.0

    corr = cov / denom
    return round(max(-1.0, min(1.0, corr)), 4)


def kendall_rank_correlation(
    predicted_scores: Sequence[float],
    true_scores: Sequence[float],
) -> float:
    """Calculate Kendall's tau-b rank correlation between predictions and ground truth.

    Handles ties in both sets of rankings.
    Returns float in [-1.0, 1.0].
    """
    n = len(predicted_scores)
    if n != len(true_scores) or n < 2:
        return 0.0

    concordant = 0
    discordant = 0
    ties_p = 0
    ties_t = 0

    for i in range(n):
        for j in range(i + 1, n):
            cmp_p = (predicted_scores[i] > predicted_scores[j]) - (predicted_scores[i] < predicted_scores[j])
            cmp_t = (true_scores[i] > true_scores[j]) - (true_scores[i] < true_scores[j])

            if cmp_p == 0 and cmp_t == 0:
                continue
            elif cmp_p == 0:
                ties_p += 1
            elif cmp_t == 0:
                ties_t += 1
            elif cmp_p == cmp_t:
                concordant += 1
            else:
                discordant += 1

    denom = math.sqrt((concordant + discordant + ties_p) * (concordant + discordant + ties_t))
    if denom == 0.0:
        return 0.0

    tau = (concordant - discordant) / denom
    return round(max(-1.0, min(1.0, tau)), 4)


def mean_reciprocal_rank(
    predicted_ranked_ids: Sequence[str],
    ground_truth_relevant_ids: Union[set[str], Sequence[str]],
) -> float:
    """Calculate Mean Reciprocal Rank (MRR) for the first relevant candidate found."""
    relevant_set = set(ground_truth_relevant_ids)
    for rank, cid in enumerate(predicted_ranked_ids, start=1):
        if cid in relevant_set:
            return round(1.0 / rank, 4)
    return 0.0
