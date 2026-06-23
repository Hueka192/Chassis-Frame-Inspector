#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
echo "=== Chassis Frame Inspector — Fix & Launch ==="
echo "[1/4] Removing opencv-python (Qt conflict)..."
pip uninstall opencv-python -y 2>/dev/null || true
echo "[2/4] Installing opencv-python-headless..."
pip install opencv-python-headless --upgrade -q
echo "[3/4] Dependencies..."
pip install PyQt5 numpy PyYAML Pillow python-pptx --upgrade -q
echo "[4/4] Launching..."
export QT_QPA_PLATFORM=xcb
PYQT5_DIR=$(python3 -c "import PyQt5,os; print(os.path.dirname(PyQt5.__file__))" 2>/dev/null||echo "")
for d in "$PYQT5_DIR/Qt5/plugins" "$PYQT5_DIR/Qt/plugins"; do
    [ -d "$d" ] && export QT_QPA_PLATFORM_PLUGIN_PATH="$d" && break
done
python3 main.py
