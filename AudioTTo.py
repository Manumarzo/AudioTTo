import os
import sys
import subprocess
import argparse
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

# ---------------- CONFIG ----------------
MODEL_SIZE = "small"
COMPUTE_TYPE = "int8"
LANGUAGE = None  
N_THREADS = 4
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
model_name = "gemini-3.1-flash-lite-preview"
whisper_model = None


# --- FIX WINDOWS ENCODING ---
def safe_print(text):
    try: print(text)
    except: pass

# --- PATH CONFIGURATION ---
def get_base_dir():
    """Restituisce la cartella dell'eseguibile o dello script, gestendo i bundle .app di macOS."""
    if getattr(sys, 'frozen', False):
        path = os.path.dirname(sys.executable)
        if ".app/Contents/MacOS" in path:
            return os.path.abspath(os.path.join(path, "../../../"))
        return path
    return os.path.dirname(os.path.abspath(__file__))

BASE_DIR = get_base_dir()

def resource_path(relative_path):
    """ Get the absolute path of the resource, working both in Dev and EXE (PyInstaller) """
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(BASE_DIR, relative_path)

# Carica .env usando il percorso assoluto
load_dotenv(os.path.join(BASE_DIR, ".env"))


# Logger Setup
logger_callback = None

def set_logger(callback):
    global logger_callback
    logger_callback = callback

def log(*args, **kwargs):
    """ Log a message to the console or to the logger callback, usefull for user interactions """
    msg = " ".join(map(str, args))
    if logger_callback:
        logger_callback(msg)
    else:
        print(msg, flush=True, **kwargs)

class ProgressLogger:
    """ Custom logger for progress output """
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


def init_whisper_model(cpu_threads=N_THREADS):
    """ Initialize the Whisper model natively """
    global whisper_model
    log(f"🧠 Loading Faster-Whisper model ({MODEL_SIZE}) with {cpu_threads} threads...")
    whisper_model = WhisperModel(
        MODEL_SIZE, 
        device="cpu", 
        compute_type=COMPUTE_TYPE,
        cpu_threads=cpu_threads,
        num_workers=1 # Single stream
    )


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
    output_dir = os.path.join(BASE_DIR, "output", base_name)
    os.makedirs(output_dir, exist_ok=True)
    return output_dir


def transcribe_audio_native(audio_path: str):
    """ Transcribe audio using the native Faster-Whisper stream with segment-by-segment progress """
    log(f"🚀 Starting transcription...")
    
    segments, info = whisper_model.transcribe(
        audio_path, 
        language=LANGUAGE,
        beam_size=5,
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=500)
    )
    
    log(f"🌍 Detected language: {info.language} (probability: {info.language_probability:.2f})")
    log(f"⏱️ Audio duration: {info.duration:.2f}s")

    pbar = tqdm(total=info.duration, file=ProgressLogger(), desc="Transcribing", unit="s", 
               bar_format="{l_bar}{bar}| {n:.1f}/{total_fmt} [{elapsed}<{remaining}]",
               ascii=" █")

    full_text = []
    last_pos = 0
    
    for segment in segments:
        full_text.append(segment.text)
        # Update progress bar
        pbar.update(segment.end - last_pos)
        last_pos = segment.end
        
    # Ensure progress bar reaches 100% if the last segment ends slightly before info.duration
    if pbar.n < info.duration:
        pbar.update(info.duration - pbar.n)
        
    pbar.close()
    return " ".join(full_text).strip(), info.language


# ---------------- DOCUMENT GENERATION ----------------
def generate_latex_document(text: str, title: str, slides_path: str, audio_lang: str) -> str:
    if not GEMINI_API_KEY:
        log("❌ Gemini API Key not found.")
        return ""

    log("🧠 Generating LaTeX document with Gemini...")
    
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
            model=model_name,
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
            model=model_name,
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
    
    # If args_list is provided, use it; otherwise, use sys.argv
    if args_list:
        args = parser.parse_args(args_list)
    else:
        args = parser.parse_args()

    # Model initialization
    init_whisper_model(cpu_threads=args.threads)

    # Folder creation and variable initialization
    output_dir = create_output_folder(args.file_audio)
    base_name = os.path.splitext(os.path.basename(args.file_audio))[0]
    succeeded = False

    try:
        # 1. Slide processing
        slides_images = process_slides(args.slides, args.pages)

        # 2. Transcription (Native)
        transcript, audio_lang = transcribe_audio_native(args.file_audio)

        if not transcript.strip():
            log("⚠️ Transcription is empty. Stopping.")
            return

        # 3. Saving transcription text file
        transcript_file = os.path.join(output_dir, f"{base_name}_trascrizione.txt")
        with open(transcript_file, "w", encoding="utf-8") as f:
            f.write(transcript)
        log(f"💾 Transcription saved at: {transcript_file}")

        # 4. LaTeX generation through LLM (Gemini)
        latex_doc = generate_latex_document(transcript, base_name, slides_images, audio_lang)

        if latex_doc:
            # 5. Automatic review (Conceptual and Code Validation)
            latex_doc = review_latex_content(latex_doc)
            
            tex_path = os.path.join(output_dir, f"{base_name}_appunti.tex")
            with open(tex_path, "w", encoding="utf-8") as f:
                f.write(latex_doc)

            log(f"📝 LaTeX file created: {tex_path}")

            # 6. PDF compilation (pdflatex)
            if compile_pdf(tex_path):
                succeeded = True
        else:
            log("❌ Failed to generate LaTeX document (AI response was empty or error).")

    except Exception as e:
        # Generic error capture to avoid silent GUI crashes
        log(f"❌ Critical Error during execution: {e}")

    finally:
        # 7. Cleaning LaTeX compilation files
        log("🧹 Cleaning LaTeX compilation files...")
        for ext in ['.aux', '.log', '.out', '.fls', '.fdb_latexmk']:
            tmp = os.path.join(output_dir, f"{base_name}_appunti{ext}")
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
                    log(f"   - Removed: {os.path.basename(tmp)}")
            except Exception as e:
                log(f"   - Error deleting {tmp}: {e}")

        # 8. Final cleanup
        if succeeded:
            cleanup_output(output_dir, base_name)

    total_seconds = int(time.time() - start_time)
    log(f"\n⏱️ Total time: {total_seconds // 60} min {total_seconds % 60} sec")
    log(f"🎉 Process completed. Final files are in: {output_dir}")


if __name__ == "__main__":

    # Fix for Multiprocessing on Windows when creating an EXE
    if sys.platform == "win32":
        os.environ["PYTHONIOENCODING"] = "utf-8"
        if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
            try: sys.stdout.reconfigure(encoding='utf-8', errors='replace')
            except: pass
        if sys.stderr and hasattr(sys.stderr, 'reconfigure'):
            try: sys.stderr.reconfigure(encoding='utf-8', errors='replace')
            except: pass
    
    # Still needed for other potential multiprocessing uses (though GUI app handles it mostly)
    if sys.platform in ["win32", "darwin"]:
        multiprocessing.freeze_support()
        multiprocessing.set_start_method('spawn', force=True)
    
    main()
