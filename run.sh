#!/usr/bin/env bash
cd "$(dirname "$0")"
export QT_QPA_PLATFORM=xcb
PYQT5_DIR=$(python3 -c "import PyQt5,os; print(os.path.dirname(PyQt5.__file__))" 2>/dev/null||echo "")
for d in "$PYQT5_DIR/Qt5/plugins" "$PYQT5_DIR/Qt/plugins"; do
    [ -d "$d" ] && export QT_QPA_PLATFORM_PLUGIN_PATH="$d" && break
done
python3 main.py "$@"
