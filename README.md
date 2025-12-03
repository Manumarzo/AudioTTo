<p align="center">
  <img src="logo/logo_audiotto_nobg.png" alt="AudioTTo Logo" width="200"/>
</p>

# AudioTTo — Audio Transcription, Slide Integration & LaTeX Notes Generation

**AudioTTo** is a complete Python tool that:

- 🎙️ transcribes **audio files** locally using [Faster-Whisper](https://github.com/guillaumekln/faster-whisper)
- 🔊 performs **noise reduction** with [`noisereduce`](https://github.com/timsainb/noisereduce)
- ✂️ automatically splits audio into **parallel-processable chunks**
- 🧠 generates structured **LaTeX notes** (and compiles them into PDF) via **Gemini AI**
- 🖼️ optionally integrates **PDF slides** into the LaTeX document
- 🧹 performs full **cleanup** of intermediate files

> **Note:** The GUI is in English. Whisper automatically detects the audio language, and the generated notes will be in the same language as the audio.

---

## 🧩 Requirements

- **Python 3.9+**
- A working **LaTeX distribution** (`TeX Live`, `MikTeX`, or `MacTeX`)  
  → required to compile `.tex` into `.pdf`
- **Google Gemini API key** stored as an environment variable:

```bash
export GEMINI_API_KEY="your_api_key_here"
```

---

## ⚙️ Installation

Open a terminal in the project directory and install all dependencies:

```bash
pip install -r requirements.txt
```

> ✅ `PyMuPDF` and `Pillow` are required for slide-to-image conversion.

---

## 🚀 Usage

AudioTTo offers two ways to use the software: a modern **Graphical User Interface (GUI)** and a classic **Command Line Interface (CLI)**.

### Option 1: Graphical User Interface (GUI) 🖥️

The easiest way to use AudioTTo is via the web-based interface.

1.  **Start the application**:
    ```bash
    python gui_app.py
    ```

2.  **Open your browser**:
    The interface will open automatically at `http://localhost:8000`.
    - Drag & drop your audio and PDF files.
    - Select page ranges if needed.
    - View progress in real-time.
    - Open generated PDFs directly in the browser.

### Option 2: Command Line Interface (CLI) 💻

For advanced users or automation, you can run the script directly from the terminal.

#### Basic usage
```bash
python AudioTTo.py path/to/audio_file.wav
```

#### With slides
```bash
python AudioTTo.py path/to/audio_file.wav --slides path/to/slides.pdf
```

#### With slide page range
```bash
python AudioTTo.py path/to/audio_file.wav --slides slides.pdf --pages 3-12
```

#### Optional arguments

| Argument    | Description                                           | Default value          |
|-------------|-------------------------------------------------------|------------------------|
| `--slides`  | Path to a **PDF file** containing lecture slides      | None                   |
| `--pages`   | Page range from the slides to include (e.g. `"5-12"`) | Entire PDF             |
| `--threads` | Number of parallel CPU cores used for transcription   | `4` or `cpu_count()-1` |

---

## 🧠 How it works

1. **Noise reduction** — Cleans the audio using `noisereduce`
2. **Chunking** — Splits audio into 10-minute chunks for parallel processing
3. **Parallel transcription** — Uses all available CPU cores via multiprocessing
4. **Slide processing (optional)** — Converts PDF pages into images using PyMuPDF
5. **LaTeX generation** — Sends transcript + slides (if any) to Gemini AI for document creation
6. **PDF compilation** — Automatically compiles `.tex` twice with `pdflatex` for a polished output
7. **Cleanup** — Removes all intermediate `.wav`, `.aux`, `.log`, etc., keeping only:
   - `*_trascrizione.txt`
   - `*_appunti.tex`
   - `*_appunti.pdf`

---

## 📁 Output structure

After execution, results are saved under:

```
output/<audio_file_name>/
├── audiofile_clean.wav
├── chunk_0.wav
├── chunk_1.wav
├── audiofile_trascrizione.txt
├── audiofile_appunti.tex
└── audiofile_appunti.pdf
```

At the end, only the `.txt`, `.tex`, and `.pdf` files remain.

---

## ⚙️ Internal workflow

| Stage                                | Description                                               |
|--------------------------------------|-----------------------------------------------------------|
| `denoise_audio()`                    | Reduces background noise from the input audio             |
| `split_audio()`                      | Splits audio into time-based segments                     |
| `transcribe_chunks_local_parallel()` | Transcribes chunks in parallel using Faster-Whisper       |
| `process_slides()`                   | Converts PDF slides into images for Gemini                |
| `generate_latex_document()`           | Generates LaTeX code with Gemini (slides + transcription) |
| `compile_pdf()`                      | Compiles `.tex` to `.pdf` twice                           |
| `cleanup_output()`                   | Cleans intermediate files from the output directory       |

---

## ⚠️ Common errors and fixes

| Error message              | Cause / Fix                                                                  |
|----------------------------|----------------------------------------------------------------------------|
| `pdflatex not found`       | Install a LaTeX distribution (`TeX Live`, `MikTeX`, or `MacTeX`)           |
| `Gemini API key not found` | Export your Gemini key via `export GEMINI_API_KEY="..."`                   |
| `PDF compilation error`    | Check the `.log` file in the output folder                                 |
| `slides not found or invalid` | Ensure the path to the PDF slides is correct                           |
| `Permission denied` (on Windows) | Wait a few seconds — Windows may still hold file locks after multiprocessing |

---

## 💡 Tips

- Use **clean and high-quality audio** for best results
- Avoid filenames with **spaces or special characters** (prefer `_` or `-`)
- You can skip slide processing by omitting `--slides`
- If you only want the transcript, comment out the LaTeX/PDF generation part
- On **Windows**, if cleanup fails, try running with admin rights or add a short delay in cleanup

---

## 📜 License

Released under the **MIT License** — you are free to use, modify, and distribute the software, as long as you **include proper attribution** to the original author.

---

## ✨ Author

**AudioTTo** — developed by *Manumarzo*