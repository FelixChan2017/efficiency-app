import threading
import time
import webview
from app import app


def start_flask():
    app.run(host="127.0.0.1", port=5000, debug=False)


if __name__ == "__main__":
    t = threading.Thread(target=start_flask, daemon=True)
    t.start()
    time.sleep(1)
    webview.create_window("人效计算", "http://127.0.0.1:5000",
                          width=1200, height=800,
                          min_size=(900, 600))
    webview.start()
