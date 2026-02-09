"""
Standalone wrapper for auto_processor.py
ห่อ app.py imports โดยไม่ trigger Streamlit UI
"""
import os
import sys

# Mock streamlit to prevent UI initialization
class MockSidebar:
    """Mock sidebar that returns itself for chaining"""
    def radio(self, *args, **kwargs):
        return kwargs.get('index', 0) if 'index' in kwargs else None
    
    def selectbox(self, *args, **kwargs):
        return kwargs.get('index', 0) if 'index' in kwargs else None
    
    def button(self, *args, **kwargs):
        return False
    
    def text_input(self, *args, **kwargs):
        return ""
    
    def file_uploader(self, *args, **kwargs):
        return None

class MockStreamlit:
    class secrets:
        pass
    
    class session_state:
        _data = {}
        
        def __getitem__(self, key):
            return self._data.get(key)
        
        def __setitem__(self, key, value):
            self._data[key] = value
        
        def __contains__(self, key):
            return key in self._data
        
        def get(self, key, default=None):
            return self._data.get(key, default)
    
    # Add sidebar
    sidebar = MockSidebar()
    
    def set_page_config(self, **kwargs):
        pass
    
    def markdown(self, *args, **kwargs):
        pass
    
    def error(self, *args, **kwargs):
        pass
    
    def warning(self, *args, **kwargs):
        pass
    
    def info(self, *args, **kwargs):
        pass
    
    def success(self, *args, **kwargs):
        pass
    
    def stop(self):
        pass
    
    def write(self, *args, **kwargs):
        pass
    
    def button(self, *args, **kwargs):
        return False
    
    def text_input(self, *args, **kwargs):
        return ""
    
    def file_uploader(self, *args, **kwargs):
        return None
    
    def download_button(self, *args, **kwargs):
        return False
    
    # Mock decorators
    @staticmethod
    def cache_data(*args, **kwargs):
        def decorator(func):
            return func
        if len(args) == 1 and callable(args[0]):
            return args[0]
        return decorator
    
    @staticmethod
    def cache_resource(*args, **kwargs):
        def decorator(func):
            return func
        if len(args) == 1 and callable(args[0]):
            return args[0]
        return decorator

# Inject mock before importing app
sys.modules['streamlit'] = MockStreamlit()

# Mock heavy packages ที่ไม่จำเป็นสำหรับ SCADA collector
from unittest.mock import MagicMock

# mock google.cloud chain (vision, storage ไม่ได้ใช้ แต่ app.py import)
_mock_cloud = MagicMock()
for mod_name in [
    'google.cloud',
    'google.cloud.vision',
    'google.cloud.storage',
]:
    if mod_name not in sys.modules:
        sys.modules[mod_name] = _mock_cloud

# mock อื่นๆ ที่ไม่ได้ติดตั้ง
for mod_name in ['cv2', 'pandas', 'inference_sdk']:
    if mod_name not in sys.modules:
        sys.modules[mod_name] = MagicMock()

# mock numpy เฉพาะถ้ายังไม่ได้ติดตั้ง
try:
    import numpy
except ImportError:
    sys.modules['numpy'] = MagicMock()

# Now import from app.py
from app import (
    load_scada_excel_mapping,
    extract_scada_values_from_exports,
    export_many_to_real_report_batch,
    append_rows_dailyreadings_batch,
    get_meter_config,
    infer_meter_type,
    gc,
    DB_SHEET_NAME,
    REAL_REPORT_SHEET,
    get_thai_time
)

# Restore real streamlit (if needed later)
if 'streamlit' in sys.modules:
    del sys.modules['streamlit']
