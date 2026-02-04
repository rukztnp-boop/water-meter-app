"""
Simple Daily Logger for Water System
- Track success/failed points per day
- Auto-cleanup after 7 days
- Save to JSON in /tmp (fast)
"""

import json
import os
from datetime import datetime, timedelta, timezone

LOG_DIR = "/tmp/water_system_logs"
os.makedirs(LOG_DIR, exist_ok=True)

def _get_today():
    """Get today's date string (TH timezone)"""
    tz = timezone(timedelta(hours=7))
    return datetime.now(tz).strftime("%Y-%m-%d")

def _get_log_file():
    """Get today's log file path"""
    return os.path.join(LOG_DIR, f"daily_{_get_today()}.json")

def _load_or_create_log():
    """Load today's log or create new"""
    log_file = _get_log_file()
    if os.path.exists(log_file):
        try:
            with open(log_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return {"success": [], "failed": {}, "timestamp": datetime.now(timezone(timedelta(hours=7))).isoformat()}
    
    return {
        "date": _get_today(),
        "success": [],
        "failed": {},  # {point_id: error_reason}
        "timestamp": datetime.now(timezone(timedelta(hours=7))).isoformat()
    }

def _save_log(data):
    """Save log to file"""
    try:
        log_file = _get_log_file()
        with open(log_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"❌ Error saving log: {e}")

def log_success(point_ids):
    """Log successful uploads"""
    if not point_ids:
        return
    
    log = _load_or_create_log()
    for pid in point_ids:
        if pid not in log["success"]:
            log["success"].append(pid)
    _save_log(log)

def log_failed(failures):
    """Log failed uploads: list of (point_id, reason)"""
    if not failures:
        return
    
    log = _load_or_create_log()
    for pid, reason in failures:
        log["failed"][pid] = reason
    _save_log(log)

def get_daily_summary():
    """Get today's summary"""
    log = _load_or_create_log()
    total = len(log["success"]) + len(log["failed"])
    
    # Count failures by reason
    reason_count = {}
    for reason in log["failed"].values():
        reason_count[reason] = reason_count.get(reason, 0) + 1
    
    return {
        "date": log.get("date", _get_today()),
        "total": total,
        "success": len(log["success"]),
        "failed": len(log["failed"]),
        "success_list": log["success"],
        "failed_list": log["failed"],
        "failure_reasons": reason_count
    }

def print_summary():
    """Print today's summary to console"""
    summary = get_daily_summary()
    
    print("\n" + "=" * 70)
    print(f"📊 DAILY REPORT: {summary['date']}")
    print("=" * 70)
    print(f"✅ Success: {summary['success']}/{summary['total']} points")
    print(f"❌ Failed:  {summary['failed']}/{summary['total']} points")
    
    if summary["failure_reasons"]:
        print("\n📍 Failure Breakdown:")
        for reason, count in sorted(summary["failure_reasons"].items()):
            print(f"   • {reason}: {count}")
    
    if summary["failed_list"]:
        print("\n🔴 Failed Points:")
        for pid, reason in list(summary["failed_list"].items())[:10]:
            print(f"   • {pid}: {reason}")
        if len(summary["failed_list"]) > 10:
            print(f"   ... and {len(summary['failed_list']) - 10} more")
    
    print("=" * 70 + "\n")

def get_7day_history():
    """Get last 7 days of logs"""
    history = []
    tz = timezone(timedelta(hours=7))
    
    for i in range(7):
        date = (datetime.now(tz) - timedelta(days=i)).strftime("%Y-%m-%d")
        log_file = os.path.join(LOG_DIR, f"daily_{date}.json")
        
        if os.path.exists(log_file):
            try:
                with open(log_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    success = len(data.get("success", []))
                    failed = len(data.get("failed", {}))
                    history.append({
                        "date": date,
                        "success": success,
                        "failed": failed,
                        "total": success + failed
                    })
            except:
                pass
    
    return history

def print_7day_history():
    """Print 7-day history"""
    history = get_7day_history()
    
    print("\n" + "=" * 70)
    print("📈 7-DAY HISTORY")
    print("=" * 70)
    print(f"{'Date':<12} {'Success':<10} {'Failed':<10} {'Total':<10}")
    print("-" * 70)
    
    total_success = 0
    total_failed = 0
    
    for day in history:
        print(f"{day['date']:<12} {day['success']:<10} {day['failed']:<10} {day['total']:<10}")
        total_success += day['success']
        total_failed += day['failed']
    
    print("-" * 70)
    print(f"{'TOTAL':<12} {total_success:<10} {total_failed:<10} {total_success + total_failed:<10}")
    print("=" * 70 + "\n")

def cleanup_old_logs():
    """Remove logs older than 7 days"""
    try:
        tz = timezone(timedelta(hours=7))
        cutoff = datetime.now(tz) - timedelta(days=7)
        
        for filename in os.listdir(LOG_DIR):
            if filename.startswith("daily_") and filename.endswith(".json"):
                date_str = filename.replace("daily_", "").replace(".json", "")
                try:
                    file_date = datetime.strptime(date_str, "%Y-%m-%d")
                    if file_date < cutoff:
                        os.remove(os.path.join(LOG_DIR, filename))
                except:
                    pass
    except:
        pass

# Auto cleanup on import
cleanup_old_logs()
