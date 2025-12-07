import os
import sys
import shutil
import asyncio
import threading
from io import StringIO
from contextlib import redirect_stdout, redirect_stderr
from fastapi import FastAPI, File, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv
import uvicorn

# Importiamo direttamente il modulo di elaborazione
import AudioTTo

load_dotenv()

app = FastAPI()

# --- FUNZIONE PER TROVARE LE RISORSE (HTML) NELL'EXE ---
def resource_path(relative_path):
    """ Ottiene il percorso assoluto delle risorse, funziona sia in dev che in PyInstaller """
    try:
        # PyInstaller crea una cartella temporanea in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

# Mount static files usando il path corretto
web_folder = resource_path("web")
if not os.path.exists(web_folder):
    os.makedirs(web_folder, exist_ok=True) # Fallback per evitare crash

app.mount("/static", StaticFiles(directory=web_folder), name="static")

os.makedirs("output", exist_ok=True)
os.makedirs("temp_uploads", exist_ok=True)

@app.get("/")
async def read_index():
    return FileResponse(os.path.join(web_folder, "index.html"))

@app.get("/outputs")
async def list_outputs():
    pdf_files = []
    for root, dirs, files in os.walk("output"):
        for file in files:
            if file.endswith(".pdf"):
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, "output")
                pdf_files.append({
                    "filename": file,
                    "path": rel_path.replace("\\", "/"), # Fix per Windows paths in JSON
                    "folder": os.path.basename(root)
                })
    return JSONResponse(content=pdf_files)

@app.get("/view/{folder}/{filename}")
async def view_file(folder: str, filename: str):
    file_path = os.path.join("output", folder, filename)
    if os.path.exists(file_path):
        return FileResponse(file_path, media_type="application/pdf", content_disposition_type="inline")
    return JSONResponse(status_code=404, content={"message": "File not found"})

@app.get("/download/{folder}/{filename}")
async def download_file(folder: str, filename: str):
    file_path = os.path.join("output", folder, filename)
    if os.path.exists(file_path):
        return FileResponse(file_path, filename=filename)
    return JSONResponse(status_code=404, content={"message": "File not found"})

class ApiKeyRequest(BaseModel):
    api_key: str

@app.get("/api/key-status")
async def get_api_key_status():
    load_dotenv(override=True)
    api_key = os.getenv("GEMINI_API_KEY")
    return {"is_set": bool(api_key)}

@app.post("/api/key")
async def set_api_key(request: ApiKeyRequest):
    key = request.api_key.strip()
    env_path = ".env"
    lines = []
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    
    key_found = False
    new_lines = []
    for line in lines:
        if line.startswith("GEMINI_API_KEY="):
            new_lines.append(f"GEMINI_API_KEY={key}\n")
            key_found = True
        else:
            new_lines.append(line)
    
    if not key_found:
        if new_lines and not new_lines[-1].endswith("\n"):
            new_lines.append("\n")
        new_lines.append(f"GEMINI_API_KEY={key}\n")
    
    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)
    os.environ["GEMINI_API_KEY"] = key
    return {"message": "API Key updated successfully"}

# --- GESTIONE ESECUZIONE AUDIOTTO IN THREAD ---
class OutputCapture(object):
    """ Classe per catturare stdout e inviarlo al WebSocket """
    def __init__(self, loop, websocket):
        self.loop = loop
        self.websocket = websocket

    def write(self, data):
        if data.strip():
            # Invia il log al websocket in modo thread-safe
            asyncio.run_coroutine_threadsafe(self.websocket.send_text(data.strip()), self.loop)

    def flush(self):
        pass

def run_audiotto_wrapper(args, loop, websocket):
    """ Esegue AudioTTo catturando l'output """
    
    # 🔹 SYNC: Aggiorniamo la variabile globale del modulo AudioTTo con la chiave corrente
    current_key = os.getenv("GEMINI_API_KEY")
    if current_key:
        AudioTTo.GEMINI_API_KEY = current_key

    capture = OutputCapture(loop, websocket)
    # Redirige stdout e stderr verso il websocket
    with redirect_stdout(capture), redirect_stderr(capture):
        try:
            AudioTTo.main(args)
        except Exception as e:
            print(f"❌ Critical Error: {e}")

@app.websocket("/ws/process")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        data = await websocket.receive_json()
        audio_filename = data.get("audio_filename")
        slides_filename = data.get("slides_filename")
        pages = data.get("pages")
        
        if not audio_filename:
            await websocket.send_text("❌ Error: No audio file specified.")
            await websocket.close()
            return
        
        # 🔹 CONTROLLO API KEY: Se non c'è la chiave, blocchiamo tutto subito
        qa_key = os.getenv("GEMINI_API_KEY")
        if not qa_key or not qa_key.strip():
             await websocket.send_text("❌ Error: API Key missing! Please set it in the Settings tab.")
             await websocket.close()
             return

        audio_path = os.path.join("temp_uploads", audio_filename)
        
        # Costruiamo la lista di argomenti da passare a AudioTTo
        cmd_args = [audio_path]
        if slides_filename:
            cmd_args.extend(["--slides", os.path.join("temp_uploads", slides_filename)])
        if pages:
            cmd_args.extend(["--pages", pages])

        await websocket.send_text(f"🚀 Starting processing...")

        # Eseguiamo in un thread separato per non bloccare il server
        loop = asyncio.get_event_loop()
        await asyncio.to_thread(run_audiotto_wrapper, cmd_args, loop, websocket)
        
        await websocket.send_text("✅ Process completed check log above.")
        await websocket.send_text("REFRESH_OUTPUTS")

    except WebSocketDisconnect:
        print("Client disconnected")
    except Exception as e:
        await websocket.send_text(f"❌ Internal error: {str(e)}")
    finally:
        try:
            await websocket.close()
        except:
            pass

@app.post("/upload")
async def upload_file_endpoint(file: UploadFile = File(...)):
    file_location = os.path.join("temp_uploads", file.filename)
    with open(file_location, "wb+") as file_object:
        shutil.copyfileobj(file.file, file_object)
    return {"filename": file.filename}

# --- INIZIO NUOVO BLOCCO IF NAME == MAIN PER GUI_APP.PY ---

def start_server():
    """ Avvia il server Uvicorn in un thread separato """
    # log_level="error" riduce il rumore nella console
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")

if __name__ == "__main__":
    import multiprocessing
    import threading
    import webview  # Importiamo pywebview

    # Fix per PyInstaller su Windows
    multiprocessing.freeze_support()
    
    # 1. Avvia il server FastAPI in un thread parallelo (Demone = si chiude quando chiudi l'app)
    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()

    # 2. Crea la finestra desktop "nativa"
    # width e height sono le dimensioni iniziali
    webview.create_window(
        title='AudioTTo - Notes generator', 
        url='http://127.0.0.1:8000',
        width=1000,
        height=800,
        resizable=True
    )

    # 3. Avvia la GUI
    try:
        webview.start()
    except KeyboardInterrupt:
        print("\n🛑 Application stopped by user.")
        sys.exit(0)

# --- FINE NUOVO BLOCCO ---