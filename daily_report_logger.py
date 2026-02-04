"""
Daily Report Logging System
Tracks: points completed, missing, and failure reasons
Keeps 7-day history for auditing
"""

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ========================================
# Configuration
# ========================================
LOG_DIR = Path.home() / ".water_meter_logs"
LOG_DIR.mkdir(exist_ok=True)

RETENTION_DAYS = 7

# Failure reasons (standardized)
FAIL_REASON = {
    "QUOTA_429": "Quota exceeded (429 error)",
    "SHEET_NOT_FOUND": "Sheet not found",
    "TIME_NOT_FOUND": "Time not found in data",
    "OCR_FAILED": "OCR failed",
    "NO_IMAGE": "No image available",
    "CONFIG_ERROR": "Configuration error",
    "NETWORK_ERROR": "Network error",
    "SKIP_NON_EMPTY": "Cell already has data (skip mode)",
    "UNKNOWN": "Unknown error",
}

# ========================================
# Logging Functions
# ========================================

def get_thai_time():
    """Get current time in Thailand (UTC+7)"""
    tz = timezone(timedelta(hours=7))
    return datetime.now(tz)


def get_today_log_file():
    """Get today's log file path"""
    today = get_thai_time().strftime("%Y-%m-%d")
    return LOG_DIR / f"{today}.json"


def get_log_entry_template():
    """Get empty log entry template"""
    return {
        "timestamp": None,
        "date": None,
        "total_points": 0,
        "success": [],
        "failed": {},  # {point_id: reason}
        "summary": {
            "completed": 0,
            "missing": 0,
            "by_reason": {}  # {reason: count}
        }
    }


def load_today_log():
    """Load today's log or create new"""
    log_file = get_today_log_file()
    if log_file.exists():
        try:
            with open(log_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return get_log_entry_template()
    return get_log_entry_template()


def save_log(log_data):
    """Save log data to file"""
    log_file = get_today_log_file()
    log_data["timestamp"] = get_thai_time().isoformat()
    log_data["date"] = get_thai_time().strftime("%Y-%m-%d")
    
    with open(log_file, "w", encoding="utf-8") as f:
        json.dump(log_data, f, ensure_ascii=False, indent=2)


def update_log_success(point_ids: list):
    """Record successful data entries"""
    log = load_today_log()
    
    for pid in point_ids:
        if pid not in log["success"]:
            log["success"].append(pid)
        if pid in log["failed"]:
            del log["failed"][pid]
    
    log["total_points"] = len(set(log["success"]) | set(log["failed"].keys()))
    log["summary"]["completed"] = len(log["success"])
    log["summary"]["missing"] = len(log["failed"])
    
    # Update reason counts
    log["summary"]["by_reason"] = {}
    for reason in log["failed"].values():
        reason_key = reason[:20]  # Truncate for grouping
        log["summary"]["by_reason"][reason_key] = log["summary"]["by_reason"].get(reason_key, 0) + 1
    
    save_log(log)


def update_log_failed(failures: list):
    """Record failed data entries
    
    Args:
        failures: list of (point_id, reason) tuples
    """
    log = load_today_log()
    
    for pid, reason in failures:
        if pid not in log["success"]:  # Don't override success
            # Standardize reason
            reason_key = None
            for key, desc in FAIL_REASON.items():
                if key in reason.upper():
                    reason_key = key
                    break
            
            log["failed"][pid] = reason if not reason_key else FAIL_REASON.get(reason_key, reason)
    
    log["total_points"] = len(set(log["success"]) | set(log["failed"].keys()))
    log["summary"]["completed"] = len(log["success"])
    log["summary"]["missing"] = len(log["failed"])
    
    # Update reason counts
    log["summary"]["by_reason"] = {}
    for reason in log["failed"].values():
        reason_key = reason[:30]
        log["summary"]["by_reason"][reason_key] = log["summary"]["by_reason"].get(reason_key, 0) + 1
    
    save_log(log)


def get_daily_summary():
    """Get today's summary: completed/missing/by_reason"""
    log = load_today_log()
    return {
        "date": log.get("date", ""),
        "completed": log["summary"]["completed"],
        "missing": log["summary"]["missing"],
        "total": log["total_points"],
        "by_reason": log["summary"]["by_reason"],
        "failed_points": log["failed"],
    }


def get_7day_history():
    """Get 7-day history"""
    today = get_thai_time().date()
    history = []
    
    for i in range(7):
        date = today - timedelta(days=i)
        log_file = LOG_DIR / f"{date.strftime('%Y-%m-%d')}.json"
        
        if log_file.exists():
            try:
                with open(log_file, "r", encoding="utf-8") as f:
                    log = json.load(f)
                    history.append({
                        "date": date.strftime("%Y-%m-%d"),
                        "completed": log["summary"]["completed"],
                        "missing": log["summary"]["missing"],
                        "total": log["total_points"],
                    })
            except:
                pass
    
    return history


def cleanup_old_logs():
    """Delete logs older than 7 days"""
    cutoff_date = get_thai_time().date() - timedelta(days=RETENTION_DAYS)
    
    for log_file in LOG_DIR.glob("*.json"):
        try:
            date_str = log_file.stem
            file_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            if file_date < cutoff_date:
                log_file.unlink()
        except:
            pass


def print_daily_report():
    """Print beautiful daily summary report"""
    summary = get_daily_summary()
    today = get_thai_time().strftime("%Y-%m-%d %H:%M:%S")
    
    report = f"""
╔═════════════════════════════════════════════════════════════════╗
║                    📊 DAILY REPORT SUMMARY                      ║
╚═════════════════════════════════════════════════════════════════╝

Date: {summary["date"]}
Time: {today}

📈 Statistics:
  ✅ Completed:  {summary["completed"]:3d} points
  ❌ Missing:    {summary["missing"]:3d} points
  ━━━━━━━━━━━━━━━━━━━━━━━
  📊 Total:      {summary["total"]:3d} points

Success Rate: {(summary["completed"] / max(summary["total"], 1) * 100):.1f}%

❌ Missing Breakdown:
"""
    
    if summary["by_reason"]:
        for reason, count in sorted(summary["by_reason"].items(), key=lambda x: -x[1]):
            report += f"  • {reason}: {count}\n"
    else:
        report += "  (None - All complete! 🎉)\n"
    
    if summary["failed_points"]:
        report += f"\n📋 Failed Points Details:\n"
        for pid, reason in sorted(summary["failed_points"].items())[:10]:
            report += f"  • {pid}: {reason}\n"
        if len(summary["failed_points"]) > 10:
            report += f"  ... and {len(summary['failed_points']) - 10} more\n"
    
    report += f"""
╔═════════════════════════════════════════════════════════════════╗
║                    📈 7-DAY TREND                               ║
╚═════════════════════════════════════════════════════════════════╝
"""
    
    history = get_7day_history()
    for day in history:
        bar_length = day["completed"] // max(1, (day["total"] // 20))
        bar = "█" * bar_length + "░" * (20 - bar_length)
        success_rate = (day["completed"] / max(day["total"], 1) * 100)
        report += f"  {day['date']}: [{bar}] {day['completed']}/{day['total']} ({success_rate:.0f}%)\n"
    
    report += f"""
╚═════════════════════════════════════════════════════════════════╝
"""
    
    return report


# ========================================
# Batch Update Error Handling
# ========================================

def _is_quota_error(err: Exception) -> bool:
    """Check if error is quota/rate limit"""
    msg = str(err).upper()
    return any(x in msg for x in ["429", "QUOTA", "RATE", "LIMIT"])


def _is_network_error(err: Exception) -> bool:
    """Check if error is network-related"""
    msg = str(err).upper()
    return any(x in msg for x in ["CONNECTION", "TIMEOUT", "NETWORK", "SOCKET"])


def categorize_error(err: Exception) -> str:
    """Categorize error into standard reason"""
    if _is_quota_error(err):
        return "QUOTA_429"
    elif _is_network_error(err):
        return "NETWORK_ERROR"
    elif "not found" in str(err).lower():
        return "SHEET_NOT_FOUND"
    else:
        return "UNKNOWN"


if __name__ == "__main__":
    # Test
    print("Log directory:", LOG_DIR)
    print("\nToday's log file:", get_today_log_file())
    print("\nLoading today's log...")
    log = load_today_log()
    print(f"  Current completed: {log['summary']['completed']}")
    print(f"  Current missing: {log['summary']['missing']}")
    
    print("\n" + print_daily_report())
    cleanup_old_logs()
    print("✅ Old logs cleaned up (>7 days)")
