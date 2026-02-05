"""
Standalone wrapper for auto_processor.py
ห่อ app.py imports โดยไม่ trigger Streamlit UI
"""
import os
import sys

# Mock streamlit to prevent UI initialization
class MockStreamlit:
    class secrets:
        pass
    
    def set_page_config(self, **kwargs):
        pass
    
    def markdown(self, *args, **kwargs):
        pass
    
    def error(self, *args, **kwargs):
        pass

# Inject mock before importing app
sys.modules['streamlit'] = MockStreamlit()

# Now import from app.py
from app import (
    load_scada_excel_mapping,
    extract_scada_values_from_exports,
    gc,
    DB_SHEET_NAME,
    get_thai_time
)

# Restore real streamlit (if needed later)
if 'streamlit' in sys.modules:
    del sys.modules['streamlit']
