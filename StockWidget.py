# filename: StockWidget.py
# python3 -m PyInstaller -F -w .\StockWidget.py --name StockWidget --icon .\StockWidget.ico --add-data ".\StockWidget.ico;."
import sys, ctypes
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from App import App, APP_NAME

if __name__ == "__main__":
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(f"{APP_NAME}.1")
    except Exception:
        pass

    # ========== 必须加在 QApplication 实例化之前 ==========
    # 开启高分辨率屏幕的自适应缩放
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
    # 支持高分辨率图标
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)
    app = App(sys.argv)
    sys.exit(app.exec())
