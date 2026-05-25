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
from concurrent.futures import ThreadPoolExecutor
import numpy as np
from faster_whisper.audio import decode_audio


# ---------------- CONFIG ----------------
MODEL_SIZE = "small"
COMPUTE_TYPE = "int8"
LANGUAGE = None  
N_THREADS = 4
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
model_name = "gemini-3.1-flash-lite-preview"
whisper_model = None


# --- FIX WINDOWS ENCODING ---
if sys.platform == "win32":
    os.environ["PYTHONIOENCODING"] = "utf-8"
    if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
        try: sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        except: pass
    if sys.stderr and hasattr(sys.stderr, 'reconfigure'):
        try: sys.stderr.reconfigure(encoding='utf-8', errors='replace')
        except: pass

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
        try:
            print(msg, flush=True, **kwargs)
        except UnicodeEncodeError:
            try:
                # Fallback to ascii/safe replacement if standard print fails
                enc = sys.stdout.encoding or 'utf-8'
                print(msg.encode(enc, errors='replace').decode(enc), flush=True, **kwargs)
            except:
                pass

class ProgressLogger:
    """ Custom logger for progress output """
    def __init__(self):
        self.first_write = True

    def write(self, buf):
        stripped = buf.strip()
        if stripped:
            if "Transcribing" in stripped:
                if self.first_write:
                    msg = stripped
                    self.first_write = False
                else:
                    msg = "\r" + stripped
            else:
                msg = stripped

            if logger_callback:
                logger_callback(msg)
            else:
                sys.stderr.write(buf)
                sys.stderr.flush()

    def flush(self):
        if not logger_callback:
            sys.stderr.flush()

warnings.filterwarnings("ignore", category=UserWarning, module='ctranslate2')


def init_whisper_model(cpu_threads=N_THREADS):
    """ Initialize the Whisper model natively with optimized multithreading """
    global whisper_model
    threads = max(1, cpu_threads)
    
    # Balance replicas (num_workers) and CPU threads per replica for optimal CPU execution.
    # CTranslate2 scales best on CPU using 2 to 4 threads per replica (due to vectorization scaling).
    if threads <= 2:
        num_workers = 1
        cpu_threads_per_worker = threads
    elif threads <= 4:
        num_workers = 2
        cpu_threads_per_worker = 2
    else:
        # Scale workers up to 8 max to keep memory overhead safe,
        # ensuring each replica gets at least 2 threads, and distributing the rest.
        cpu_threads_per_worker = 2
        num_workers = min(8, threads // 2)
        if num_workers >= 8:
            cpu_threads_per_worker = max(2, threads // 8)
            
    log(f"🧠 Loading Faster-Whisper model ({MODEL_SIZE}) with {num_workers} workers, each using {cpu_threads_per_worker} CPU threads...")
    whisper_model = WhisperModel(
        MODEL_SIZE, 
        device="cpu", 
        compute_type=COMPUTE_TYPE,  # Int8 is optimized for CPU execution
        cpu_threads=cpu_threads_per_worker,
        num_workers=num_workers
    )
    whisper_model.num_workers = num_workers



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


def find_split_points(audio_data, sample_rate=16000, chunk_duration_sec=600, search_window_sec=20):
    """
    Finds optimal split points in audio_data (1D numpy array) to avoid cutting words.
    Looks for the quietest period (lowest energy) in a search window around each chunk boundary.
    """
    total_samples = len(audio_data)
    chunk_samples = chunk_duration_sec * sample_rate
    search_samples = search_window_sec * sample_rate
    
    if total_samples <= chunk_samples:
        return [0, total_samples]
        
    split_points = [0]
    current_pos = chunk_samples
    
    while current_pos < total_samples:
        start_search = max(0, current_pos - search_samples // 2)
        end_search = min(total_samples, current_pos + search_samples // 2)
        
        if end_search - start_search < sample_rate:
            break
            
        window_size = int(0.5 * sample_rate)
        min_energy = float('inf')
        best_split = current_pos
        
        step = int(0.1 * sample_rate)
        for i in range(start_search, end_search - window_size, step):
            energy = np.sum(np.abs(audio_data[i : i + window_size]))
            if energy < min_energy:
                min_energy = energy
                best_split = i + window_size // 2
                
        split_points.append(best_split)
        current_pos = best_split + chunk_samples
        
    split_points.append(total_samples)
    return split_points


def transcribe_audio_native(audio_path: str):
    """ Transcribe audio in parallel using audio chunking and multiple Whisper workers """
    log(f"🚀 Loading and decoding audio file: {audio_path}...")
    
    try:
        audio_data = decode_audio(audio_path, sampling_rate=16000)
    except Exception as e:
        log(f"❌ Failed to decode audio with PyAV: {e}. Falling back to sequential transcription.")
        return transcribe_audio_native_sequential(audio_path)
        
    total_duration = len(audio_data) / 16000
    log(f"⏱️ Audio duration: {total_duration:.2f}s")
    
    split_points = find_split_points(audio_data, sample_rate=16000, chunk_duration_sec=600, search_window_sec=20)
    chunks = [audio_data[split_points[i]:split_points[i+1]] for i in range(len(split_points)-1)]
    num_chunks = len(chunks)
    log(f"🧩 Split audio into {num_chunks} chunks for parallel transcription.")
    
    first_30s = chunks[0][:min(len(chunks[0]), 30 * 16000)]
    try:
        _, info = whisper_model.transcribe(first_30s, beam_size=1)
        detected_lang = info.language
        lang_prob = info.language_probability
    except Exception as e:
        log(f"⚠️ Language detection failed: {e}. Using default language (None).")
        detected_lang = None
        lang_prob = 0.0
        
    log(f"🌍 Detected language: {detected_lang} (probability: {lang_prob:.2f})")
    
    pbar = tqdm(total=total_duration, file=ProgressLogger(), desc="Transcribing", unit="s", 
               bar_format="{l_bar}{bar}| {n:.1f}/{total_fmt} [{elapsed}<{remaining}]",
               ascii=" █")
               
    progress_lock = threading.Lock()
    
    def transcribe_chunk_worker(chunk_idx, chunk_data):
        try:
            segments, _ = whisper_model.transcribe(
                chunk_data,
                language=detected_lang,
                beam_size=5,
                vad_filter=True,
                vad_parameters=dict(min_silence_duration_ms=500)
            )
            
            chunk_text = []
            last_pos = 0
            for segment in segments:
                chunk_text.append(segment.text)
                segment_delta = segment.end - last_pos
                last_pos = segment.end
                with progress_lock:
                    pbar.update(segment_delta)
                    
            chunk_duration = len(chunk_data) / 16000
            if last_pos < chunk_duration:
                with progress_lock:
                    pbar.update(chunk_duration - last_pos)
                    
            return chunk_idx, " ".join(chunk_text).strip()
        except Exception as err:
            log(f"❌ Error transcribing chunk {chunk_idx + 1}: {err}")
            chunk_duration = len(chunk_data) / 16000
            with progress_lock:
                pbar.update(chunk_duration)
            return chunk_idx, ""

    max_workers = getattr(whisper_model, "num_workers", 1)
    log(f"⚡ Transcribing chunks concurrently with up to {max_workers} threads...")
    
    results = [None] * num_chunks
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(transcribe_chunk_worker, idx, chunk) for idx, chunk in enumerate(chunks)]
        for fut in futures:
            idx, text = fut.result()
            results[idx] = text
            
    pbar.close()
    
    full_transcript = " ".join([t for t in results if t]).strip()
    return full_transcript, detected_lang


def transcribe_audio_native_sequential(audio_path: str):
    """ Sequential fallback transcription """
    segments, info = whisper_model.transcribe(
        audio_path, 
        language=LANGUAGE,
        beam_size=5,
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=500)
    )
    
    pbar = tqdm(total=info.duration, file=ProgressLogger(), desc="Transcribing (Seq)", unit="s", 
               bar_format="{l_bar}{bar}| {n:.1f}/{total_fmt} [{elapsed}<{remaining}]",
               ascii=" █")

    full_text = []
    last_pos = 0
    for segment in segments:
        full_text.append(segment.text)
        pbar.update(segment.end - last_pos)
        last_pos = segment.end
        
    if pbar.n < info.duration:
        pbar.update(info.duration - pbar.n)
        
    pbar.close()
    return " ".join(full_text).strip(), info.language


# ---------------- DOCUMENT GENERATION ----------------
def chunk_text_by_words(text: str, chunk_size: int = 3000) -> List[str]:
    words = text.split()
    chunks = []
    for i in range(0, len(words), chunk_size):
        chunks.append(" ".join(words[i:i + chunk_size]))
    return chunks


def save_active_models(model_gen: str = None, model_rev: str = None):
    """ Saves the active model preferences to the .env file so they persist """
    env_path = os.path.join(BASE_DIR, ".env")
    lines = []
    if os.path.exists(env_path):
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except Exception as e:
            log(f"⚠️ Error reading .env file: {e}")
            return
            
    keys_to_update = {}
    if model_gen:
        keys_to_update["MODEL_GENERATION"] = model_gen.strip()
    if model_rev:
        keys_to_update["MODEL_REVISION"] = model_rev.strip()
        
    if not keys_to_update:
        return
        
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
            
    try:
        with open(env_path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
        for k in keys_to_update:
            os.environ[k] = keys_to_update[k]
        log(f"💾 Saved fallback model preferences to .env: {keys_to_update}")
    except Exception as e:
        log(f"⚠️ Error writing .env file: {e}")


def generate_content_with_retry(client, model: str, contents, config, max_retries: int = 3) -> str:
    current_model = model
    delay = 5.0
    
    for attempt in range(max_retries + 1):
        try:
            response = client.models.generate_content(
                model=current_model,
                contents=contents,
                config=config
            )
            return response.text if response.text else ""
        except Exception as e:
            err_str = str(e).lower()
            if any(kw in err_str for kw in ["429", "quota", "exhausted", "limit"]):
                # Pro fallback to Flash
                if "pro" in current_model.lower():
                    fallback_model = "gemini-2.5-flash"
                    log(f"⚠️ Quota exceeded for model {current_model}. Falling back to {fallback_model}...")
                    
                    # Caching fallback selection:
                    model_gen_env = os.getenv("MODEL_GENERATION", "gemini-2.5-flash")
                    model_rev_env = os.getenv("MODEL_REVISION", "gemini-2.5-flash")
                    
                    if model == model_gen_env:
                        save_active_models(model_gen=fallback_model)
                    elif model == model_rev_env:
                        save_active_models(model_rev=fallback_model)
                        
                    current_model = fallback_model
                    try:
                        response = client.models.generate_content(
                            model=current_model,
                            contents=contents,
                            config=config
                        )
                        return response.text if response.text else ""
                    except Exception as fallback_err:
                        err_str = str(fallback_err).lower()
                
                if attempt < max_retries:
                    log(f"⏳ Quota limit hit. Retrying in {delay} seconds (attempt {attempt + 1}/{max_retries})...")
                    time.sleep(delay)
                    delay *= 2
                else:
                    raise e
            else:
                raise e
    return ""


def review_latex_chunk(latex_code: str, audio_lang: str) -> str:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return latex_code

    log("🧠 Reviewing chunk content and code with Gemini (Expert Mode)...")
    
    try:
        client = genai.Client(api_key=api_key)
        model_rev = os.getenv("MODEL_REVISION", "gemini-2.5-flash")
        
        prompt = f"""
You are an expert academic professor and technical reviewer.
Your goal is to refine the following LaTeX document snippet (part of a larger document).

1. **Conceptual & Scientific Accuracy**: 
   - Read the content critically. 
   - Identify any scientific, medical, or mathematical errors (e.g., incorrect formulas, misspelled drug names, wrong definitions). 
   - **CORRECT ONLY THE ERRORS** based on your expert knowledge. Do not ask for clarification, just fix it to the scientifically correct version.

2. **LaTeX Validity**: 
   - Ensure all code is valid and compiles without errors. 
   - Fix any broken environments, unclosed brackets, or invalid math syntax.

LaTeX Snippet to Review:
{latex_code}

Output ONLY the corrected LaTeX snippet. Do not include markdown code blocks (e.g. ```latex), explanations, or comments.
"""

        config = types.GenerateContentConfig(
            safety_settings=[
                types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH", threshold="BLOCK_NONE"),
                types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="BLOCK_NONE"),
                types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="BLOCK_NONE"),
                types.SafetySetting(category="HARM_CATEGORY_HARASSMENT", threshold="BLOCK_NONE"),
            ]
        )

        reviewed_latex = generate_content_with_retry(client, model_rev, prompt, config)
        if not reviewed_latex:
            log("⚠️ Review response empty. Using original snippet.")
            return latex_code
            
        reviewed_latex = reviewed_latex.strip()
        
        # Cleanup markdown formatting if present
        if reviewed_latex.startswith("```"):
            lines = reviewed_latex.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            reviewed_latex = "\n".join(lines).strip()
            
        return reviewed_latex

    except Exception as e:
        log(f"⚠️ Error during snippet review: {e}. Using original snippet.")
        return latex_code


CORE_ACADEMIC_INSTRUCTIONS = """
ADDITIONAL MANDATORY FORMATTING, STYLE & CONTENT RULES (Balanced Academic Style):
1. **Academic Writing Style (Fluid but Dense)**: Formulate detailed explanations of concepts following an academic, clear, and structured editorial style. Complex concepts must be explained in a complete, linear, and accessible manner, using well-written narrative paragraphs to delve into theories and logical passages. Avoid verbal fillers, conversational preambles, fluff, and repetitions typical of spoken speech.
2. **Usage of Lists**: The body text should remain fluid and academic. However, you should use bulleted or numbered lists (such as LaTeX `itemize` or `enumerate`) whenever it helps to clarify classifications, characteristics, step-by-step processes, or structured details, ensuring a clean and legible study layout.
3. **Visual Anchor**: Use bold formatting (`\\textbf{...}`) to highlight key terms and fundamental concepts within the paragraphs to facilitate quick reading and effective studying.
4. **Visual Concepts Integration**: If the audio/slides describe a graph, diagram, schema, or physical/structural system (e.g., double helix, neural network layers, curves), **NEVER try to draw them visually using characters, dashes, or ASCII art**. Instead, integrate their description smoothly into the flow of the text, or isolate them in a standard LaTeX subheading/paragraph (e.g., `\\subsection{Approfondimento Concettuale: ...}` or `\\subsubsection{Approfondimento Concettuale: ...}`), describing their theoretical, architectural, or mathematical meaning in a clean manner.
5. **Fidelity to Audio**: Maintain strict and total adherence to the transcription content. Do not invent details or introduce topics, algorithms, or concepts that were not mentioned by the speaker.
"""


def generate_final_summary(client, model: str, full_body_text: str, audio_lang: str) -> str:
    """
    Generates a final summary section based EXCLUSIVELY on the generated body text.
    """
    log("🧠 Generating final summary from compiled body chapters...")
    prompt = f"""
You are an expert academic professor.
Your task is to write a highly structured, concise final summary section titled exactly `\\section{{Riepilogo}}`.

Here is the complete compiled body of the lecture notes:
---
{full_body_text}
---

CRITICAL SUMMARY RULES:
1. **Title**: The section must start strictly with the title: `\\section{{Riepilogo}}`.
2. **Bold Visual Anchors**: Where appropriate or necessary, use LaTeX bold formatting (`\\textbf{{...}}`) to highlight key terms, fundamental words, or core concepts in the text to make the summary highly legible and easy to skim.
3. **Fewer Bullet Points**: The summary must be written primarily in a concise, fluid narrative format (1 or 2 short paragraphs summarizing the core message, key results, and main takeaways of the lecture). Explain the concepts in a slightly simpler, clearer, and more accessible/straightforward manner compared to the dense academic body text. Avoid overly dense prose while keeping the content scientifically accurate. Limit bullet points (using `\\begin{{itemize}}`) to a maximum of 2 or 3 high-impact, critical items.
4. **Length Control**:
   - The summary must be extremely concise, occupying at most 10-15% of the total document length.
   - Any bullet points used must be short (max 2 lines each).
5. **Consistency & Semantic Alignment**:
   - The summary must ONLY contain concepts, terms, and algorithms that have already been fully explained and detailed in the body text above.
   - It is strictly FORBIDDEN to introduce any new key terms, algorithms, or concepts that were omitted or not explained in the preceding body text.
6. **Language & Output**:
   - The summary must be written in the same language as the notes (detected language: {audio_lang}).
   - Do NOT output any LaTeX preamble or document environment (like `\\begin{{document}}`). Output ONLY the `\\section{{Riepilogo}}` section and its content.
"""
    config = types.GenerateContentConfig(
        safety_settings=[
            types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH", threshold="BLOCK_NONE"),
            types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="BLOCK_NONE"),
            types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="BLOCK_NONE"),
            types.SafetySetting(category="HARM_CATEGORY_HARASSMENT", threshold="BLOCK_NONE"),
        ]
    )
    
    summary_latex = generate_content_with_retry(client, model, prompt, config)
    if summary_latex:
        return review_latex_chunk(summary_latex.strip(), audio_lang)
    return ""



def generate_latex_document(text: str, title: str, slides_path: str, audio_lang: str) -> str:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        log("❌ Gemini API Key not found.")
        return ""

    log("🧠 Generating LaTeX document with Gemini...")
    
    # Get generation model name
    model_gen = os.getenv("MODEL_GENERATION", "gemini-2.5-flash")
    
    # Split text into chunks
    chunks = chunk_text_by_words(text, chunk_size=3000)
    num_chunks = len(chunks)
    log(f"📝 Split transcription into {num_chunks} chunks.")
    
    client = genai.Client(api_key=api_key)
    
    # Upload PDF slide once if available
    uploaded_file = None
    if slides_path:
        try:
            log(f"   - Uploading PDF to Gemini: {os.path.basename(slides_path)}")
            with open(slides_path, "rb") as f:
                uploaded_file = client.files.upload(file=f, config={'mime_type': 'application/pdf'})
            log(f"   - PDF Uploaded (URI: {uploaded_file.uri})")
        except Exception as e:
            log(f"⚠️ Error uploading slides: {e}. Proceeding without slides.")
            
    compiled_body = []
    previous_notes = ""
    
    for i, chunk in enumerate(chunks):
        log(f"🤖 Processing chunk {i+1}/{num_chunks}...")
        
        prompt_parts = []
        is_first = (i == 0)
        is_last = (i == num_chunks - 1)
        
        if is_first:
            prompt = f"""
You are an expert assistant that creates complete, clear, academic LaTeX lesson notes.
We are processing a long lecture in segments. This is PART 1 of the lecture.
Write the LaTeX body content (using \\section, \\subsection, etc.) based on the transcription below.

IMPORTANT RULES:
- DO NOT write preamble, packages, `\\documentclass`, `\\begin{{document}}`, `\\maketitle`, or `\\end{{document}}`.
- Start directly with the first section (e.g. `\\section{{...}}`).
- Use clear formatting, bullet points, and math equations (using amsmath) where appropriate.
- Write the entire content in the same language as the transcription. The detected language is: {audio_lang}.
{CORE_ACADEMIC_INSTRUCTIONS}

TRANSCRIPTION OF PART 1:
{chunk}
"""
        else:
            prompt = f"""
You are an expert assistant that creates complete, clear, academic LaTeX lesson notes.
We are processing a long lecture in segments. This is PART {i+1} of the lecture.
You must write the next part of the LaTeX notes, maintaining consistency in style, terminology, and structure with the previous part.

PREVIOUS PART NOTES (for style and context reference):
---
{previous_notes[-2000:]}
---

IMPORTANT RULES:
- DO NOT write preamble, packages, `\\documentclass`, `\\begin{{document}}`, or `\\end{{document}}`.
- Continue writing sections, subsections, or text.
- Do not repeat sections from the previous part; continue the explanation smoothly.
- Use clear formatting, bullet points, and math equations where appropriate.
- Write the entire content in the same language as the transcription. The detected language is: {audio_lang}.
{CORE_ACADEMIC_INSTRUCTIONS}

TRANSCRIPTION OF PART {i+1}:
{chunk}
"""
        prompt_parts.append(prompt)
        
        if uploaded_file:
            prompt_parts.append("Refer to the attached PDF slides for context, diagrams, and structure.")
            prompt_parts.append(uploaded_file)
            
        try:
            config = types.GenerateContentConfig(
                safety_settings=[
                    types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH", threshold="BLOCK_NONE"),
                    types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="BLOCK_NONE"),
                    types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="BLOCK_NONE"),
                    types.SafetySetting(category="HARM_CATEGORY_HARASSMENT", threshold="BLOCK_NONE"),
                ]
            )
            
            chunk_latex = generate_content_with_retry(client, model_gen, prompt_parts, config)
            if not chunk_latex:
                 log(f"⚠️ Response empty for chunk {i+1}.")
                 continue
                 
            # Review chunk content immediately
            reviewed_chunk = review_latex_chunk(chunk_latex, audio_lang)
            
            # Clean up potential markdown formatting
            if reviewed_chunk.startswith("```"):
                lines = reviewed_chunk.splitlines()
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].startswith("```"):
                    lines = lines[:-1]
                reviewed_chunk = "\n".join(lines).strip()
                
            compiled_body.append(reviewed_chunk)
            previous_notes = reviewed_chunk
            
        except Exception as e:
            log(f"❌ Error generating content for chunk {i+1}: {e}")
            
    if not compiled_body:
        return ""

    # Generate final summary based exclusively on the compiled body content
    full_body_text = "\n\n".join(compiled_body)
    summary_latex = generate_final_summary(client, model_gen, full_body_text, audio_lang)
    if summary_latex:
        # Clean up potential markdown formatting in the summary
        if summary_latex.startswith("```"):
            lines = summary_latex.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            summary_latex = "\n".join(lines).strip()
        compiled_body.append(summary_latex)
        
    clean_title = title.replace('_', ' ')
    full_latex = f"""\\documentclass[12pt]{{article}}
\\usepackage[utf8]{{inputenc}}
\\usepackage{{geometry}}
\\geometry{{a4paper, margin=1in}}
\\usepackage{{amsmath}}
\\usepackage{{amssymb}}
\\usepackage{{graphicx}}
\\usepackage{{helvet}}
\\renewcommand{{\\familydefault}}{{\\sfdefault}}

\\title{{Lecture Notes: {clean_title}}}
\\author{{AudioTTo Notes Generator}}
\\date{{\\today}}

\\begin{{document}}
\\maketitle

{"\n\n".join(compiled_body)}

\\end{{document}}"""

    return full_latex


def review_latex_content(latex_code: str) -> str:
    # Deprecated: review is now done chunk-by-chunk inside generate_latex_document.
    # Return latex_code directly.
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
