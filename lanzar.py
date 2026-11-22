import threading
import time
import webbrowser
import app

def abrir_navegador():
    time.sleep(1.5)
    webbrowser.open("http://127.0.0.1:5000")

if __name__ == "__main__":
    threading.Thread(target=abrir_navegador).start()
    app.init_db()
    app.app.run(debug=False, use_reloader=False, host="127.0.0.1", port=5000)