"""
EEG Artifact Submission Grader

Scores one team CSV against the hardcoded answer key.
Submission rows are matched to answer-key rows by best IoU — order does not matter.

Usage:
    python submission_check.py path/to/group-id_group-name.csv
    python submission_check.py path/to/group-id_group-name.csv --rows rows.csv --summary summary.csv
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
from statistics import mean

# ============================================================
# ANSWER KEY
# Edit these rows to match the official workshop annotations.
# ============================================================

ANSWER_KEY = [
    {
        "artifact_category": "micro_event",
        "artifact_class":    "ver_eyem",
        "start_time":        1.25,
        "end_time":          1.60,
    },
    {
        "artifact_category": "medium_task_block",
        "artifact_class":    "swallow",
        "start_time":        8.20,
        "end_time":          10.10,
    },
    {
        "artifact_category": "long_task_block",
        "artifact_class":    "chew",
        "start_time":        18.00,
        "end_time":          27.50,
    },
    {
        "artifact_category": "macroscopic_state",
        "artifact_class":    "close_base",
        "start_time":        40.00,
        "end_time":          105.00,
    },
]

# ============================================================
# CATEGORY RULES
# onset_tolerance  — max allowed |pred_start - true_start| in seconds
# offset_tolerance — max allowed |pred_end   - true_end|   in seconds
# ============================================================

CATEGORY_RULES = {
    "micro_event": {
        "classes":           ["ver_eyem"],
        "onset_tolerance":   0.20,   # ± 200 ms
        "offset_tolerance":  0.30,   # ± 300 ms
    },
    "medium_task_block": {
        "classes":           ["tongue", "swallow"],
        "onset_tolerance":   0.50,   # ± 500 ms
        "offset_tolerance":  1.00,   # ± 1000 ms
    },
    "long_task_block": {
        "classes":           ["hor_headm", "ver_headm", "eyebrow", "chew"],
        "onset_tolerance":   1.50,   # ± 1.5 s
        "offset_tolerance":  2.00,   # ± 2.0 s
    },
    "macroscopic_state": {
        "classes":           ["blink", "close_base", "open_base"],
        "onset_tolerance":   3.00,   # ± 3.0 s
        "offset_tolerance":  3.00,   # ± 3.0 s
    },
}

# ============================================================
# POINT WEIGHTS
# Change these values to adjust competition scoring.
# ============================================================

MAX_INTERVAL_POINTS = 10.0   # Scales with IoU once timing passes

CATEGORY_POINTS = {
    "micro_event":       5.0,
    "medium_task_block": 8.0,
    "long_task_block":  10.0,
    "macroscopic_state": 6.0,
}

CLASS_POINTS = {
    "ver_eyem":   5.0,
    "tongue":     8.0,
    "swallow":   10.0,
    "hor_headm": 10.0,
    "ver_headm": 10.0,
    "eyebrow":    9.0,
    "chew":      10.0,
    "blink":      6.0,
    "close_base": 6.0,
    "open_base":  6.0,
}

# ============================================================
# REQUIRED COLUMNS (do not change unless the spec changes)
# ============================================================

REQUIRED_COLUMNS = ["artifact_category", "artifact_class", "start_time", "end_time"]


# ────────────────────────────────────────────────────────────
# I/O helpers
# ────────────────────────────────────────────────────────────

def _norm(name: str) -> str:
    """Normalize a column header to lowercase_with_underscores."""
    return name.strip().lower().replace(" ", "_")


def read_submission(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            return []

        col_map = {_norm(h): h for h in reader.fieldnames}
        missing = [c for c in REQUIRED_COLUMNS if c not in col_map]
        if missing:
            raise ValueError(f"Missing required column(s): {', '.join(missing)}")

        rows = []
        for raw in reader:
            rows.append({c: raw[col_map[c]].strip() for c in REQUIRED_COLUMNS})
        return rows


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


# ────────────────────────────────────────────────────────────
# Scoring helpers
# ────────────────────────────────────────────────────────────

def iou(p_start: float, p_end: float, t_start: float, t_end: float) -> float:
    intersection = max(0.0, min(p_end, t_end) - max(p_start, t_start))
    union = max(p_end, t_end) - min(p_start, t_start)
    return intersection / union if union > 0 else 0.0


def is_blank(row: dict[str, str] | None) -> bool:
    return row is None or all(row.get(c, "").strip() == "" for c in REQUIRED_COLUMNS)


def parse_times(row: dict[str, str]) -> tuple[bool, str, float, float]:
    """
    Parse and validate start/end times from a submission row.
    Returns (is_valid, status_tag, pred_start, pred_end).
    """
    try:
        p_start = float(row["start_time"])
        p_end   = float(row["end_time"])
    except ValueError:
        return False, "non_numeric_time", 0.0, 0.0

    if p_end <= p_start:
        return False, "end_not_after_start", p_start, p_end

    return True, "ok", p_start, p_end


# ────────────────────────────────────────────────────────────
# IoU-based matching
# ────────────────────────────────────────────────────────────

def match_predictions(submission: list[dict[str, str]]) -> dict[int, tuple[dict[str, str], float]]:
    """
    Match each valid submission row to its best-IoU answer-key row.
    Each submission row and each answer-key row is used at most once.
    Higher-IoU pairs are assigned before lower-IoU pairs.

    Returns a dict mapping answer_key_index -> (matched submission row, iou_score).
    """
    # Collect all valid submission rows with their parsed times
    valid_preds: list[tuple[int, dict[str, str], float, float]] = []
    for sub_idx, row in enumerate(submission):
        if is_blank(row):
            continue
        is_valid, _, p_start, p_end = parse_times(row)
        if is_valid:
            valid_preds.append((sub_idx, row, p_start, p_end))

    # Build all (iou_score, answer_key_index, pred_entry) candidates
    candidates: list[tuple[float, int, tuple]] = []
    for key_idx, truth in enumerate(ANSWER_KEY):
        t_start = float(truth["start_time"])
        t_end   = float(truth["end_time"])
        for sub_idx, row, p_start, p_end in valid_preds:
            score = iou(p_start, p_end, t_start, t_end)
            if score > 0:
                candidates.append((score, key_idx, (sub_idx, row)))

    # Greedy assignment: best IoU first, each side used at most once
    candidates.sort(key=lambda x: x[0], reverse=True)
    matched_keys: set[int] = set()
    matched_subs: set[int] = set()
    assignments: dict[int, tuple[dict[str, str], float]] = {}

    for score, key_idx, (sub_idx, row) in candidates:
        if key_idx in matched_keys or sub_idx in matched_subs:
            continue
        assignments[key_idx] = (row, score)
        matched_keys.add(key_idx)
        matched_subs.add(sub_idx)

    return assignments


# ────────────────────────────────────────────────────────────
# Row scoring
# ────────────────────────────────────────────────────────────

def score_row(row_number: int, truth: dict, pred: dict[str, str] | None, overlap: float) -> dict:
    result = {
        "row_id":            row_number,
        "points_earned":     0.0,
        "interval_accuracy": 0.0,
        "category_accuracy": 0,
        "artifact_accuracy": 0,
        "status":            "unmatched",
    }

    if pred is None:
        return result

    t_cat   = truth["artifact_category"]
    t_class = truth["artifact_class"]
    rules   = CATEGORY_RULES[t_cat]

    is_valid, status, p_start, p_end = parse_times(pred)
    result["status"] = status
    if not is_valid:
        return result

    cat_correct   = pred["artifact_category"] == t_cat
    class_correct = pred["artifact_class"]    == t_class

    # Accuracy is recorded regardless of timing tolerance
    result["category_accuracy"] = int(cat_correct)
    result["artifact_accuracy"] = int(class_correct)

    # Timing tolerance check using truth row's tolerances
    t_start   = float(truth["start_time"])
    t_end     = float(truth["end_time"])
    onset_ok  = abs(p_start - t_start) <= rules["onset_tolerance"]
    offset_ok = abs(p_end   - t_end)   <= rules["offset_tolerance"]

    if not (onset_ok and offset_ok):
        result["status"] = "interval_outside_tolerance"
        return result

    # Timing passed — compute points using the already-computed IoU
    interval_pts = MAX_INTERVAL_POINTS * overlap
    category_pts = CATEGORY_POINTS.get(t_cat, 0.0)   if cat_correct   else 0.0
    class_pts    = CLASS_POINTS.get(t_class, 0.0)     if class_correct else 0.0

    result["points_earned"]     = round(interval_pts + category_pts + class_pts, 2)
    result["interval_accuracy"] = round(overlap, 4)
    result["status"]            = status
    return result


# ────────────────────────────────────────────────────────────
# Submission scoring
# ────────────────────────────────────────────────────────────

def score_submission(path: Path) -> tuple[list[dict], dict]:
    submission  = read_submission(path)
    assignments = match_predictions(submission)

    row_results = []
    for key_idx, truth in enumerate(ANSWER_KEY):
        matched = assignments.get(key_idx)
        pred, overlap = matched if matched else (None, 0.0)
        row_results.append(score_row(key_idx + 1, truth, pred, overlap))

    summary = build_summary(row_results, path)
    return row_results, summary


def build_summary(rows: list[dict], path: Path) -> dict:
    stem = path.stem
    group_id, _, group_name = stem.partition("_")

    interval_acc = mean(r["interval_accuracy"] for r in rows) if rows else 0.0
    category_acc = mean(r["category_accuracy"] for r in rows) if rows else 0.0
    artifact_acc = mean(r["artifact_accuracy"] for r in rows) if rows else 0.0
    general_acc  = mean([interval_acc, category_acc, artifact_acc])

    return {
        "team_file":         path.name,
        "group_id":          group_id,
        "group_name":        group_name,
        "total_points":      round(sum(r["points_earned"] for r in rows), 2),
        "interval_accuracy": round(interval_acc, 4),
        "category_accuracy": round(category_acc, 4),
        "artifact_accuracy": round(artifact_acc, 4),
        "general_accuracy":  round(general_acc,  4),
    }


# ────────────────────────────────────────────────────────────
# Output formatting
# ────────────────────────────────────────────────────────────

def format_row_report(rows: list[dict]) -> list[dict]:
    return [
        {
            "Point":             r["points_earned"],
            "Interval Accuracy": r["interval_accuracy"],
            "Category Accuracy": r["category_accuracy"],
            "Artifact Accuracy": r["artifact_accuracy"],
        }
        for r in rows
    ]


def format_summary(summary: dict) -> dict:
    return {
        "Total Points":      summary["total_points"],
        "Interval Accuracy": summary["interval_accuracy"],
        "Category Accuracy": summary["category_accuracy"],
        "Artifact Accuracy": summary["artifact_accuracy"],
        "General Accuracy":  summary["general_accuracy"],
    }


def print_summary(summary: dict) -> None:
    print("\nSubmission summary")
    print(f"  Team file          : {summary['team_file']}")
    print(f"  Group ID           : {summary['group_id']}")
    print(f"  Group name         : {summary['group_name']}")
    print(f"  Total points       : {summary['total_points']}")
    print(f"  Interval accuracy  : {summary['interval_accuracy']:.4f}")
    print(f"  Category accuracy  : {summary['category_accuracy']:.4f}")
    print(f"  Artifact accuracy  : {summary['artifact_accuracy']:.4f}")
    print(f"  General accuracy   : {summary['general_accuracy']:.4f}")


# ────────────────────────────────────────────────────────────
# CLI
# ────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Score an EEG artifact submission CSV.")
    parser.add_argument("submission", type=Path, help="Team CSV (group-id_group-name.csv)")
    parser.add_argument("--rows",    type=Path, help="Row-level output CSV")
    parser.add_argument("--summary", type=Path, help="Team summary output CSV")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    base = Path("results") / args.submission.stem

    Path("results").mkdir(exist_ok=True)

    rows_path    = args.rows    or Path(f"{base}_rows.csv")
    summary_path = args.summary or Path(f"{base}_summary.csv")

    row_results, summary = score_submission(args.submission)

    write_csv(rows_path,    format_row_report(row_results))
    write_csv(summary_path, [format_summary(summary)])
    print_summary(summary)
    print(f"\nRow report   → {rows_path}")
    print(f"Team summary → {summary_path}")


if __name__ == "__main__":
    main()