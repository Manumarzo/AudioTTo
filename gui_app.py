import os
import sys
import asyncio
import shutil
import threading
import multiprocessing
from io import StringIO
from contextlib import redirect_stdout, redirect_stderr

from fastapi import FastAPI, File, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv
import uvicorn

# ------------------------------------------------------------
# SAFE PRINT (non rompe mai PyInstaller)
# ------------------------------------------------------------
def safe_print(msg):
    try:
        print(msg)
    except Exception:
        pass


# ------------------------------------------------------------
# RESOURCE PATH (PyInstaller safe)
# ------------------------------------------------------------
def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


# ------------------------------------------------------------
# FASTAPI APP
# ------------------------------------------------------------
load_dotenv()
app = FastAPI()

web_folder = resource_path("web")
os.makedirs(web_folder, exist_ok=True)

app.mount("/static", StaticFiles(directory=web_folder), name="static")

os.makedirs("output", exist_ok=True)
os.makedirs("temp_uploads", exist_ok=True)


@app.get("/")
async def index():
    return FileResponse(os.path.join(web_folder, "index.html"))


@app.get("/outputs")
async def list_outputs():
    files = []
    for root, _, names in os.walk("output"):
        for n in names:
            if n.endswith(".pdf"):
                files.append({
                    "filename": n,
                    "path": os.path.relpath(os.path.join(root, n), "output").replace("\\", "/"),
                    "folder": os.path.basename(root)
                })
    return files


@app.get("/download/{folder}/{filename}")
async def download(folder: str, filename: str):
    p = os.path.join("output", folder, filename)
    if not os.path.exists(p):
        return JSONResponse(status_code=404, content={"message": "Not found"})
    return FileResponse(p, filename=filename)


# ------------------------------------------------------------
# API CONFIG
# ------------------------------------------------------------
class ApiKeyRequest(BaseModel):
    api_key: str


@app.get("/api/key-status")
async def key_status():
    load_dotenv(override=True)
    return {"is_set": bool(os.getenv("GEMINI_API_KEY"))}


@app.post("/api/key")
async def save_key(req: ApiKeyRequest):
    os.environ["GEMINI_API_KEY"] = req.api_key.strip()
    with open(".env", "w", encoding="utf-8") as f:
        f.write(f"GEMINI_API_KEY={req.api_key.strip()}\n")
    return {"message": "OK"}


class ThreadConfig(BaseModel):
    threads: int


@app.get("/api/info")
async def app_info():
    cpu = multiprocessing.cpu_count()
    threads = int(os.getenv("THREADS", "4"))
    return {"cpu_count": cpu, "saved_threads": threads}


@app.post("/api/save-threads")
async def save_threads(cfg: ThreadConfig):
    os.environ["THREADS"] = str(cfg.threads)
    with open(".env", "a", encoding="utf-8") as f:
        f.write(f"THREADS={cfg.threads}\n")
    return {"message": "OK"}


# ------------------------------------------------------------
# AUDIO PROCESSING WRAPPER (LAZY IMPORT)
# ------------------------------------------------------------
def run_audiotto(args, loop, websocket):
    import AudioTTo  # IMPORT LAZY

    def ws_log(msg):
        async def send():
            try:
                await websocket.send_text(msg)
            except Exception:
                pass
        asyncio.run_coroutine_threadsafe(send(), loop)

    AudioTTo.set_logger(ws_log)
    try:
        AudioTTo.main(args)
    except Exception as e:
        ws_log(f"❌ Error: {e}")
    finally:
        AudioTTo.set_logger(None)


@app.websocket("/ws/process")
async def ws_process(ws: WebSocket):
    await ws.accept()
    try:
        data = await ws.receive_json()
        audio = data.get("audio_filename")
        if not audio:
            await ws.send_text("❌ No audio")
            return

        args = [os.path.join("temp_uploads", audio)]

        if data.get("slides_filename"):
            args += ["--slides", os.path.join("temp_uploads", data["slides_filename"])]

        if data.get("pages"):
            args += ["--pages", data["pages"]]

        if data.get("threads"):
            args += ["--threads", str(data["threads"])]

        loop = asyncio.get_event_loop()
        await ws.send_text("🚀 Processing...")
        await asyncio.to_thread(run_audiotto, args, loop, ws)
        await ws.send_text("✅ Done")
        await ws.send_text("REFRESH_OUTPUTS")

    except WebSocketDisconnect:
        safe_print("Client disconnected")


@app.post("/upload")
async def upload(file: UploadFile = File(...)):
    p = os.path.join("temp_uploads", file.filename)
    with open(p, "wb") as f:
        shutil.copyfileobj(file.file, f)
    return {"filename": file.filename}


# ------------------------------------------------------------
# MAIN (TUTTO QUI)
# ------------------------------------------------------------
if __name__ == "__main__":
    multiprocessing.freeze_support()

    # ---------- LOGGING SAFE ----------
    try:
        log_dir = resource_path(".")
        log_file = os.path.join(log_dir, "debug.log")
        import logging
        logging.basicConfig(filename=log_file, level=logging.INFO)
    except Exception:
        pass

    # ---------- PYTHONNET FIX ----------
    if sys.platform == "win32" and getattr(sys, "frozen", False):
        base = sys._MEIPASS
        for f in os.listdir(base):
            if f.lower().startswith("python") and f.endswith(".dll"):
                os.environ["PYTHONNET_PYDLL"] = os.path.join(base, f)
                break

    # ---------- START SERVER ----------
    server = threading.Thread(
        target=lambda: uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info"),
        daemon=True
    )
    server.start()

    # ---------- GUI ----------
    try:
        import webview
        webview.create_window(
            "AudioTTo - Notes generator",
            "http://127.0.0.1:8000",
            width=1000,
            height=800,
            resizable=True
        )

        webview.start()

    except Exception as e:
        safe_print("⚠️ GUI unavailable, open browser:")
        safe_print("http://127.0.0.1:8000")
        import webbrowser
        webbrowser.open("http://127.0.0.1:8000")
        try:
            while True:
                import time
                time.sleep(1)
        except KeyboardInterrupt:
            pass
