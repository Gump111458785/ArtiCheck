from __future__ import annotations

import math


def reward(findings: list[dict], labels: dict[str, int], tool_calls=0, tokens=0,
           false_accusation_penalty=2.0, call_cost=.02, token_cost=.000001):
    if len({f["claim_id"] for f in findings}) != len(findings):
        raise ValueError("Duplicate findings")
    if {f["claim_id"] for f in findings} != set(labels) or any(v not in (0, 1) for v in labels.values()):
        raise ValueError("Rewards require complete, separate ground-truth labels")
    if min(tool_calls, tokens, false_accusation_penalty, call_cost, token_cost) < 0:
        raise ValueError("Negative reward costs")
    score = 0.0
    for finding in findings:
        label, verdict = labels[finding["claim_id"]], finding["verdict"]
        if verdict == "issue":
            score += 1 if label else -false_accusation_penalty
        elif verdict == "supported":
            score += -.5 if label else .25
        elif verdict == "inconclusive":
            score -= .1
        else:
            raise ValueError("Invalid verdict")
    return score / max(1, len(findings)) - tool_calls*call_cost - tokens*token_cost


def dynamic_groups(groups: list[list[dict]]):
    """DAPO-inspired filter; caller must resample to fill the training batch."""
    return [g for g in groups if len(g) >= 2 and len({r["reward"] for r in g}) > 1]


def curriculum(rows: list[dict], stage: int):
    if stage not in (1, 2, 3):
        raise ValueError("Curriculum stage must be 1, 2 or 3")
    return [r for r in rows if r.get("difficulty", 1) <= stage]


def clipped_importance_weight(train_logprob, behavior_logprob, cap=2.0):
    if cap <= 0 or not all(math.isfinite(x) for x in (train_logprob, behavior_logprob, cap)):
        raise ValueError("Invalid importance inputs")
    return math.exp(min(train_logprob-behavior_logprob, math.log(cap)))


def grpo_loss(new_logprobs, old_logprobs, advantages, mask, behavior_logprobs=None,
              clip_low=.2, clip_high=.28, importance_cap=2.0):
    """Token-level clipped objective with detached truncated IS correction.

    Shapes: [batch,tokens]; advantages [batch] or [batch,tokens]. This utility
    does not replace verl's distributed trainer or implement full DAPO.
    """
    import torch
    if clip_low < 0 or clip_high < 0 or importance_cap <= 0:
        raise ValueError("Invalid clipping parameters")
    if not (new_logprobs.shape == old_logprobs.shape == mask.shape):
        raise ValueError("Log-prob and mask shapes must match")
    if advantages.ndim == 1:
        advantages = advantages[:, None]
    ratio = torch.exp((new_logprobs-old_logprobs.detach()).clamp(-20, 20))
    clipped = ratio.clamp(1-clip_low, 1+clip_high)
    loss = -torch.minimum(ratio*advantages.detach(), clipped*advantages.detach())
    if behavior_logprobs is not None:
        if behavior_logprobs.shape != old_logprobs.shape:
            raise ValueError("Behavior log-prob shape mismatch")
        weights = torch.exp((old_logprobs.detach()-behavior_logprobs.detach()).clamp(max=math.log(importance_cap)))
        loss = loss * weights
    return (loss*mask).sum() / mask.sum().clamp(min=1)
