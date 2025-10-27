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

> **Note:** The output and messages are in Italian, but Whisper automatically detects the language. Just translate the prompt and messages if you want to try another language.

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
pip install librosa soundfile noisereduce pydub imageio-ffmpeg faster-whisper google-generativeai setuptools PyMuPDF Pillow
```

> ✅ `PyMuPDF` and `Pillow` are required for slide-to-image conversion.

---

## 🚀 Usage

You can run the script on any audio file (`.wav`, `.mp3`, `.m4a`, etc.). Optionally, you can provide a **PDF of slides** and specify which pages to include.

### Basic usage

```bash
python AudioTTo.py path/to/audio_file.wav
```

### With slides

```bash
python AudioTTo.py path/to/audio_file.wav --slides path/to/slides.pdf
```

### With slide page range

```bash
python AudioTTo.py path/to/audio_file.wav --slides slides.pdf --pages 3-12
```

### Optional arguments

| Argument    | Description                                           | Default value          |
|-------------|-------------------------------------------------------|------------------------|
| `--slides`  | Path to a **PDF file** containing lecture slides      | None                   |
| `--pages`   | Page range from the slides to include (e.g. `"5-12"`) | Entire PDF             |
| `--threads` | Number of parallel CPU cores used for transcription   | `4` or `cpu_count()-1` |

Example:

```bash
python AudioTTo.py university_lecture.wav --slides slides.pdf --pages 5-15 --threads 6
```

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
| `genera_documento_latex()`           | Generates LaTeX code with Gemini (slides + transcription) |
| `compila_pdf()`                      | Compiles `.tex` to `.pdf` twice                           |
| `pulisci_cartella_output()`          | Cleans intermediate files from the output directory       |

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