import os
import sys
import shutil
import asyncio
import threading
import multiprocessing
import webbrowser
from fastapi import FastAPI, File, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv
import uvicorn

# ------------------------------------------------------------
# WINDOWS ENCODING FIX
# ------------------------------------------------------------
if sys.platform == "win32":
    os.environ["PYTHONIOENCODING"] = "utf-8"
    if sys.stdout:
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except:
            pass
    if sys.stderr:
        try:
            sys.stderr.reconfigure(encoding="utf-8")
        except:
            pass


def safe_print(msg):
    try:
        print(msg)
    except:
        pass


# ------------------------------------------------------------
# FASTAPI SETUP
# ------------------------------------------------------------
load_dotenv()
app = FastAPI()


def resource_path(relative_path):
    """Compatibile con PyInstaller"""
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


web_folder = resource_path("web")
os.makedirs(web_folder, exist_ok=True)
os.makedirs("output", exist_ok=True)
os.makedirs("temp_uploads", exist_ok=True)

app.mount("/static", StaticFiles(directory=web_folder), name="static")


# ------------------------------------------------------------
# ROUTES
# ------------------------------------------------------------

# Root (index.html): main menu 
@app.get("/")
async def index():
    return FileResponse(os.path.join(web_folder, "index.html"))


# Outputs (folder where appunti.pdf is saved)
@app.get("/outputs")
async def list_outputs():
    files = []
    for root, _, filenames in os.walk("output"):
        for f in filenames:
            if f.endswith(".pdf"):
                full = os.path.join(root, f)
                rel = os.path.relpath(full, "output").replace("\\", "/")
                files.append({
                    "filename": f,
                    "path": rel,
                    "folder": os.path.basename(root)
                })
    return JSONResponse(content=files)


# View PDF (open in browser)
@app.get("/view/{folder}/{filename}")
async def view_pdf(folder: str, filename: str):
    path = os.path.join("output", folder, filename)
    if os.path.exists(path):
        return FileResponse(path, media_type="application/pdf", content_disposition_type="inline")
    return JSONResponse(status_code=404, content={"message": "Not found"})


# Download PDF (download from browser)
@app.get("/download/{folder}/{filename}")
async def download_pdf(folder: str, filename: str):
    path = os.path.join("output", folder, filename)
    if os.path.exists(path):
        return FileResponse(path, filename=filename)
    return JSONResponse(status_code=404, content={"message": "Not found"})


# ------------------------------------------------------------
# SETTINGS API
# ------------------------------------------------------------
class ApiKeyRequest(BaseModel):
    api_key: str


# Check API key status
@app.get("/api/key-status")
async def key_status():
    load_dotenv(override=True)
    return {"is_set": bool(os.getenv("GEMINI_API_KEY"))}


# Save API key
@app.post("/api/key")
async def save_key(req: ApiKeyRequest):
    key = req.api_key.strip()
    env_path = ".env"
    lines = []

    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

    found = False
    new_lines = []
    for l in lines:
        if l.startswith("GEMINI_API_KEY="):
            new_lines.append(f"GEMINI_API_KEY={key}\n")
            found = True
        else:
            new_lines.append(l)

    if not found:
        new_lines.append(f"GEMINI_API_KEY={key}\n")

    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)

    os.environ["GEMINI_API_KEY"] = key
    return {"message": "API key saved"}


class ThreadConfig(BaseModel):
    threads: int


# Get app info
@app.get("/api/info")
async def app_info():
    return {
        "cpu_count": multiprocessing.cpu_count(),
        "saved_threads": int(os.getenv("THREADS", "4"))
    }


# Save threads
@app.post("/api/save-threads")
async def save_threads(cfg: ThreadConfig):
    env_path = ".env"
    lines = []

    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

    found = False
    out = []
    for l in lines:
        if l.startswith("THREADS="):
            out.append(f"THREADS={cfg.threads}\n")
            found = True
        else:
            out.append(l)

    if not found:
        out.append(f"THREADS={cfg.threads}\n")

    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(out)

    os.environ["THREADS"] = str(cfg.threads)
    return {"message": "Threads saved"}


# ------------------------------------------------------------
# FILE UPLOAD
# ------------------------------------------------------------

# Upload file
@app.post("/upload")
async def upload(file: UploadFile = File(...)):
    path = os.path.join("temp_uploads", file.filename)
    with open(path, "wb") as f:
        shutil.copyfileobj(file.file, f)
    return {"filename": file.filename}


# ------------------------------------------------------------
# WEBSOCKET PROCESS
# ------------------------------------------------------------

# Process audio
@app.websocket("/ws/process")
async def process_ws(ws: WebSocket):
    await ws.accept()
    try:
        data = await ws.receive_json()
        audio = data.get("audio_filename")
        slides = data.get("slides_filename")
        pages = data.get("pages")
        threads = data.get("threads")

        if not audio:
            await ws.send_text("❌ No audio file")
            return

        if not os.getenv("GEMINI_API_KEY"):
            await ws.send_text("❌ API key missing")
            return

        args = [os.path.join("temp_uploads", audio)]
        if slides:
            args += ["--slides", os.path.join("temp_uploads", slides)]
        if pages:
            args += ["--pages", pages]
        if threads:
            args += ["--threads", str(threads)]

        await ws.send_text(f"🚀 Processing (threads={threads})")

        loop = asyncio.get_running_loop()
        await asyncio.to_thread(run_audiotto, args, loop, ws)

        await ws.send_text("✅ Done")
        await ws.send_text("REFRESH_OUTPUTS")

    except WebSocketDisconnect:
        pass
    except Exception as e:
        await ws.send_text(f"❌ Error: {e}")
    finally:
        try:
            await ws.close()
        except:
            pass


def run_audiotto(args, loop, ws):
    # 🔥 LAZY IMPORT (CRITICO)
    import AudioTTo

    def logger(msg):
        async def send():
            try:
                await ws.send_text(msg)
            except:
                pass
        asyncio.run_coroutine_threadsafe(send(), loop)

    AudioTTo.set_logger(logger)
    try:
        AudioTTo.main(args)
    except Exception as e:
        logger(f"❌ {e}")
    finally:
        AudioTTo.set_logger(None)


# ------------------------------------------------------------
# SERVER START
# ------------------------------------------------------------

# Start server
def start_server():
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=8000,
        log_level="info",
        loop="asyncio"
    )


# ------------------------------------------------------------
# MAIN
# ------------------------------------------------------------
if __name__ == "__main__":
    multiprocessing.freeze_support()

    # 🔧 FIX PYTHONNET (WINDOWS + PYINSTALLER)
    if sys.platform == "win32" and getattr(sys, "frozen", False):
        base = sys._MEIPASS
        for f in os.listdir(base):
            if f.lower().startswith("python") and f.lower().endswith(".dll"):
                os.environ["PYTHONNET_PYDLL"] = os.path.join(base, f)
                break

    server = threading.Thread(target=start_server, daemon=True)
    server.start()

    try:
        import webview
        webview.create_window(
            "AudioTTo - Notes Generator",
            "http://127.0.0.1:8000",
            width=1000,
            height=800,
            resizable=True
        )
        webview.start()

    except Exception as e:
        safe_print("\n⚠️ GUI not available, opening browser")
        safe_print(str(e))
        webbrowser.open("http://127.0.0.1:8000")

        try:
            while True:
                import time
                time.sleep(1)
        except KeyboardInterrupt:
            pass

    finally:
        if os.path.exists("temp_uploads"):
            try:
                shutil.rmtree("temp_uploads")
            except:
                pass
