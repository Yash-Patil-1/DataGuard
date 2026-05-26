"""
DataGuard — Historical Report Tracking

Stores quality scores over time in a local SQLite database so the
dashboard can display score trends, track regressions, and alert
on quality degradation.

Usage:
    from src.history import save_to_history, load_history

    # After running pipeline
    save_to_history(report.to_dict())

    # For dashboard
    history = load_history(days=30)
"""

import os
import sqlite3
import json
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any

DB_FILENAME = "quality_timeline.db"
TABLE_NAME = "quality_snapshots"


def _get_db_path() -> str:
    """Get the path to the history database (in the project root)."""
    # Resolve relative to this file's location (src/history.py -> project root)
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), DB_FILENAME)


def _init_db():
    """Ensure the database and table exist."""
    db_path = _get_db_path()
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                overall_score REAL NOT NULL,
                status TEXT NOT NULL,
                dimension_scores TEXT NOT NULL,
                num_checks INTEGER NOT NULL,
                num_passed INTEGER NOT NULL,
                num_failed INTEGER NOT NULL,
                run_type TEXT DEFAULT 'full'
            )
        """)
        conn.commit()
    finally:
        conn.close()


def save_to_history(report: dict, run_type: str = "full"):
    """
    Save a quality report to the historical database.

    Args:
        report: Quality report dict (from QualityReport.to_dict())
        run_type: 'full', 'validate_only', 'detect_only', etc.
    """
    _init_db()
    db_path = _get_db_path()

    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            f"""
            INSERT INTO {TABLE_NAME}
                (timestamp, overall_score, status, dimension_scores,
                 num_checks, num_passed, num_failed, run_type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                report.get("timestamp", datetime.now().isoformat()),
                float(report.get("overall_score", 0.0)),
                str(report.get("status", "unknown")),
                json.dumps(report.get("dimension_scores", {})),
                int(report.get("num_checks", 0)),
                int(report.get("num_passed", 0)),
                int(report.get("num_failed", 0)),
                run_type,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def load_history(days: int = 30, limit: int = 100) -> List[Dict[str, Any]]:
    """
    Load historical quality snapshots.

    Args:
        days: Number of days of history to load
        limit: Maximum number of records to return

    Returns:
        List of dicts with timestamp, overall_score, status, dimension_scores, etc.
    """
    _init_db()
    db_path = _get_db_path()

    if not os.path.exists(db_path):
        return []

    cutoff = (datetime.now() - timedelta(days=days)).isoformat()

    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.execute(
            f"""
            SELECT timestamp, overall_score, status, dimension_scores,
                   num_checks, num_passed, num_failed, run_type
            FROM {TABLE_NAME}
            WHERE timestamp >= ?
            ORDER BY timestamp ASC
            LIMIT ?
            """,
            (cutoff, limit),
        )
        rows = []
        for row in cursor.fetchall():
            rows.append({
                "timestamp": row[0],
                "overall_score": row[1],
                "status": row[2],
                "dimension_scores": json.loads(row[3]) if row[3] else {},
                "num_checks": row[4],
                "num_passed": row[5],
                "num_failed": row[6],
                "run_type": row[7],
            })
        return rows
    finally:
        conn.close()


def get_latest_score() -> Optional[Dict[str, Any]]:
    """Get the most recent quality score entry."""
    _init_db()
    db_path = _get_db_path()

    if not os.path.exists(db_path):
        return None

    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.execute(
            f"""
            SELECT timestamp, overall_score, status, dimension_scores,
                   num_checks, num_passed, num_failed, run_type
            FROM {TABLE_NAME}
            ORDER BY timestamp DESC
            LIMIT 1
            """
        )
        row = cursor.fetchone()
        if row:
            return {
                "timestamp": row[0],
                "overall_score": row[1],
                "status": row[2],
                "dimension_scores": json.loads(row[3]) if row[3] else {},
                "num_checks": row[4],
                "num_passed": row[5],
                "num_failed": row[6],
                "run_type": row[7],
            }
        return None
    finally:
        conn.close()


def get_score_summary(days: int = 30) -> Dict[str, Any]:
    """
    Get a summary of quality score trends.

    Returns:
        dict with current, min, max, avg, trend (up/down/stable)
    """
    history = load_history(days=days)
    if not history:
        return {"current": None, "min": None, "max": None, "avg": None, "trend": "unknown"}

    scores = [h["overall_score"] for h in history]
    current = scores[-1]
    avg = sum(scores) / len(scores)

    # Simple trend: compare first half vs second half
    mid = len(scores) // 2
    if mid >= 1:
        first_half = sum(scores[:mid]) / mid
        second_half = sum(scores[mid:]) / (len(scores) - mid)
        diff = second_half - first_half
        if diff > 0.02:
            trend = "improving"
        elif diff < -0.02:
            trend = "degrading"
        else:
            trend = "stable"
    else:
        trend = "stable"

    return {
        "current": round(current * 100, 1),
        "min": round(min(scores) * 100, 1),
        "max": round(max(scores) * 100, 1),
        "avg": round(avg * 100, 1),
        "trend": trend,
        "count": len(scores),
    }


def auto_save_report(report: dict, output_dir: str = None) -> dict:
    """
    Convenience function: save report to JSON + TXT + history DB.

    Args:
        report: Quality report dict
        output_dir: Directory for JSON/TXT reports (optional)

    Returns:
        dict with paths and history status
    """
    from src.utils import save_report

    result = {"history_saved": False}

    # Save to SQLite history
    try:
        save_to_history(report)
        result["history_saved"] = True
    except Exception as e:
        print(f"  Warning: Could not save to history: {e}")

    # Save JSON/TXT if output_dir provided
    if output_dir:
        try:
            paths = save_report(report, output_dir)
            result["paths"] = paths
        except Exception as e:
            print(f"  Warning: Could not save report files: {e}")

    return result


# Quick test
if __name__ == "__main__":
    print("=" * 60)
    print("  DataGuard — History Tracker")
    print("=" * 60)

    # Test saving a sample report
    sample_report = {
        "dataset": "test",
        "timestamp": datetime.now().isoformat(),
        "overall_score": 0.75,
        "status": "warning",
        "dimension_scores": {"completeness": 0.8, "validity": 0.7},
        "num_checks": 10,
        "num_passed": 7,
        "num_failed": 3,
    }

    save_to_history(sample_report)
    print("\n  ✓ Sample report saved to history")

    history = load_history(days=30)
    print(f"  ✓ Loaded {len(history)} history entries")

    summary = get_score_summary()
    print(f"  ✓ Current: {summary['current']}% | Trend: {summary['trend']}")
    print(f"    Min: {summary['min']}% | Max: {summary['max']}% | Avg: {summary['avg']}%")

    print("\n" + "=" * 60)
