# 📚 Daily Report Logger - Quick Reference

## Installation
```bash
# Copy file to project directory
cp daily_report_logger.py /path/to/project/
```

## Import
```python
from daily_report_logger import (
    update_log_success,      # Record successful points
    update_log_failed,       # Record failed points with reasons
    print_daily_report,      # Get formatted report
    get_daily_summary,       # Get data dict
    get_7day_history,        # Get 7-day trend
)
```

## Basic Usage

### 1. Log Successful Points
```python
ok_pids = ["P001", "P002", "P003"]
update_log_success(ok_pids)
```

### 2. Log Failed Points (with reasons)
```python
fail_list = [
    ("P004", "OCR failed"),
    ("P005", "Quota exceeded (429 error)"),
    ("P006", "Time not found in data"),
]
update_log_failed(fail_list)
```

### 3. Print Daily Report
```python
report = print_daily_report()
print(report)
# OR in Streamlit:
st.info(report)
```

### 4. Get Summary Data
```python
summary = get_daily_summary()
print(f"Completed: {summary['completed']}")
print(f"Missing: {summary['missing']}")
print(f"Reasons: {summary['by_reason']}")
```

### 5. Get 7-Day History
```python
history = get_7day_history()
for day in history:
    print(f"{day['date']}: {day['completed']}/{day['total']}")
```

---

## Real Example from app (4).py

### Before (no logging)
```python
ok_pids, fail_list = export_many_to_real_report_batch(items, target_date)
st.success(f"Done: {len(ok_pids)} uploaded")
# User doesn't know what failed!
```

### After (with logging)
```python
from daily_report_logger import *

ok_pids, fail_list = export_many_to_real_report_batch(items, target_date)

# Log the results
update_log_success(ok_pids)
update_log_failed(fail_list)

# Show beautiful report
st.success(f"✅ {len(ok_pids)} points completed")
if fail_list:
    st.error(f"❌ {len(fail_list)} points failed")
    st.info(print_daily_report())
# User sees exactly what's missing and why!
```

---

## Log Files Location
```
~/.water_meter_logs/
├── 2026-01-31.json  ← Today's log
├── 2026-01-30.json
├── 2026-01-29.json
├── 2026-01-28.json
└── ...
```

Auto-cleanup: Older than 7 days = deleted

---

## Failure Reasons (Standardized)

| Reason | Meaning |
|--------|---------|
| `QUOTA_429` | Quota exceeded (rate limited) |
| `SHEET_NOT_FOUND` | Monthly sheet doesn't exist |
| `TIME_NOT_FOUND` | Time column/value not found |
| `OCR_FAILED` | OCR couldn't read meter |
| `NO_IMAGE` | No image uploaded |
| `CONFIG_ERROR` | Point configuration issue |
| `NETWORK_ERROR` | Network/connection error |
| `SKIP_NON_EMPTY` | Cell already had data (skip mode) |
| `UNKNOWN` | Unknown error |

---

## Dashboard Integration

### Add to main page
```python
import streamlit as st
from daily_report_logger import get_daily_summary, get_7day_history

# Header
st.title("💧 Water Meter System")

# Add today's summary
st.markdown("## 📊 Today's Progress")
summary = get_daily_summary()

col1, col2, col3 = st.columns(3)
col1.metric("✅ Completed", summary["completed"], delta=f"+{summary['completed']}")
col2.metric("❌ Missing", summary["missing"], delta=f"-{len(summary['failed_points'])}")
col3.metric("📈 Rate", f"{(summary['completed']/max(summary['total'],1)*100):.1f}%")

# Failed breakdown
if summary["by_reason"]:
    st.markdown("### ❌ Missing Breakdown")
    for reason, count in sorted(summary["by_reason"].items(), key=lambda x: -x[1]):
        st.write(f"• **{reason}**: {count} points")
else:
    st.success("🎉 All points complete!")
```

---

## Monitoring Script

Run this daily to check yesterday's status:
```python
from daily_report_logger import *
from datetime import datetime, timedelta

yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
log_file = Path.home() / f".water_meter_logs/{yesterday}.json"

if log_file.exists():
    with open(log_file) as f:
        log = json.load(f)
    print(print_daily_report())
```

---

## Troubleshooting

### Q: Why is point P045 failing?
```python
summary = get_daily_summary()
print(summary["failed_points"].get("P045"))
# Output: "Quota exceeded (429 error)"
```

### Q: What's the trend this week?
```python
history = get_7day_history()
for day in history:
    rate = day["completed"] / max(day["total"], 1) * 100
    print(f"{day['date']}: {rate:.1f}%")
```

### Q: How do I reset today's log?
```python
from pathlib import Path
log_file = Path.home() / f".water_meter_logs/{datetime.now().strftime('%Y-%m-%d')}.json"
log_file.unlink()  # Delete today's log
```

---

## API Reference

### `update_log_success(point_ids: list)`
Record successfully uploaded points
- **point_ids**: List of point IDs like `["P001", "P002"]`

### `update_log_failed(failures: list)`
Record failed points with reasons
- **failures**: List of `(point_id, reason)` tuples

### `print_daily_report() -> str`
Get formatted report string
- **Returns**: Multi-line report string

### `get_daily_summary() -> dict`
Get summary data
- **Returns**: `{"completed": int, "missing": int, "by_reason": dict, ...}`

### `get_7day_history() -> list`
Get 7-day trend
- **Returns**: List of daily summaries

### `get_today_log_file() -> Path`
Get today's log file path
- **Returns**: Path object

### `load_today_log() -> dict`
Load/create today's log
- **Returns**: Log dict

### `cleanup_old_logs()`
Delete logs older than 7 days
- **Auto-called**: By `save_log()`

---

## Performance Notes

- Log file size: ~5KB per day
- 7-day retention: ~35KB total
- No performance impact (JSON writes are fast)
- Auto-cleanup happens at `save_log()` time

---

**Last Updated**: 2026-01-31
**Version**: 1.0
**Status**: ✅ Production Ready
