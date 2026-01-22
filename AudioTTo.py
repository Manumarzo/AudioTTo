import os
import sys
import subprocess
import argparse
from pydub import AudioSegment
import imageio_ffmpeg as ffmpeg
from faster_whisper import WhisperModel
import google.genai as genai
import multiprocessing
import warnings
import time
from typing import List
from dotenv import load_dotenv

import fitz  # PyMuPDF for PDF manipulation
# import PIL.Image  # Removed as we upload PDF directly now

# Force UTF-8 encoding on Windows (Only if console exists)
if sys.platform == "win32":
    # Controlliamo se stdout esiste prima di toccarlo
    if sys.stdout is not None:
        try:
            sys.stdout.reconfigure(encoding='utf-8')
        except AttributeError:
            pass # Ignora se non supportato

    # Controlliamo se stderr esiste prima di toccarlo
    if sys.stderr is not None:
        try:
            sys.stderr.reconfigure(encoding='utf-8')
        except AttributeError:
            pass # Ignora se non supportato

warnings.filterwarnings("ignore", category=UserWarning, module='ctranslate2')

# Load environment variables
load_dotenv()

def add_ffmpeg_path():
    """ Aggiunge il path dei binari ffmpeg compressi nel PATH di sistema se congelato """
    if getattr(sys, 'frozen', False):
        base_path = sys._MEIPASS
        # Aggiungiamo il path corrente (dove si trovano ffmpeg.exe e ffprobe.exe estratti)
        os.environ["PATH"] += os.pathsep + base_path
        
        # Opzionale: se pydub non lo trova automaticamente, potremmo forzarlo qui
        # Ma di solito basta il PATH.

# Eseguiamo subito
add_ffmpeg_path()

# ---------------- CONFIG ----------------
MODEL_SIZE = "small"
COMPUTE_TYPE = "int8"
LANGUAGE = None  # Auto-detect language
N_THREADS = 4
CHUNK_LENGTH_MS_LOCAL = 10 * 60 * 1000
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
model = "gemini-3-flash"
AudioSegment.converter = ffmpeg.get_ffmpeg_exe()
model_worker = None


def init_worker():
    global model_worker
    model_worker = WhisperModel(MODEL_SIZE, device="cpu", compute_type=COMPUTE_TYPE)


# ---------------- SLIDES PROCESSING ----------------
def process_slides(slides_path: str, pages_range: str = None) -> any:
    """
    Checks if PDF exists and handles page slicing if a range is provided.
    Returns the path to the file to uplad (original or temporary sliced).
    """
    if not slides_path or not os.path.exists(slides_path):
        print("⚠️  Slides path not provided or does not exist.")
        return None

    print(f"📄 Slides detected: {slides_path}")
    
    if not pages_range:
        return slides_path

    # Handle page slicing
    try:
        print(f"✂️  Extracting page range: {pages_range}")
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
            print(f"⚠️ Invalid range {start_page+1}-{end_page+1}. Using full PDF.")
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
        print(f"❌ Error during PDF slicing: {e}. Using original file.")
        return slides_path


# ---------------- AUDIO FUNCTIONS ----------------
def create_output_folder(audio_path: str) -> str:
    base_name = os.path.splitext(os.path.basename(audio_path))[0]
    output_dir = os.path.join("output", base_name)
    os.makedirs(output_dir, exist_ok=True)
    return output_dir


def split_audio(audio_path: str, chunk_len_ms: int, output_dir: str) -> list:
    print(f"🔪 Splitting audio into {chunk_len_ms // 60000}-minute chunks...")
    audio = AudioSegment.from_file(audio_path)
    chunks = []
    for i in range(0, len(audio), chunk_len_ms):
        chunk = audio[i:i+chunk_len_ms]
        chunk_path = os.path.join(output_dir, f"chunk_{i//chunk_len_ms}.wav")
        chunk.export(chunk_path, format="wav")
        chunks.append(chunk_path)
    print(f"✔️ Audio split into {len(chunks)} chunks.")
    return chunks


def transcribe_chunk_worker(chunk_path: str):
    segments, info = model_worker.transcribe(chunk_path, language=LANGUAGE)
    text = " ".join(s.text for s in segments)
    return text, info.language  # Return transcription + detected language


def transcribe_chunks_local_parallel(chunks: list, num_workers: int):
    print(f"🚀 Starting parallel transcription on {num_workers} CPU cores...")

    texts = []
    langs = []

    with multiprocessing.Pool(processes=num_workers, initializer=init_worker) as pool:
        for chunk_path, (text, lang) in zip(chunks, pool.map(transcribe_chunk_worker, chunks)):
            texts.append(text)
            langs.append(lang)
            print(f"   - Chunk {os.path.basename(chunk_path)} completed (language detected: {lang}).", flush=True)

    from collections import Counter
    final_lang = Counter(langs).most_common(1)[0][0]

    return " ".join(texts).strip(), final_lang


# ---------------- DOCUMENT GENERATION ----------------
def generate_latex_document(text: str, title: str, slides_path: str, audio_lang: str) -> str:
    if not GEMINI_API_KEY:
        print("❌ Gemini API Key not found.")
        return ""

    print("🧠 Generating LaTeX document with Gemini (v2.5)...")
    
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        
        prompt_parts = []
        
        # 1. Base System Instructions
        base_prompt = f"""
You are an expert assistant that creates complete, clear, academic LaTeX lesson notes.

IMPORTANT RULES:
- The output MUST start with `\\documentclass{{article}}` and MUST end with `\\end{{document}}`.
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
            print(f"   - Uploading PDF to Gemini: {os.path.basename(slides_path)}")
            # Upload file to Gemini
            with open(slides_path, "rb") as f:
                uploaded_file = client.files.upload(f, config={'mime_type': 'application/pdf'})
            
            print(f"   - PDF Uploaded (URI: {uploaded_file.uri})")
            prompt_parts.append("Refer to the attached PDF slides for context, diagrams, and structure.")
            prompt_parts.append(uploaded_file)
        else:
            print("   - Sending transcription only.")

        # 3. Generate Content
        response = client.models.generate_content(
            model=model,
            contents=prompt_parts
        )
        
        latex = response.text.strip()

        if "\\documentclass" in latex:
            latex = latex[latex.find("\\documentclass"):]
        if "\\end{document}" in latex:
            latex = latex[:latex.rfind("\\end{document}") + len("\\end{document}")]

        return latex

    except Exception as e:
        print(f"❌ Error during Gemini request: {e}")
        return ""


# ---------------- COMPILATION ----------------
def compile_pdf(tex_path: str) -> bool:
    print("📄 Compiling PDF...")

    output_dir, file_name = os.path.split(tex_path)

    for _ in range(2):  # run twice
        try:
            subprocess.run(
                ["pdflatex", "-interaction=nonstopmode", file_name],
                check=True, cwd=output_dir, capture_output=True
            )
        except Exception as e:
            print(f"❌ PDF compilation failed: {e}")
            return False

    print("✅ PDF successfully generated.")
    return True


def cleanup_output(output_dir: str, base_name: str):
    print("\n🧹 Final cleanup...")

    keep_files = [
        f"{base_name}_appunti.tex",
        f"{base_name}_appunti.pdf",
        f"{base_name}_trascrizione.txt"
    ]

    for filename in os.listdir(output_dir):
        if filename not in keep_files:
            try:
                os.remove(os.path.join(output_dir, filename))
                print(f"   - Removed temporary file: {filename}")
            except Exception as e:
                print(f"   - Error deleting {filename}: {e}")

    print("✔️ Cleanup completed.")


# ---------------- MAIN ----------------
def main(args_list=None):
    print("🚀 Initializing AudioTTo...", flush=True)
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
            print("⚠️ Transcription is empty. Stopping.")
            return

        # 5. Salvataggio file di testo trascrizione
        transcript_file = os.path.join(output_dir, f"{base_name}_trascrizione.txt")
        with open(transcript_file, "w", encoding="utf-8") as f:
            f.write(transcript)
        print(f"💾 Transcription saved at: {transcript_file}")
        print(f"🌍 Detected language: {audio_lang}")

        # 6. Generazione LaTeX tramite LLM (Gemini)
        latex_doc = generate_latex_document(transcript, base_name, slides_images, audio_lang)

        if latex_doc:
            tex_path = os.path.join(output_dir, f"{base_name}_appunti.tex")
            with open(tex_path, "w", encoding="utf-8") as f:
                f.write(latex_doc)
            print(f"📝 LaTeX file created: {tex_path}")

            # 7. Compilazione PDF (pdflatex)
            if compile_pdf(tex_path):
                succeeded = True
        else:
            print("❌ Failed to generate LaTeX document (AI response was empty or error).")

    except Exception as e:
        # Cattura errori generici per evitare crash silenziosi della GUI
        print(f"❌ Critical Error during execution: {e}")

    finally:
        # Pulizia file temporanei audio
        print("\n🧹 Removing intermediate audio files...")
        for f_path in temp_files:
            try:
                if os.path.exists(f_path):
                    os.remove(f_path)
            except Exception as e:
                print(f"   - Error deleting {f_path}: {e}")

        # Pulizia file temporanei LaTeX
        print("🧹 Cleaning LaTeX compilation files...")
        for ext in ['.aux', '.log', '.out', '.fls', '.fdb_latexmk']:
            tmp = os.path.join(output_dir, f"{base_name}_appunti{ext}")
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
                    print(f"   - Removed: {os.path.basename(tmp)}")
            except Exception as e:
                print(f"   - Error deleting {tmp}: {e}")

        # Pulizia finale cartella output (se successo, cancella anche tex e txt per ordine, se vuoi)
        if succeeded:
            cleanup_output(output_dir, base_name)

    total_seconds = int(time.time() - start_time)
    print(f"\n⏱️ Total time: {total_seconds // 60} min {total_seconds % 60} sec")
    print(f"🎉 Process completed. Final files are in: {output_dir}")


if __name__ == "__main__":
    # Fix obbligatorio per Multiprocessing su Windows quando si crea un EXE
    if sys.platform in ["win32", "darwin"]:
        multiprocessing.freeze_support()
        multiprocessing.set_start_method('spawn', force=True)
    main()
