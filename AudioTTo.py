# COMANDO DI INSTALLAZIONE (da lanciare nel terminale):
# pip install librosa soundfile noisereduce pydub imageio-ffmpeg faster-whisper google-generativeai setuptools

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

# Sopprime lo UserWarning specifico di ctranslate2/pkg_resources per un output più pulito
warnings.filterwarnings("ignore", category=UserWarning, module='ctranslate2')

# ---------------- CONFIG ----------------
MODEL_SIZE = "small"
COMPUTE_TYPE = "int8"
LANGUAGE = None
N_THREADS = 4

CHUNK_LENGTH_MS_LOCAL = 10 * 60 * 1000

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
AudioSegment.converter = ffmpeg.get_ffmpeg_exe()

# --- VARIABILE GLOBALE PER I WORKER ---
# Questa variabile sarà resa disponibile a ogni processo worker.
# Ogni worker avrà la sua copia inizializzata una sola volta.
model_worker = None

def init_worker():
    """
    Funzione di inizializzazione per ogni processo del pool.
    Carica il modello Whisper una sola volta per worker.
    """
    global model_worker
    print(f"Processo worker {os.getpid()} sta inizializzando il modello Whisper...")
    model_worker = WhisperModel(MODEL_SIZE, device="cpu", compute_type=COMPUTE_TYPE)
    print(f"✅ Processo worker {os.getpid()} ha caricato il modello.")

# ---------------- FUNZIONI ----------------

def crea_cartella_output(audio_path: str) -> str:
    base_name = os.path.splitext(os.path.basename(audio_path))[0]
    output_dir = os.path.join("output", base_name)
    os.makedirs(output_dir, exist_ok=True)
    print(f"📁 Cartella di output: {output_dir}")
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
    """
    Funzione eseguita dal worker. Ora NON carica più il modello,
    ma usa quello pre-caricato nella variabile globale del suo processo.
    """
    global model_worker
    segments, _ = model_worker.transcribe(chunk_path, language=LANGUAGE)
    text = " ".join(s.text for s in segments)
    print(f"   - Chunk {os.path.basename(chunk_path)} trascritto dal worker {os.getpid()}.")
    return text

def transcribe_chunks_local_parallel(chunks: list, num_workers: int) -> str:
    print(f"🚀 Avvio trascrizione parallela su {num_workers} core della CPU...")
    # Usa 'initializer' per chiamare 'init_worker' all'avvio di ogni processo
    with multiprocessing.Pool(processes=num_workers, initializer=init_worker) as pool:
        results = pool.map(transcribe_chunk_worker, chunks)
    return " ".join(results).strip()

def genera_documento_latex(testo: str, titolo: str) -> str:
    if not GEMINI_API_KEY:
        print("❌ Chiave API di Gemini non trovata. Imposta la variabile d'ambiente GEMINI_API_KEY.")
        return ""
    print("🧠 Generazione documento LaTeX con Gemini...")
    genai.configure(api_key=GEMINI_API_KEY)
    
    model = genai.GenerativeModel('gemini-2.5-flash')
    
    prompt = f"""
    Sei un assistente esperto nella creazione di documenti LaTeX. A partire dalla trascrizione di una lezione, genera un documento LaTeX completo, ben strutturato e pronto per la compilazione.

    REGOLE FONDAMENTALI:
    - La tua risposta DEVE iniziare immediatamente con `\\documentclass{{article}}` e finire esattamente con `\\end{{document}}`.
    - NON includere frasi introduttive, spiegazioni, commenti o blocchi di codice Markdown. La tua risposta deve essere solo e unicamente codice LaTeX valido.
    - Struttura il documento con un titolo, la data di oggi, e sezioni/sottosezioni logiche basate sul contenuto.
    - Usa pacchetti standard come `geometry`, `amsmath`, `graphicx`, `helvet` e `inputenc` con `utf8`.
    - Utilizza elenchi puntati (`itemize`) e numerati (`enumerate`) per organizzare le informazioni in modo chiaro.
    - Correggi eventuali errori grammaticali e di battitura.
    - Riformula le frasi per renderle più chiare e accademiche.
    - Includi una sezione finale di riassunto chiamata `\\section*{{Riassunto Finale}}`.

    Usa questo titolo per il documento: Appunti della Lezione: {titolo.replace('_', ' ')}

    TRASCRIZIONE:
    {testo}
    """
    try:
        risposta = model.generate_content(prompt)
        contenuto = risposta.text.strip()
        # Pulizia robusta
        if not contenuto.startswith("\\documentclass"):
            primo_comando = contenuto.find("\\documentclass")
            if primo_comando != -1:
                contenuto = contenuto[primo_comando:]
        if not contenuto.endswith("\\end{document}"):
            ultimo_comando = contenuto.rfind("\\end{document}")
            if ultimo_comando != -1:
                contenuto = contenuto[:ultimo_comando + len("\\end{document}")]
        
        return contenuto
    except Exception as e:
        print(f"❌ Errore durante la chiamata a Gemini: {e}")
        return ""

def compila_pdf(tex_path: str) -> bool:
    print("📄 Compilazione del PDF in corso...")
    output_dir = os.path.dirname(tex_path)
    file_name = os.path.basename(tex_path)
    for _ in range(2):
        try:
            subprocess.run(
                ["pdflatex", "-interaction=nonstopmode", file_name],
                check=True, cwd=output_dir, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        except FileNotFoundError:
            print("❌ Errore: 'pdflatex' non trovato. Assicurati di avere una distribuzione LaTeX installata.")
            return False
        except subprocess.CalledProcessError:
            log_file = file_name.replace('.tex', '.log')
            print(f"❌ Errore durante la compilazione. Controlla il file di log: '{log_file}' in {output_dir}.")
            return False
        except Exception as e:
            print(f"❌ Errore imprevisto durante la compilazione: {e}")
            return False
    print("✅ PDF generato con successo.")
    return True

def pulisci_cartella_output(output_dir: str, base_name: str):
    print("\n🧹 Pulizia finale della cartella di output...")
    file_da_mantenere = [f"{base_name}_appunti.tex", f"{base_name}_appunti.pdf", f"{base_name}_trascrizione.txt"]
    for filename in os.listdir(output_dir):
        if filename not in file_da_mantenere:
            try:
                os.remove(os.path.join(output_dir, filename))
                print(f"   - Eliminato file intermedio: {filename}")
            except OSError as e:
                print(f"   - Errore durante l'eliminazione di {filename}: {e}")
    print("✔️ Pulizia finale completata.")

def main():
    
    start_time = time.time()
    
    parser = argparse.ArgumentParser(description="Trascrive un file audio localmente (CPU) e genera appunti in LaTeX/PDF.")
    parser.add_argument("file_audio", help="Percorso del file audio da trascrivere.")
    parser.add_argument("--threads", type=int, default=None, help="Numero di processi paralleli per la trascrizione. Default: numero di core - 1.")

    args = parser.parse_args()

    output_dir = crea_cartella_output(args.file_audio)
    base_name = os.path.splitext(os.path.basename(args.file_audio))[0]

    file_temporanei = []
    successo = False

    try:
        print("🖥️  Modalità: Trascrizione locale su CPU.")
        clean_audio_path = denoise_audio(args.file_audio, output_dir)
        file_temporanei.append(clean_audio_path)

        chunks = split_audio(clean_audio_path, CHUNK_LENGTH_MS_LOCAL, output_dir)
        file_temporanei.extend(chunks)

        max_threads_desiderati = args.threads or N_THREADS or max(1, multiprocessing.cpu_count() - 1)
        

        num_workers = min(max_threads_desiderati, len(chunks))


        if len(chunks) > 0:
            num_workers = max(1, num_workers)
        else:
            num_workers = 0

  
        if num_workers > 0:
            testo_trascritto = transcribe_chunks_local_parallel(chunks, num_workers)
        else:
            print("⚠️ Nessun chunk audio da trascrivere.")
            testo_trascritto = ""

        if not testo_trascritto or not testo_trascritto.strip():
            print("⚠️ La trascrizione è vuota. Interruzione del processo.")

        if testo_trascritto and testo_trascritto.strip():
            trascrizione_file = os.path.join(output_dir, f"{base_name}_trascrizione.txt")
            with open(trascrizione_file, "w", encoding="utf-8") as f:
                f.write(testo_trascritto)
            print(f"💾 Trascrizione completa salvata in: {trascrizione_file}")
            
            documento_latex = genera_documento_latex(testo_trascritto, base_name)
            if documento_latex:
                output_tex_path = os.path.join(output_dir, f"{base_name}_appunti.tex")
                with open(output_tex_path, "w", encoding="utf-8") as f:
                    f.write(documento_latex)
                print(f"📝 File LaTeX creato: {output_tex_path}")

                if compila_pdf(output_tex_path):
                    successo = True
        else:
            print("Processo terminato senza aver generato una trascrizione valida.")


    finally:
        print("\n🧹 Pulizia dei file intermedi (chunk e audio pulito)...")
        for f_path in file_temporanei:
            if os.path.exists(f_path):
                try:
                    os.remove(f_path)
                except OSError as e:
                     print(f"   - Errore durante l'eliminazione di {f_path}: {e}")
        
        if successo:
            pulisci_cartella_output(output_dir, base_name)
            
    end_time = time.time()
    total_seconds = end_time - start_time
    hours = int(total_seconds // 3600)
    minutes = int((total_seconds % 3600) // 60)
    seconds = int(total_seconds % 60)

    print(f"\n⏱️  Tempo totale di elaborazione: {hours} ore, {minutes} minuti e {seconds} secondi.")
    print(f"🎉 Processo terminato. I file finali si trovano in: {output_dir}")

if __name__ == "__main__":
    if sys.platform in ["win32", "darwin"]:
        multiprocessing.freeze_support()
        multiprocessing.set_start_method('spawn', force=True)
    main()