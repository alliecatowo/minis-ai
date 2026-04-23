#!/usr/bin/env python3
import asyncio
import sys
import argparse
from pathlib import Path
from sqlalchemy import select
from typing import Any

# Add backend to path
_backend_dir = Path(__file__).parent.parent
if str(_backend_dir) not in sys.path:
    sys.path.insert(0, str(_backend_dir))

from app.db import async_session
from app.models.evidence import ReviewCycle
from app.models.mini import Mini

def _precision_recall_f1(
    expected_ids: set[str],
    predicted_ids: set[str],
) -> tuple[float, float, float]:
    """Compute strict agreement metrics with sane empty-set behavior.
    
    Match logic in eval/review.py
    """
    if not expected_ids and not predicted_ids:
        return 1.0, 1.0, 1.0
    if not expected_ids or not predicted_ids:
        # If expected is empty but predicted is not: Precision=0, Recall=1
        # If expected is not empty but predicted is: Precision=1, Recall=0
        if not expected_ids:
             return 0.0, 1.0, 0.0
        else:
             return 1.0, 0.0, 0.0

    true_positives = len(expected_ids & predicted_ids)
    precision = true_positives / len(predicted_ids)
    recall = true_positives / len(expected_ids)
    f1 = 0.0
    if precision + recall > 0:
        f1 = 2 * precision * recall / (precision + recall)
    return precision, recall, f1

def calculate_jaccard(list1: list[Any], list2: list[Any], key: str | None = None) -> float:
    """Calculate Jaccard similarity between two lists.
    If key is provided, extracts that field from dicts in the list.
    """
    if not list1 and not list2:
        return 1.0
    if not list1 or not list2:
        return 0.0
    
    def extract(item: Any) -> str:
        if key and isinstance(item, dict):
            return str(item.get(key, item)).lower().strip()
        return str(item).lower().strip()

    set1 = set(extract(i) for i in list1)
    set2 = set(extract(i) for i in list2)
    intersection = len(set1 & set2)
    union = len(set1 | set2)
    return intersection / union

def calculate_metrics(cycles: list[ReviewCycle]):
    if not cycles:
        return None
    
    total = len(cycles)
    approval_matches = 0
    blocker_precisions = []
    blocker_recalls = []
    comment_overlaps = []
    
    for cycle in cycles:
        pred = cycle.predicted_state or {}
        human = cycle.human_review_outcome or {}
        
        # 1. Approval State Accuracy
        pred_verdict = pred.get("expressed_feedback", {}).get("approval_state")
        human_verdict = human.get("expressed_feedback", {}).get("approval_state")
        if pred_verdict == human_verdict:
            approval_matches += 1
            
        # 2. Blocker Precision/Recall
        pred_blockers = pred.get("private_assessment", {}).get("blocking_issues", [])
        human_blockers = human.get("private_assessment", {}).get("blocking_issues", [])
        
        # Extract 'id' or use string value
        p_set = set(str(b.get("id") if isinstance(b, dict) else b).lower().strip() for b in pred_blockers)
        h_set = set(str(b.get("id") if isinstance(b, dict) else b).lower().strip() for b in human_blockers)
        
        prec, rec, _ = _precision_recall_f1(h_set, p_set)
        blocker_precisions.append(prec)
        blocker_recalls.append(rec)
            
        # 3. Comment Overlap (Jaccard on bodies)
        pred_comments = pred.get("expressed_feedback", {}).get("comments", [])
        human_comments = human.get("expressed_feedback", {}).get("comments", [])
        comment_overlaps.append(calculate_jaccard(pred_comments, human_comments, key="body"))
        
    return {
        "count": total,
        "approval_accuracy": approval_matches / total,
        "blocker_precision": sum(blocker_precisions) / len(blocker_precisions),
        "blocker_recall": sum(blocker_recalls) / len(blocker_recalls),
        "comment_overlap": sum(comment_overlaps) / len(comment_overlaps),
    }

async def main():
    parser = argparse.ArgumentParser(description="Calculate review agreement metrics from DB.")
    parser.add_argument("--mini", help="Filter by mini username")
    args = parser.parse_args()

    async with async_session() as session:
        # Query ReviewCycle records where human_review_outcome is present
        stmt = select(ReviewCycle).where(ReviewCycle.human_review_outcome.is_not(None))
        if args.mini:
            stmt = stmt.join(Mini).where(Mini.username == args.mini)
        
        result = await session.execute(stmt)
        cycles = result.scalars().all()
        
        # Group by mini_id
        by_mini = {}
        for c in cycles:
            by_mini.setdefault(c.mini_id, []).append(c)
            
        if not by_mini:
            print("No ReviewCycle records with human outcomes found.")
            return

        # Get mini names
        mini_stmt = select(Mini).where(Mini.id.in_(by_mini.keys()))
        mini_result = await session.execute(mini_stmt)
        minis = {m.id: m.username for m in mini_result.scalars().all()}
        
        results = []
        for mini_id, mini_cycles in by_mini.items():
            username = minis.get(mini_id, mini_id)
            metrics = calculate_metrics(mini_cycles)
            results.append((username, metrics))
            
        # Print Markdown Table
        print("\n## Review Agreement Scoring (Live Cycles)\n")
        print("| Mini | Cycles | Approval Acc | Blocker Prec | Blocker Rec | Comment Overlap |")
        print("| :--- | :---: | :---: | :---: | :---: | :---: |")
        for username, m in sorted(results, key=lambda x: x[0]):
            print(f"| {username} | {m['count']} | {m['approval_accuracy']:.2%} | {m['blocker_precision']:.2%} | {m['blocker_recall']:.2%} | {m['comment_overlap']:.2%} |")
        print()

if __name__ == "__main__":
    asyncio.run(main())
