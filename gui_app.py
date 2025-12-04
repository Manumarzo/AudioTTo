import os
import shutil
import subprocess
import asyncio
from fastapi import FastAPI, File, UploadFile, Form, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from typing import List, Optional
import glob
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()


app = FastAPI()

# Mount static files (HTML, CSS, JS)
app.mount("/static", StaticFiles(directory="web"), name="static")

# Ensure output directory exists
os.makedirs("output", exist_ok=True)
os.makedirs("temp_uploads", exist_ok=True)

@app.get("/")
async def read_index():
    return FileResponse("web/index.html")

@app.get("/outputs")
async def list_outputs():
    """List all generated PDF files in the output directory."""
    # Pattern: output/<folder>/<file>.pdf
    # We want to find all PDFs inside subdirectories of 'output'
    pdf_files = []
    for root, dirs, files in os.walk("output"):
        for file in files:
            if file.endswith(".pdf"):
                # Create a relative path or a downloadable link structure
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, "output")
                pdf_files.append({
                    "filename": file,
                    "path": rel_path,
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
    """Check if GEMINI_API_KEY is set in .env"""
    # Reload to ensure we catch external changes or initial load issues
    load_dotenv(override=True)
    api_key = os.getenv("GEMINI_API_KEY")
    return {"is_set": bool(api_key)}

@app.post("/api/key")
async def set_api_key(request: ApiKeyRequest):
    """Update GEMINI_API_KEY in .env file"""
    key = request.api_key.strip()
    env_path = ".env"
    
    # Read existing lines
    lines = []
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    
    # Update or append
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
    
    # Update current process environment as well
    os.environ["GEMINI_API_KEY"] = key
    
    return {"message": "API Key updated successfully"}

@app.websocket("/ws/process")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        # 1. Receive configuration and file metadata first (if needed) or just wait for the start signal
        # For simplicity, we might handle the file upload via a separate POST request, 
        # and use the WebSocket ONLY for streaming logs of a specific job.
        # However, to keep it unified, let's assume the client uploads files via POST first, 
        # gets a "job_id" (or just uses a single global lock for this local tool), and then connects to WS.
        
        # SIMPLIFIED APPROACH for local tool:
        # Client sends JSON with filenames (already uploaded) and config.
        data = await websocket.receive_json()
        audio_filename = data.get("audio_filename")
        slides_filename = data.get("slides_filename")
        pages = data.get("pages")
        
        if not audio_filename:
            await websocket.send_text("❌ Error: No audio file specified.")
            await websocket.close()
            return

        audio_path = os.path.join("temp_uploads", audio_filename)
        
        cmd = ["python", "AudioTTo.py", audio_path]
        
        if slides_filename:
            slides_path = os.path.join("temp_uploads", slides_filename)
            cmd.extend(["--slides", slides_path])
            
        if pages:
            cmd.extend(["--pages", pages])
            
        # Set encoding to UTF-8 for the subprocess to handle emojis on Windows
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"

        # Run subprocess and stream output
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env
        )

        await websocket.send_text(f"🚀 Starting command: {' '.join(cmd)}")

        while True:
            line = await process.stdout.readline()
            if not line:
                break
            decoded_line = line.decode('utf-8', errors='replace').strip()
            if decoded_line:
                await websocket.send_text(decoded_line)

        await process.wait()
        
        if process.returncode == 0:
            await websocket.send_text("✅ Process completed successfully!")
            await websocket.send_text("REFRESH_OUTPUTS") # Signal to frontend to refresh list
        else:
            await websocket.send_text(f"❌ Process error (Code {process.returncode})")

    except WebSocketDisconnect:
        print("Client disconnected")
    except Exception as e:
        await websocket.send_text(f"❌ Internal error: {str(e)}")
    finally:
        # Cleanup uploaded files
        try:
            if 'audio_path' in locals() and os.path.exists(audio_path):
                os.remove(audio_path)
            if 'slides_path' in locals() and os.path.exists(slides_path):
                os.remove(slides_path)
        except Exception as e:
            print(f"Error cleaning up files: {e}")

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

if __name__ == "__main__":
    import uvicorn
    # Open browser automatically (optional, user can do it)
    print("Starting server at http://localhost:8000")
    uvicorn.run(app, host="127.0.0.1", port=8000)
