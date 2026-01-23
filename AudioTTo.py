import os
import sys

# --- FIX WINDOWS ENCODING (Moved to main execution to avoid conflicts) ---
# Logic moved to ensure gui_app.py's logger is prioritized when imported
# ------------------------------------------------------------
def safe_print(text):
    try: print(text)
    except: pass

import subprocess
import argparse
from pydub import AudioSegment
from faster_whisper import WhisperModel
import google.genai as genai
from google.genai import types
import multiprocessing
import warnings
import time
from typing import List
from dotenv import load_dotenv
import threading
from tqdm import tqdm
import fitz 

# --- CONFIGURAZIONE PATH E BINARI ---

def resource_path(relative_path):
    """ Ottiene il percorso assoluto delle risorse, funzionante sia in Dev che in EXE (PyInstaller) """
    if hasattr(sys, '_MEIPASS'):
        # PyInstaller crea una cartella temporanea in _MEIPASS
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)

def configure_ffmpeg():
    """ Configura pydub per usare ffmpeg incluso nel pacchetto """
    
    # Determina i nomi dei file in base all'OS
    if sys.platform == "win32":
        ffmpeg_name = "ffmpeg.exe"
        ffprobe_name = "ffprobe.exe"
    else:
        ffmpeg_name = "ffmpeg"
        ffprobe_name = "ffprobe"

    # PyInstaller con il nostro spec mette i file nella root o in bin/ (dipende dal dest in spec)
    # Nel build.spec abbiamo messo destination='.', quindi sono nella root di _MEIPASS
    ffmpeg_path = resource_path(ffmpeg_name)
    ffprobe_path = resource_path(ffprobe_name)

    # Fallback: Se non siamo in EXE e i file non sono nella root, cerchiamo in bin/ (per sviluppo)
    if not os.path.exists(ffmpeg_path):
        ffmpeg_path = resource_path(os.path.join("bin", ffmpeg_name))
        ffprobe_path = resource_path(os.path.join("bin", ffprobe_name))

    # Configura Pydub
    if os.path.exists(ffmpeg_path):
        AudioSegment.converter = ffmpeg_path
        AudioSegment.ffprobe = ffprobe_path
        # Aggiungi al PATH di sistema per subprocess calls dirette
        os.environ["PATH"] += os.pathsep + os.path.dirname(ffmpeg_path)
    else:
        safe_print("⚠️ Warning: FFmpeg binaries not found in bundle. Using system default.")

# Logger Setup
logger_callback = None
progress_queue = None

def set_logger(callback):
    global logger_callback
    logger_callback = callback

def log(*args, **kwargs):
    msg = " ".join(map(str, args))
    if logger_callback:
        logger_callback(msg)
    else:
        print(msg, flush=True, **kwargs)

class ProgressLogger:
    def write(self, buf):
        if buf.strip():
            if logger_callback:
                logger_callback(buf)
            else:
                sys.stderr.write(buf)
                sys.stderr.flush()
    def flush(self):
        if not logger_callback:
            sys.stderr.flush()

warnings.filterwarnings("ignore", category=UserWarning, module='ctranslate2')

# Load environment variables
load_dotenv()

# --- ESEGUIAMO LA CONFIGURAZIONE ---
configure_ffmpeg() 

# ---------------- CONFIG ----------------
MODEL_SIZE = "small"
COMPUTE_TYPE = "int8"
LANGUAGE = None  
N_THREADS = 4
CHUNK_LENGTH_MS_LOCAL = 10 * 60 * 1000
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
model = "gemini-3-flash-preview"
model_worker = None

def init_worker(queue=None):
    global model_worker, progress_queue
    model_worker = WhisperModel(MODEL_SIZE, device="cpu", compute_type=COMPUTE_TYPE)
    if queue:
        progress_queue = queue


# ---------------- SLIDES PROCESSING ----------------
def process_slides(slides_path: str, pages_range: str = None) -> any:
    """
    Checks if PDF exists and handles page slicing if a range is provided.
    Returns the path to the file to uplad (original or temporary sliced).
    """
    if not slides_path or not os.path.exists(slides_path):
        log("⚠️  Slides path not provided or does not exist.")
        return None

    log(f"📄 Slides detected: {slides_path}")
    
    if not pages_range:
        return slides_path

    # Handle page slicing
    try:
        log(f"✂️  Extracting page range: {pages_range}")
        doc = fitz.open(slides_path)
        
        # Parse range (e.g., "1-5")
        start_page, end_page = 0, len(doc) - 1
        parts = pages_range.split('-')
        if len(parts) >= 1 and parts[0].strip():
            start_page = int(parts[0]) - 1
        if len(parts) >= 2 and parts[1].strip():
            end_page = int(parts[1]) - 1
        
        # Validate bounds
        start_page = max(0, start_page)
        end_page = min(len(doc) - 1, end_page)

        if start_page > end_page:
            log(f"⚠️ Invalid range {start_page+1}-{end_page+1}. Using full PDF.")
            doc.close()
            return slides_path

        # Create new PDF with selected pages
        output_dir = os.path.dirname(slides_path) or "."
        base_name = os.path.splitext(os.path.basename(slides_path))[0]
        sliced_path = os.path.join(output_dir, f"{base_name}_pages_{start_page+1}-{end_page+1}.pdf")
        
        new_doc = fitz.open()
        new_doc.insert_pdf(doc, from_page=start_page, to_page=end_page)
        new_doc.save(sliced_path)
        new_doc.close()
        doc.close()
        
        print(f"   - Created temporary sliced PDF: {sliced_path}")
        return sliced_path

    except Exception as e:
        log(f"❌ Error during PDF slicing: {e}. Using original file.")
        return slides_path


# ---------------- AUDIO FUNCTIONS ----------------
def create_output_folder(audio_path: str) -> str:
    base_name = os.path.splitext(os.path.basename(audio_path))[0]
    output_dir = os.path.join("output", base_name)
    os.makedirs(output_dir, exist_ok=True)
    return output_dir


def split_audio(audio_path: str, chunk_len_ms: int, output_dir: str) -> list:
    log(f"🔪 Splitting audio into {chunk_len_ms // 60000}-minute chunks...")
    
    # WORKAROUND: pydub requires ffprobe for non-wav files, but imageio-ffmpeg only provides ffmpeg.
    # We manually convert to WAV using the available ffmpeg binary to avoid WinError 2.
    temp_wav = os.path.join(output_dir, "temp_conversion.wav")
    
    try:
        # Check if already wav to skip conversion (optional, but safer to just normalize)
        if not audio_path.lower().endswith(".wav"):
            log("   - Converting to WAV for processing...")
            cmd = [
                AudioSegment.converter,
                "-y", # Overwrite
                "-i", audio_path,
                "-ac", "1", # Mono
                "-ar", "16000", # 16kHz (optimal for Whisper)
                temp_wav
            ]
            
            # Run ffmpeg, suppress output unless error
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            audio_source = temp_wav
        else:
            audio_source = audio_path

        # Now load from WAV (native python support, no ffprobe needed)
        audio = AudioSegment.from_wav(audio_source)

    except subprocess.CalledProcessError as e:
        log(f"❌ FFmpeg conversion failed: {e}")
        # Try fall back to direct load if conversion failed? Most likely will fail again but worth a shot
        audio = AudioSegment.from_file(audio_path)
    except Exception as e:
        log(f"⚠️ Error loading audio: {e}. Trying callback...")
        audio = AudioSegment.from_file(audio_path)

    chunks = []
    for i in range(0, len(audio), chunk_len_ms):
        chunk = audio[i:i+chunk_len_ms]
        chunk_path = os.path.join(output_dir, f"chunk_{i//chunk_len_ms}.wav")
        chunk.export(chunk_path, format="wav")
        chunks.append(chunk_path)
    
    
    # Cleanup temp wav
    if os.path.exists(temp_wav):
        try:
            os.remove(temp_wav)
        except:
            pass
            
    log(f"✔️ Audio split into {len(chunks)} chunks.")
    return chunks


def transcribe_chunk_worker(chunk_path: str):
    # Use Segments to track progress
    segments, info = model_worker.transcribe(chunk_path, language=LANGUAGE)
    
    full_text = []
    try:
        for segment in segments:
            full_text.append(segment.text)
            # Send progress (duration of segment) to main process
            if progress_queue:
                duration = segment.end - segment.start
                progress_queue.put(duration)
    except Exception as e:
        # In case of error, just log and continue/return partial
        pass
        
    return " ".join(full_text), info.language


def transcribe_chunks_local_parallel(chunks: list, num_workers: int):
    log(f"🚀 Starting parallel transcription on {num_workers} CPU cores...")

    texts = []
    langs = []

    # Usa tqdm per mostrare la barra di avanzamento
    # file=ProgressLogger() reindirizza l'output al nostro callback (WebSocket o Stderr)

    # 1. Calcola durata totale REALE per la progress bar
    # Invece di stimare, misuriamo la durata dei chunk generati.
    # pydub.AudioSegment.from_file(chunk_path).duration_seconds è preciso ma lento se riapriamo.
    # Ma dato che `split_audio` è appena finito, possiamo assumere che i chunk siano corretti.
    # Facciamo una lettura rapida dei file wav (headers).
    import wave
    total_estimated_seconds = 0.0
    for c in chunks:
        try:
            with wave.open(c, 'r') as f:
                frames = f.getnframes()
                rate = f.getframerate()
                total_estimated_seconds += frames / float(rate)
        except:
            # Fallback a stima se non è un wav standard o errore
            total_estimated_seconds += (CHUNK_LENGTH_MS_LOCAL / 1000)
    
    log(f"Duration calculated: {total_estimated_seconds:.2f}s")
    
    manager = multiprocessing.Manager()
    queue = manager.Queue()
    
    # Thread per monitorare la queue e aggiornare tqdm
    def monitor_progress(q, total_sec):
        # Use simple block characters for cleaner UI
        pbar = tqdm(total=total_sec, file=ProgressLogger(), desc="Transcribing", unit="s", 
                   bar_format="{l_bar}{bar}| {n:.1f}/{total_fmt} [{elapsed}<{remaining}]",
                   ascii=" █")
        processed_sec = 0
        while True:
            try:
                # Blocca per un po', se niente arriva controlla se main ha finito (ma qui usiamo sentinel o daemon)
                # Semplifichiamo: usiamo timeout e un flag esterno o sentinel
                duration = q.get(timeout=0.5)
                if duration == "DONE":
                    # Force update to 100% (handle silence skipping)
                    remaining = total_sec - pbar.n
                    if remaining > 0:
                        pbar.update(remaining)
                    break
                pbar.update(duration)
                processed_sec += duration
            except Exception: # Empty
                if all_done_event.is_set():
                    # Same cleanup if event triggers finish
                    remaining = total_sec - pbar.n
                    if remaining > 0:
                        pbar.update(remaining)
                    break
        pbar.close()

    all_done_event = threading.Event()
    monitor_thread = threading.Thread(target=monitor_progress, args=(queue, total_estimated_seconds))
    monitor_thread.start()

    try:
        with multiprocessing.Pool(processes=num_workers, initializer=init_worker, initargs=(queue,)) as pool:
            # Non usiamo più tqdm qui direttamente come wrapper, lasciamo fare al thread monitor
            results = pool.map(transcribe_chunk_worker, chunks)
            
            for text, lang in results:
                texts.append(text)
                langs.append(lang)
    finally:
        all_done_event.set()
        # Ensure monitor thread finishes
        queue.put("DONE") 
        monitor_thread.join() 

    from collections import Counter
    final_lang = Counter(langs).most_common(1)[0][0]

    return " ".join(texts).strip(), final_lang


# ---------------- DOCUMENT GENERATION ----------------
def generate_latex_document(text: str, title: str, slides_path: str, audio_lang: str) -> str:
    if not GEMINI_API_KEY:
        log("❌ Gemini API Key not found.")
        return ""

    log("🧠 Generating LaTeX document with Gemini (v3)...")
    
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        
        prompt_parts = []
        
        # 1. Base System Instructions
        base_prompt = f"""
You are an expert assistant that creates complete, clear, academic LaTeX lesson notes.

IMPORTANT RULES:
- The output MUST start with `\\documentclass[12pt]{{article}}` and MUST end with `\\end{{document}}`.
- DO NOT include explanations, comments, markdown code blocks, or introductory text.
- DO NOT include an abstract section.
- You must write the entire document in the SAME LANGUAGE as the transcription. The detected language is: {audio_lang}.
- Use only standard LaTeX packages: geometry, amsmath, graphicx, helvet, inputenc (utf8).
- Reformulate sentences to be clear, well-organized, and academic.
- Use logical sections and subsections.
- Add a final summary section.

Document Title:
Lecture Notes: {title.replace('_', ' ')}

TRANSCRIPTION:
{text}
"""
        prompt_parts.append(base_prompt)

        # 2. Add PDF file if available
        if slides_path:
            log(f"   - Uploading PDF to Gemini: {os.path.basename(slides_path)}")
            # Upload file to Gemini
            with open(slides_path, "rb") as f:
                uploaded_file = client.files.upload(file=f, config={'mime_type': 'application/pdf'})
            
            log(f"   - PDF Uploaded (URI: {uploaded_file.uri})")
            prompt_parts.append("Refer to the attached PDF slides for context, diagrams, and structure.")
            prompt_parts.append(uploaded_file)
        else:
            log("   - Sending transcription only.")

        # 3. Generate Content
        response = client.models.generate_content(
            model=model,
            contents=prompt_parts,
            config=types.GenerateContentConfig(
                safety_settings=[
                    types.SafetySetting(
                        category="HARM_CATEGORY_HATE_SPEECH",
                        threshold="BLOCK_NONE"
                    ),
                    types.SafetySetting(
                        category="HARM_CATEGORY_DANGEROUS_CONTENT",
                        threshold="BLOCK_NONE"
                    ),
                    types.SafetySetting(
                        category="HARM_CATEGORY_SEXUALLY_EXPLICIT",
                        threshold="BLOCK_NONE"
                    ),
                    types.SafetySetting(
                        category="HARM_CATEGORY_HARASSMENT",
                        threshold="BLOCK_NONE"
                    ),
                ]
            )
        )
        
        # Check for safety blocks or empty response
        if not response.text:
             log(f"⚠️ Gemini response was empty. Feedback: {response.prompt_feedback if hasattr(response, 'prompt_feedback') else 'Unknown'}")
             # Tenta di prendere candidati se esistono
             if response.candidates:
                 log(f"⚠️ Candidates found: {len(response.candidates)}. Finish reason: {response.candidates[0].finish_reason}")
             return ""

        latex = response.text.strip()

        if "\\documentclass" in latex:
            latex = latex[latex.find("\\documentclass"):]
        if "\\end{document}" in latex:
            latex = latex[:latex.rfind("\\end{document}") + len("\\end{document}")]

        return latex



    except Exception as e:
        log(f"❌ Error during Gemini request: {e}")
        return ""


def review_latex_content(latex_code: str) -> str:
    if not GEMINI_API_KEY:
        return latex_code

    log("🧠 Reviewing content and code with Gemini (Expert Mode)...")
    
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        
        prompt = f"""
You are an expert academic professor and technical reviewer.
Your goal is to refine the following LaTeX document.

1. **Conceptual & Scientific Accuracy**: 
   - Read the content critically. 
   - Identify any scientific, medical, or mathematical errors (e.g., incorrect formulas, misspelled drug names, wrong definitions). 
   - **CORRECT ONLY THE ERRORS** based on your expert knowledge. Do not ask for clarification, just fix it to the scientifically correct version.

2. **LaTeX Validity**: 
   - Ensure all code is valid and compiles without errors. 
   - Fix any broken environments, unclosed brackets, or invalid math syntax.

LaTeX to Review:
{latex_code}

Output ONLY the corrected LaTeX document, starting with \\documentclass...
"""

        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                safety_settings=[
                    types.SafetySetting(
                        category="HARM_CATEGORY_HATE_SPEECH",
                        threshold="BLOCK_NONE"
                    ),
                    types.SafetySetting(
                        category="HARM_CATEGORY_DANGEROUS_CONTENT",
                        threshold="BLOCK_NONE"
                    ),
                    types.SafetySetting(
                        category="HARM_CATEGORY_SEXUALLY_EXPLICIT",
                        threshold="BLOCK_NONE"
                    ),
                    types.SafetySetting(
                        category="HARM_CATEGORY_HARASSMENT",
                        threshold="BLOCK_NONE"
                    ),
                ]
            )
        )

        if not response.text:
            log("⚠️ Review response empty. Using original draft.")
            return latex_code
            
        reviewed_latex = response.text.strip()
        
        # Cleanup markdown formatting if present
        if "\\documentclass" in reviewed_latex:
            reviewed_latex = reviewed_latex[reviewed_latex.find("\\documentclass"):]
        if "\\end{document}" in reviewed_latex:
            reviewed_latex = reviewed_latex[:reviewed_latex.rfind("\\end{document}") + len("\\end{document}")]
            
        return reviewed_latex

    except Exception as e:
        log(f"⚠️ Error during review: {e}. Using original draft.")
        return latex_code





# ---------------- COMPILATION ----------------
def compile_pdf(tex_path: str) -> bool:
    log("📄 Compiling PDF...")

    output_dir, file_name = os.path.split(tex_path)

    for _ in range(2):  # run twice
        try:
            subprocess.run(
                ["pdflatex", "-interaction=nonstopmode", file_name],
                check=True, cwd=output_dir, capture_output=True
            )
        except Exception as e:
            log(f"❌ PDF compilation failed: {e}")
            return False

    log("✅ PDF successfully generated.")
    return True


def cleanup_output(output_dir: str, base_name: str):
    log("\n🧹 Final cleanup...")

    keep_files = [
        f"{base_name}_appunti.tex",
        f"{base_name}_appunti.pdf",
        f"{base_name}_trascrizione.txt"
    ]

    for filename in os.listdir(output_dir):
        if filename not in keep_files:
            try:
                os.remove(os.path.join(output_dir, filename))
                log(f"   - Removed temporary file: {filename}")
            except Exception as e:
                log(f"   - Error deleting {filename}: {e}")

    log("✔️ Cleanup completed.")


# ---------------- MAIN ----------------
def main(args_list=None):
    log("🚀 Initializing AudioTTo...")
    start_time = time.time()

    parser = argparse.ArgumentParser(description="Transcribes audio and generates LaTeX/PDF notes with optional PDF slides.")
    parser.add_argument("file_audio", help="Path to the audio file.")
    parser.add_argument("--slides", help="Path to PDF slides.")
    parser.add_argument("--pages", help="Page range (e.g., '5-12').")
    parser.add_argument("--threads", type=int, default=N_THREADS)
    
    # MODIFICA: Se args_list è popolato (chiamata dalla GUI), usa quello.
    # Altrimenti, se è None, argparse leggerà automaticamente sys.argv (chiamata da terminale).
    if args_list:
        args = parser.parse_args(args_list)
    else:
        args = parser.parse_args()

    # Creazione cartelle e inizializzazione variabili
    output_dir = create_output_folder(args.file_audio)
    base_name = os.path.splitext(os.path.basename(args.file_audio))[0]
    temp_files = []
    succeeded = False

    try:
        # 1. Elaborazione Slide
        slides_images = process_slides(args.slides, args.pages)

        # 2. Pulizia Audio (Denoising)
        # 2. (Skipped) Pulizia Audio (Denoising rimosso come richiesto)
        # clean_audio = denoise_audio(args.file_audio, output_dir)
        # temp_files.append(clean_audio)

        # 3. Splitting Audio in chunk
        chunks = split_audio(args.file_audio, CHUNK_LENGTH_MS_LOCAL, output_dir)
        temp_files.extend(chunks)

        # 4. Trascrizione (Parallela se ci sono chunk multipli)
        num_workers = min(args.threads, len(chunks)) if chunks else 0
        transcript, audio_lang = transcribe_chunks_local_parallel(chunks, num_workers)

        if not transcript.strip():
            log("⚠️ Transcription is empty. Stopping.")
            return

        # 5. Salvataggio file di testo trascrizione
        transcript_file = os.path.join(output_dir, f"{base_name}_trascrizione.txt")
        with open(transcript_file, "w", encoding="utf-8") as f:
            f.write(transcript)
        log(f"💾 Transcription saved at: {transcript_file}")
        log(f"🌍 Detected language: {audio_lang}")

        # 6. Generazione LaTeX tramite LLM (Gemini)
        latex_doc = generate_latex_document(transcript, base_name, slides_images, audio_lang)

        if latex_doc:
            # 6b. Revisione Automatica (Convalida Concettuale e Codice)
            latex_doc = review_latex_content(latex_doc)
            
            tex_path = os.path.join(output_dir, f"{base_name}_appunti.tex")
            with open(tex_path, "w", encoding="utf-8") as f:
                f.write(latex_doc)

            log(f"📝 LaTeX file created: {tex_path}")

            # 7. Compilazione PDF (pdflatex)
            if compile_pdf(tex_path):
                succeeded = True
        else:
            log("❌ Failed to generate LaTeX document (AI response was empty or error).")

    except Exception as e:
        # Cattura errori generici per evitare crash silenziosi della GUI
        log(f"❌ Critical Error during execution: {e}")

    finally:
        # Pulizia file temporanei audio
        log("\n🧹 Removing intermediate audio files...")
        for f_path in temp_files:
            try:
                if os.path.exists(f_path):
                    os.remove(f_path)
            except Exception as e:
                log(f"   - Error deleting {f_path}: {e}")

        # Pulizia file temporanei LaTeX
        log("🧹 Cleaning LaTeX compilation files...")
        for ext in ['.aux', '.log', '.out', '.fls', '.fdb_latexmk']:
            tmp = os.path.join(output_dir, f"{base_name}_appunti{ext}")
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
                    log(f"   - Removed: {os.path.basename(tmp)}")
            except Exception as e:
                log(f"   - Error deleting {tmp}: {e}")

        # Pulizia finale cartella output (se successo, cancella anche tex e txt per ordine, se vuoi)
        if succeeded:
            cleanup_output(output_dir, base_name)

    total_seconds = int(time.time() - start_time)
    log(f"\n⏱️ Total time: {total_seconds // 60} min {total_seconds % 60} sec")
    log(f"🎉 Process completed. Final files are in: {output_dir}")


if __name__ == "__main__":
    # Fix obbligatorio per Multiprocessing su Windows quando si crea un EXE
    # Also apply encoding fix for standalone execution
    if sys.platform == "win32":
        os.environ["PYTHONIOENCODING"] = "utf-8"
        if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
            try: sys.stdout.reconfigure(encoding='utf-8', errors='replace')
            except: pass
        if sys.stderr and hasattr(sys.stderr, 'reconfigure'):
            try: sys.stderr.reconfigure(encoding='utf-8', errors='replace')
            except: pass
    # Fix obbligatorio per Multiprocessing su Windows quando si crea un EXE
    if sys.platform in ["win32", "darwin"]:
        multiprocessing.freeze_support()
        multiprocessing.set_start_method('spawn', force=True)
    main()
