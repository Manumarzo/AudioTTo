# COMANDO DI INSTALLAZIONE:
# pip install librosa soundfile noisereduce pydub imageio-ffmpeg faster-whisper google-generativeai setuptools PyMuPDF Pillow

import os
import sys
import subprocess
import argparse
import librosa
import soundfile as sf
import noisereduce as nr
from pydub import AudioSegment
import imageio_ffmpeg as ffmpeg
from faster_whisper import WhisperModel
import google.generativeai as genai
import multiprocessing
import warnings
import time
from typing import List

# Import specifici per la conversione delle slide
import fitz  # PyMuPDF per i PDF
import PIL.Image

warnings.filterwarnings("ignore", category=UserWarning, module='ctranslate2')

# ---------------- CONFIG ----------------
MODEL_SIZE = "small"
COMPUTE_TYPE = "int8"
LANGUAGE = None
N_THREADS = 4
CHUNK_LENGTH_MS_LOCAL = 10 * 60 * 1000
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") 
AudioSegment.converter = ffmpeg.get_ffmpeg_exe()
model_worker = None

def init_worker():
    global model_worker
    model_worker = WhisperModel(MODEL_SIZE, device="cpu", compute_type=COMPUTE_TYPE)

# ---------------- FUNZIONI SLIDE (SOLO PDF) ----------------
def process_slides(slides_path: str, pages_range: str = None) -> List[PIL.Image.Image]:
    if not slides_path or not os.path.exists(slides_path):
        print("⚠️  Percorso slide non fornito o non esistente.")
        return []

    print(f"🖼️  Processamento delle slide da: {slides_path}")
    images = []
    file_ext = os.path.splitext(slides_path)[1].lower()

    # --- Gestione dei file PDF ---
    if file_ext == '.pdf':
        try:
            doc = fitz.open(slides_path)
            start_page, end_page = 0, len(doc) - 1
            if pages_range:
                try:
                    parts = pages_range.split('-')
                    start_page = int(parts[0]) - 1
                    end_page = int(parts[1]) - 1 if len(parts) > 1 else start_page
                except (ValueError, IndexError):
                    print(f"⚠️ Formato pagine non valido '{pages_range}'. Uso l'intero PDF.")
            
            start_page = max(0, start_page)
            end_page = min(len(doc) - 1, end_page)

            print(f"   - Estraggo le pagine da {start_page + 1} a {end_page + 1}...")
            for i in range(start_page, end_page + 1):
                page = doc.load_page(i)
                pix = page.get_pixmap(dpi=150)
                img = PIL.Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                images.append(img)
            doc.close()
        except Exception as e:
            print(f"❌ Errore durante la conversione del PDF: {e}")
            return []
    else:
        print(f"❌ Formato slide non supportato: {file_ext}. Lo script accetta solo file PDF.")

    if images:
        print(f"✔️  {len(images)} slide processate e pronte per essere inviate a Gemini.")
    return images


# ---------------- FUNZIONI AUDIO (invariate) ----------------
def crea_cartella_output(audio_path: str) -> str:
    base_name = os.path.splitext(os.path.basename(audio_path))[0]
    output_dir = os.path.join("output", base_name)
    os.makedirs(output_dir, exist_ok=True)
    return output_dir

def denoise_audio(input_path: str, output_dir: str) -> str:
    print("🔊 Riduzione rumore in corso...") 
    y, sr = librosa.load(input_path, sr=None)
    y_denoised = nr.reduce_noise(y=y, sr=sr)
    clean_path = os.path.join(output_dir, f"{os.path.splitext(os.path.basename(input_path))[0]}_clean.wav")
    sf.write(clean_path, y_denoised, sr)
    print("✔️ Rumore ridotto.") 
    return clean_path

def split_audio(audio_path: str, chunk_len_ms: int, output_dir: str) -> list:
    print(f"🔪 Divisione dell'audio in chunk da {chunk_len_ms // 60000} minuti...") 
    audio = AudioSegment.from_file(audio_path)
    chunks = []
    for i in range(0, len(audio), chunk_len_ms):
        chunk = audio[i:i+chunk_len_ms]
        chunk_path = os.path.join(output_dir, f"chunk_{i//chunk_len_ms}.wav")
        chunk.export(chunk_path, format="wav")
        chunks.append(chunk_path)
    print(f"✔️ Audio diviso in {len(chunks)} chunk.")
    return chunks

def transcribe_chunk_worker(chunk_path: str) -> str:
    segments, _ = model_worker.transcribe(chunk_path, language=LANGUAGE)
    return " ".join(s.text for s in segments)

def transcribe_chunks_local_parallel(chunks: list, num_workers: int) -> str:
    print(f"🚀 Avvio trascrizione parallela su {num_workers} core della CPU...")
    trascrizioni = []
    with multiprocessing.Pool(processes=num_workers, initializer=init_worker) as pool:
        for chunk_path, testo in zip(chunks, pool.map(transcribe_chunk_worker, chunks)):
            trascrizioni.append(testo)
            print(f"   - Chunk {os.path.basename(chunk_path)} completato e ricevuto nel processo principale.", flush=True)
    return " ".join(trascrizioni).strip()


# ---------------- GENERAZIONE DOCUMENTO ----------------
def genera_documento_latex(testo: str, titolo: str, slides: List[PIL.Image.Image]) -> str:
    if not GEMINI_API_KEY:
        print("❌ Chiave API di Gemini non trovata.")
        return ""
    
    print("🧠 Generazione documento LaTeX con Gemini...")
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel('gemini-2.5-flash')

    # Scegliamo il prompt in base alla presenza delle slide
    if slides:
        # Prompt per TRASCRIZIONE + SLIDE (due fonti)
        prompt_iniziale = f"""
        Sei un assistente esperto nella creazione di documenti LaTeX. Il tuo compito è creare appunti dettagliati e ben strutturati di una lezione.
        Hai a disposizione DUE FONTI: una TRASCRIZIONE testuale e una serie di IMMAGINI delle slide della lezione, 
        usale per integrarle con la trascrizione e creare degli appunti completi.

        REGOLE FONDAMENTALI:
        - La tua risposta DEVE iniziare immediatamente con `\\documentclass{{article}}` e finire esattamente con `\\end{{document}}`.
        - NON includere frasi introduttive, spiegazioni, commenti o blocchi di codice Markdown. La tua risposta deve essere solo e unicamente codice LaTeX valido.
        - Usa le IMMAGINI delle slide come guida principale per la STRUTTURA del documento (titolo, sezioni, sottosezioni).
        - Usa la TRASCRIZIONE per riempire le sezioni create con spiegazioni dettagliate, esempi e approfondimenti.
        - Usa il font Helvetica. Includi `\\usepackage{{helvet}}` e `\\renewcommand{{\\familydefault}}{{\\sfdefault}}` nel preambolo.
        - Usa pacchetti standard come `geometry`, `amsmath`, `graphicx`, e `inputenc` con `utf8`.
        - Se sono presenti formule scrivile correttamente.
        - Utilizza elenchi puntati (`itemize`) e numerati (`enumerate`) per organizzare le informazioni in modo chiaro.
        - Correggi eventuali errori grammaticali e di battitura presenti nella trascrizione.
        - Riformula le frasi per renderle più chiare e accademiche, mantenendo il significato originale.
        - Includi una sezione finale di riassunto chiamata `\\section*{{Riassunto Finale}}`.

        Usa questo titolo per il documento: Appunti della Lezione: {titolo.replace('_', ' ')}

        TRASCRIZIONE:
        {testo}
        """
    else:
        # Prompt per SOLA TRASCRIZIONE (una fonte)
        prompt_iniziale = f"""
        Sei un assistente esperto nella creazione di documenti LaTeX. A partire dalla trascrizione di una lezione, genera un documento LaTeX completo, ben strutturato e pronto per la compilazione.

        REGOLE FONDAMENTALI:
        - La tua risposta DEVE iniziare immediatamente con `\\documentclass{{article}}` e finire esattamente con `\\end{{document}}`.
        - NON includere frasi introduttive, spiegazioni, commenti o blocchi di codice Markdown. La tua risposta deve essere solo e unicamente codice LaTeX valido.
        - Struttura il documento con un titolo, la data di oggi, e sezioni/sottosezioni logiche basate sul contenuto.
        - Usa pacchetti standard come `geometry`, `amsmath`, `graphicx`, `helvet` e `inputenc` con `utf8`.
        - Se sono presenti formule scrivile correttamente.
        - Utilizza elenchi puntati (`itemize`) e numerati (`enumerate`) per organizzare le informazioni in modo chiaro.
        - Correggi eventuali errori grammaticali e di battitura.
        - Riformula le frasi per renderle più chiare e accademiche.
        - Includi una sezione finale di riassunto chiamata `\\section*{{Riassunto Finale}}`.

        Usa questo titolo per il documento: Appunti della Lezione: {titolo.replace('_', ' ')}

        TRASCRIZIONE:
        {testo}
        """

    prompt_parts = [prompt_iniziale]
    if slides:
        print("   - Invio di 2 fonti a Gemini (trascrizione + immagini).")
        prompt_parts.extend(slides)
    else:
        print("   - Invio di 1 fonte a Gemini (solo trascrizione).")

    try:
        risposta = model.generate_content(prompt_parts)
        contenuto = risposta.text.strip()
        # Pulizia robusta dell'output
        if "\\documentclass" in contenuto:
            contenuto = contenuto[contenuto.find("\\documentclass"):]
        if "\\end{document}" in contenuto:
            contenuto = contenuto[:contenuto.rfind("\\end{document}") + len("\\end{document}")]
        
        return contenuto
    except Exception as e:
        print(f"❌ Errore durante la chiamata a Gemini: {e}")
        return ""

# ---------------- COMPILAZIONE E PULIZIA ----------------
def compila_pdf(tex_path: str) -> bool:
    print("📄 Compilazione del PDF...")
    output_dir, file_name = os.path.split(tex_path)
    for _ in range(2): # Compila due volte per riferimenti incrociati
        try:
            subprocess.run(
                ["pdflatex", "-interaction=nonstopmode", file_name],
                check=True, cwd=output_dir, capture_output=True
            )
        except (FileNotFoundError, subprocess.CalledProcessError) as e:
            print(f"❌ Errore compilazione PDF. Assicurati che 'pdflatex' sia installato. Dettagli: {e}")
            return False
    print("✅ PDF generato con successo.")
    return True

def pulisci_cartella_output(output_dir: str, base_name: str):
    print("\n🧹 Pulizia finale della cartella di output...")
    file_da_mantenere = [
        f"{base_name}_appunti.tex", 
        f"{base_name}_appunti.pdf", 
        f"{base_name}_trascrizione.txt"
    ]
    for filename in os.listdir(output_dir):
        if filename not in file_da_mantenere:
            try:
                os.remove(os.path.join(output_dir, filename))
                print(f"   - Eliminato file intermedio: {filename}")
            except OSError as e:
                print(f"   - Errore durante l'eliminazione di {filename}: {e}")
    print("✔️ Pulizia finale completata.")

# ---------------- MAIN ----------------
def main():
    start_time = time.time()
    parser = argparse.ArgumentParser(description="Trascrive audio e genera appunti LaTeX/PDF con slide PDF opzionali.")
    parser.add_argument("file_audio", help="Percorso del file audio.")
    parser.add_argument("--slides", help="Percorso del file PDF delle slide.")
    parser.add_argument("--pages", help="Intervallo di pagine per PDF (es. '5-12').")
    parser.add_argument("--threads", type=int, default=N_THREADS)
    args = parser.parse_args()

    output_dir = crea_cartella_output(args.file_audio)
    base_name = os.path.splitext(os.path.basename(args.file_audio))[0]
    file_temporanei = []
    successo = False

    try:
        immagini_slide = process_slides(args.slides, args.pages)

        clean_audio = denoise_audio(args.file_audio, output_dir)
        file_temporanei.append(clean_audio)
        chunks = split_audio(clean_audio, CHUNK_LENGTH_MS_LOCAL, output_dir)
        file_temporanei.extend(chunks)

        num_workers = min(args.threads, len(chunks)) if chunks else 0
        testo_trascritto = transcribe_chunks_local_parallel(chunks, num_workers) if num_workers else ""

        if not testo_trascritto.strip():
            print("⚠️ La trascrizione è vuota. Interruzione del processo.")
            return
        
        # Salva la trascrizione prima di procedere
        trascrizione_file = os.path.join(output_dir, f"{base_name}_trascrizione.txt")
        with open(trascrizione_file, "w", encoding="utf-8") as f:
            f.write(testo_trascritto)
        print(f"💾 Trascrizione completa salvata in: {trascrizione_file}")

        documento_latex = genera_documento_latex(testo_trascritto, base_name, immagini_slide)
        
        if documento_latex:
            tex_path = os.path.join(output_dir, f"{base_name}_appunti.tex")
            with open(tex_path, "w", encoding="utf-8") as f:
                f.write(documento_latex)
            print(f"📝 File LaTeX creato: {tex_path}")

            if compila_pdf(tex_path):
                successo = True

    finally:

        print("\n🧹 Pulizia dei file audio intermedi (chunk e audio pulito)...")
        for f_path in file_temporanei:
            try:
                if os.path.exists(f_path): os.remove(f_path)
            except OSError as e:
                print(f"   - Errore durante l'eliminazione di {f_path}: {e}")
        
        if successo:
            pulisci_cartella_output(output_dir, base_name)

    total_seconds = int(time.time() - start_time)
    print(f"\n⏱️  Tempo totale: {total_seconds // 60} min {total_seconds % 60} sec")
    print(f"🎉 Processo terminato. I file finali si trovano in: {output_dir}")

if __name__ == "__main__":
    if sys.platform in ["win32", "darwin"]:
        multiprocessing.freeze_support()
        multiprocessing.set_start_method('spawn', force=True)
    main()