#!/bin/bash
# 🧪 Quick Test Script for OCR Fixes

echo "🧪 OCR Quick Test Script"
echo "========================="

# Check if test image folder exists
if [ -z "$1" ]; then
    echo "Usage: ./quick_test.sh <image_folder_or_file>"
    echo ""
    echo "Examples:"
    echo "  ./quick_test.sh 'รูป error หลังจากแก้ code วันนี้.zip'"
    echo "  ./quick_test.sh error_images/"
    echo "  ./quick_test.sh S__154140715_0.jpg"
    exit 1
fi

INPUT="$1"

# Check if it's a zip file
if [[ "$INPUT" == *.zip ]]; then
    echo "📦 Extracting zip file..."
    EXTRACT_DIR="extracted_test_images"
    mkdir -p "$EXTRACT_DIR"
    unzip -q "$INPUT" -d "$EXTRACT_DIR"
    INPUT="$EXTRACT_DIR"
    echo "✅ Extracted to: $EXTRACT_DIR"
fi

# Check if input exists
if [ ! -e "$INPUT" ]; then
    echo "❌ Error: $INPUT not found"
    exit 1
fi

# Test VSD images first
echo ""
echo "🔥 Testing VSD/Digital meters..."
echo "================================"
python3 test_vsd_meter.py "$INPUT"

# Run full regression test
echo ""
echo "📊 Running full regression test..."
echo "=================================="
python3 test_ocr_regression.py "$INPUT" -o "results_$(date +%Y%m%d_%H%M%S).csv"

echo ""
echo "✅ Testing complete!"
echo ""
echo "📄 Check the CSV and JSON files for detailed results"
