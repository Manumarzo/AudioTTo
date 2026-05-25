import os
import sys
import shutil
import asyncio
import threading
import multiprocessing
import webbrowser
import time
from fastapi import FastAPI, File, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv
import uvicorn
import google.genai as genai
from google.genai import types


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
def get_base_dir():
    """Restituisce la cartella dell'eseguibile o dello script, gestendo i bundle .app di macOS."""
    if getattr(sys, 'frozen', False):
        path = os.path.dirname(sys.executable)
        if ".app/Contents/MacOS" in path:
            return os.path.abspath(os.path.join(path, "../../../"))
        return path
    return os.path.dirname(os.path.abspath(__file__))

BASE_DIR = get_base_dir()
OUTPUT_ROOT = os.path.join(BASE_DIR, "output")
TEMP_UPLOADS = os.path.join(BASE_DIR, "temp_uploads")
ENV_PATH = os.path.join(BASE_DIR, ".env")

load_dotenv(ENV_PATH, override=True)
app = FastAPI()

def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = BASE_DIR
    return os.path.join(base_path, relative_path)

web_folder = resource_path("web")
os.makedirs(OUTPUT_ROOT, exist_ok=True)

# 🔧 STARTUP CLEANUP: Reset the temp folder every time the app opens
if os.path.exists(TEMP_UPLOADS):
    try:
        shutil.rmtree(TEMP_UPLOADS)
    except Exception as e:
        safe_print(f"Warning: Could not clear temp folder at startup: {e}")
os.makedirs(TEMP_UPLOADS, exist_ok=True)

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
    for root, _, filenames in os.walk(OUTPUT_ROOT):
        for f in filenames:
            if f.endswith(".pdf"):
                full = os.path.join(root, f)
                rel = os.path.relpath(full, OUTPUT_ROOT).replace("\\", "/")
                files.append({
                    "filename": f,
                    "path": rel,
                    "folder": os.path.basename(root)
                })
    return JSONResponse(content=files)


# View PDF (open in browser)
@app.get("/view/{folder}/{filename}")
async def view_pdf(folder: str, filename: str):
    path = os.path.join(OUTPUT_ROOT, folder, filename)
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
    env_path = ENV_PATH
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


class ModelsConfigRequest(BaseModel):
    model_generation: str
    model_revision: str


# Get app info
@app.get("/api/info")
async def app_info():
    load_dotenv(ENV_PATH, override=True)
    return {
        "cpu_count": multiprocessing.cpu_count(),
        "saved_threads": int(os.getenv("THREADS", "4")),
        "model_generation": os.getenv("MODEL_GENERATION", "gemini-2.5-flash"),
        "model_revision": os.getenv("MODEL_REVISION", "gemini-2.5-flash")
    }


# Save models config
@app.post("/api/save-models")
async def save_models(cfg: ModelsConfigRequest):
    env_path = ENV_PATH
    lines = []
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
            
    keys_to_update = {
        "MODEL_GENERATION": cfg.model_generation.strip(),
        "MODEL_REVISION": cfg.model_revision.strip()
    }
    
    new_lines = []
    updated = set()
    for l in lines:
        matched = False
        for k in keys_to_update:
            if l.startswith(f"{k}="):
                new_lines.append(f"{k}={keys_to_update[k]}\n")
                updated.add(k)
                matched = True
                break
        if not matched:
            new_lines.append(l)
            
    for k in keys_to_update:
        if k not in updated:
            new_lines.append(f"{k}={keys_to_update[k]}\n")
            
    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)
        
    os.environ["MODEL_GENERATION"] = cfg.model_generation.strip()
    os.environ["MODEL_REVISION"] = cfg.model_revision.strip()
    return {"message": "Models updated successfully"}


# List models from Google Gemini API
@app.get("/api/models")
async def get_models():
    load_dotenv(ENV_PATH, override=True)
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return JSONResponse(status_code=400, content={"message": "API key missing"})
    
    try:
        client = genai.Client(api_key=api_key)
        
        def fetch_models():
            # Run a small probe check to see if gemini-2.5-pro is blocked on this key
            has_pro_access = True
            try:
                client.models.generate_content(
                    model="gemini-2.5-pro",
                    contents="ping",
                    config=types.GenerateContentConfig(max_output_tokens=1)
                )
            except Exception as probe_err:
                err_str = str(probe_err).lower()
                if any(kw in err_str for kw in ["429", "quota", "exhausted", "limit: 0", "limit 0"]):
                    safe_print(f"⚠️ Pro model check failed (quota/free limit 0). Hiding Pro models: {probe_err}")
                    has_pro_access = False
                elif any(kw in err_str for kw in ["key", "invalid", "unauthorized", "api_key", "400", "403"]):
                    raise probe_err
                else:
                    safe_print(f"⚠️ Pro model check failed with general error (hiding Pro): {probe_err}")
                    has_pro_access = False

            available_models = []
            for m in client.models.list():
                if hasattr(m, 'supported_actions') and m.supported_actions:
                    if "generateContent" in m.supported_actions:
                        name = m.name
                        if name.startswith("models/"):
                            name = name[len("models/"):]
                        
                        # Filter out Pro models if user does not have Pro access on their key/tier
                        if not has_pro_access and "pro" in name.lower():
                            continue
                            
                        available_models.append({
                            "name": name,
                            "display_name": m.display_name or name
                        })
            return available_models

        models = await asyncio.to_thread(fetch_models)
        return {"models": models}
    except Exception as e:
        safe_print(f"Error listing models: {e}")
        return JSONResponse(status_code=500, content={"message": str(e)})



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
    path = os.path.join(TEMP_UPLOADS, file.filename)
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
    files_to_delete = []
    try:
        data = await ws.receive_json()
        audio = data.get("audio_filename")
        video = data.get("video_filename")
        slides = data.get("slides_filename")
        pages = data.get("pages")
        threads = data.get("threads")

        if not audio and not video:
            await ws.send_text("❌ No audio or video file provided")
            return

        if not os.getenv("GEMINI_API_KEY"):
            await ws.send_text("❌ API key missing")
            return

        # Determine the source file (audio or video)
        if video:
            audio_path = os.path.join(TEMP_UPLOADS, video)
        else:
            audio_path = os.path.join(TEMP_UPLOADS, audio)
        
        if audio_path:
            files_to_delete.append(audio_path)

        args = [audio_path]
        if slides:
            slides_path = os.path.join(TEMP_UPLOADS, slides)
            args += ["--slides", slides_path]
            files_to_delete.append(slides_path)

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
        # 🧹 SESSION CLEANUP: Remove files immediately after processing
        for fpath in files_to_delete:
            if fpath and os.path.exists(fpath):
                try:
                    os.remove(fpath)
                    safe_print(f"Cleanup: Removed {os.path.basename(fpath)}")
                except Exception as e:
                    safe_print(f"Cleanup failed for {fpath}: {e}")
        
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
# ------------------------------------------------------------
# MAIN
# ------------------------------------------------------------
if __name__ == "__main__":
    multiprocessing.freeze_support()

    # 🔧 FIX PYTHONNET (WINDOWS + PYINSTALLER)
    # Keeping this for potential future needs, though pywebview is gone
    if sys.platform == "win32" and getattr(sys, "frozen", False):
        base = sys._MEIPASS
        for f in os.listdir(base):
            if f.lower().startswith("python") and f.lower().endswith(".dll"):
                os.environ["PYTHONNET_PYDLL"] = os.path.join(base, f)
                break

    # Open browser automatically after a short delay
    def open_browser():
        time.sleep(1.5)
        webbrowser.open("http://127.0.0.1:8000")

    threading.Thread(target=open_browser, daemon=True).start()

    try:
        start_server()
    except KeyboardInterrupt:
        pass
    finally:
        # 🧹 SHUTDOWN CLEANUP: Ensure absolute path is cleared
        if os.path.exists(TEMP_UPLOADS):
            try:
                shutil.rmtree(TEMP_UPLOADS)
            except:
                pass
