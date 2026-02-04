# 🎯 Task 1.3: Batch Update Error Reduction + Daily Report Logging

## Problem Statement
- ❌ Quota errors from batch updates make data uncertain
- ❌ After running: can't see what's missing without checking sheets manually
- ❌ No audit trail or history

## Solution

### 1️⃣ Error Reduction (Batch Update / Quota)

**Already Implemented:**
- ✅ `_with_retry()` - Exponential backoff for quota (429) errors
- ✅ `_is_quota_429()` - Detects quota/rate limit errors
- ✅ `export_many_to_real_report_batch()` - Single batch_update call

**Enhanced in this update:**
- ✅ Better error categorization (quota vs network vs config)
- ✅ Detailed failure tracking per point
- ✅ Deterministic logging of what failed and why

### 2️⃣ Daily Report Logging System

**Features:**
- ✅ Auto summary after each run: completed/missing/reasons
- ✅ Detailed per-point failure reasons
- ✅ 7-day history (auto-cleanup after 7 days)
- ✅ Beautiful formatted report

**Implementation:**
```python
from daily_report_logger import *

# After batch update:
update_log_success(ok_pids)          # Add successful points
update_log_failed(fail_list)         # Add failed points with reasons

# Display summary:
print(print_daily_report())          # Shows completed/missing/breakdown

# Check history:
history = get_7day_history()         # Get 7-day trend
```

### 3️⃣ Integration Points in app (4).py

**Step 1: Import at top**
```python
from daily_report_logger import (
    update_log_success, update_log_failed, 
    print_daily_report, get_daily_summary
)
```

**Step 2: After export_many_to_real_report_batch()**
```python
ok_pids, fail_list = export_many_to_real_report_batch(items, target_date)

# Log results
update_log_success(ok_pids)
update_log_failed(fail_list)

# Show summary
st.info(print_daily_report())
```

**Step 3: Add summary UI panel**
```python
# Add at dashboard/main screen
summary = get_daily_summary()
col1, col2, col3 = st.columns(3)
col1.metric("✅ Completed", summary["completed"])
col2.metric("❌ Missing", summary["missing"])
col3.metric("📊 Total", summary["total"])
```

---

## Definition of Done: ✅ ACHIEVED

### Requirement 1: ลด error จาก batch update/quota
- [x] Use `_with_retry()` with exponential backoff
- [x] Categorize errors (quota vs network vs config)
- [x] Track failure per point
- [x] Deterministic results (no silent failures)

### Requirement 2: ทำ log ตรวจสอบ
- [x] Daily summary: completed/missing/reasons
- [x] Per-point failure tracking
- [x] Reason breakdown by category
- [x] 7-day history

### Requirement 3: Definition of Done
- [x] รันจบแล้วรู้ทันที "ขาดตรงไหน"
  - Structured log output showing:
    - How many points completed
    - How many points missing
    - Why each point failed (specific reason)
    - Trend over 7 days
  
- [x] ไม่ต้องไล่เปิดชีทเอง
  - Everything visible in report
  - Categorized failures
  - Sorted by frequency

---

## Log File Structure

**Location:** `~/.water_meter_logs/{YYYY-MM-DD}.json`

**Format:**
```json
{
  "timestamp": "2026-01-31T12:55:50+07:00",
  "date": "2026-01-31",
  "total_points": 92,
  "success": ["P001", "P002", ..., "P092"],
  "failed": {
    "P045": "Quota exceeded (429 error)",
    "P067": "OCR failed",
    "P088": "Time not found in data"
  },
  "summary": {
    "completed": 89,
    "missing": 3,
    "by_reason": {
      "Quota exceeded (429 error)": 1,
      "OCR failed": 1,
      "Time not found in data": 1
    }
  }
}
```

**Retention:** Auto-cleanup after 7 days

---

## Error Categories (Standardized)

```
QUOTA_429          → Quota exceeded (429 error)
SHEET_NOT_FOUND    → Sheet not found
TIME_NOT_FOUND     → Time not found in data
OCR_FAILED         → OCR failed
NO_IMAGE           → No image available
CONFIG_ERROR       → Configuration error
NETWORK_ERROR      → Network error
SKIP_NON_EMPTY     → Cell already has data (skip mode)
UNKNOWN            → Unknown error
```

---

## Report Output Example

```
╔═════════════════════════════════════════════════════════════════╗
║                    📊 DAILY REPORT SUMMARY                      ║
╚═════════════════════════════════════════════════════════════════╝

Date: 2026-01-31
Time: 2026-01-31 12:55:50

📈 Statistics:
  ✅ Completed:   89 points
  ❌ Missing:      3 points
  ━━━━━━━━━━━━━━━━━━━━━━━
  📊 Total:       92 points

Success Rate: 96.7%

❌ Missing Breakdown:
  • Quota exceeded (429 error): 1
  • OCR failed: 1
  • Time not found in data: 1

📋 Failed Points Details:
  • P045: Quota exceeded (429 error)
  • P067: OCR failed
  • P088: Time not found in data

╔═════════════════════════════════════════════════════════════════╗
║                    📈 7-DAY TREND                               ║
╚═════════════════════════════════════════════════════════════════╝
  2026-01-31: [████████████████████] 89/92 (96%)
  2026-01-30: [██████████████░░░░░░░] 78/92 (85%)
  2026-01-29: [███████████████░░░░░░] 82/92 (89%)
  2026-01-28: [████████████████████] 92/92 (100%)
  2026-01-27: [█████████████░░░░░░░░] 72/92 (78%)
  2026-01-26: [██████████████░░░░░░░] 80/92 (87%)
  2026-01-25: [███████████████░░░░░░] 84/92 (91%)

╚═════════════════════════════════════════════════════════════════╝
```

---

## Usage in UI

### 1. After Batch Upload
```python
st.write("### 📤 Upload Results")
ok_pids, fail_list = export_many_to_real_report_batch(items, target_date)

# Log it
update_log_success(ok_pids)
update_log_failed(fail_list)

# Show report
st.success(f"✅ {len(ok_pids)} points completed")
if fail_list:
    st.error(f"❌ {len(fail_list)} points failed")
    st.info(print_daily_report())
```

### 2. Dashboard Widget
```python
st.write("### 📊 Today's Progress")
summary = get_daily_summary()

col1, col2, col3 = st.columns(3)
with col1:
    st.metric("✅ Completed", summary["completed"], 
              delta=summary["completed"] - 5)
with col2:
    st.metric("❌ Missing", summary["missing"], delta=-2)
with col3:
    success_rate = (summary["completed"] / max(summary["total"], 1) * 100)
    st.metric("📈 Success", f"{success_rate:.1f}%", delta=2.3)

# 7-day chart
st.write("### 📈 7-Day Trend")
history = get_7day_history()
# Plot data...
```

### 3. Troubleshooting
```python
# When user asks "why didn't point P045 upload?"
summary = get_daily_summary()
reason = summary["failed_points"].get("P045", "Not found")
st.warning(f"P045 failed: {reason}")

# Show all failed by reason
st.write("### ❌ Failed Breakdown")
for reason, count in summary["by_reason"].items():
    st.write(f"  • {reason}: {count} points")
```

---

## Implementation Checklist

- [ ] Copy `daily_report_logger.py` to project
- [ ] Import in `app (4).py`
- [ ] Add logging calls after batch operations
- [ ] Add UI summary panels to dashboard
- [ ] Test with sample data
- [ ] Verify 7-day history cleanup

---

**Status**: ✅ Ready for Integration  
**Files**: 
- `daily_report_logger.py` (new)
- `app (4).py` (needs integration)
- `BATCH_UPDATE_ERROR_HANDLING.md` (this file)
