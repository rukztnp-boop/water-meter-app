#!/usr/bin/env python3
"""
Test _norm_pid_key fixes
"""
import re

def _norm_pid_key(s: str) -> str:
    s = str(s or "").upper().strip()
    s = s.replace("-", "_")
    s = re.sub(r"\s+", "_", s)
    s = re.sub(r"[^A-Z0-9_]", "", s)
    s = re.sub(r"_+", "_", s).strip("_")
    
    s = s.replace("S_", "3_")
    s = s.replace("_S_", "_3_")
    s = s.replace("_S", "_3")
    
    # 🔥 แปลงเลข 2 หลักติดกันเป็น X_Y
    s = re.sub(r"_(\d)\1(?=_|$)", r"_\1_\1", s)
    
    return s

# Test cases
test_cases = [
    ("GT BP 33", "GT_BP_3_3"),  # Expected after fix
    ("GT_BP_33", "GT_BP_3_3"),  # Direct input
    ("FN WWT AS", "FN_WWT_AS"),
    ("FN_WWT_AS", "FN_WWT_AS"),
    ("BP_22", "BP_2_2"),
    ("GV_BP_11", "GV_BP_1_1"),
]

print("Testing _norm_pid_key:")
print("="*70)
for input_str, expected in test_cases:
    result = _norm_pid_key(input_str)
    status = "✅" if result == expected else "❌"
    print(f"{status} '{input_str}' → '{result}' (expected: '{expected}')")
