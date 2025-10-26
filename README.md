# 🎧 AudioTTo — Audio Transcription and LaTeX Notes Generation

**AudioTTo** is a Python script that:

* transcribes **audio files** locally using [Faster-Whisper](https://github.com/guillaumekln/faster-whisper),
* performs **noise reduction** with `noisereduce`,
* automatically splits audio into **parallel-processable chunks**,
* and generates a **LaTeX (and PDF)** notes document, structured and formatted using **Gemini AI**.

---

## 🧩 Requirements

* **Python 3.9+**
* A **LaTeX distribution** installed (`TeX Live`, `MikTeX`, or `MacTeX`)
  → required to compile the `.tex` file into `.pdf`.
* **Google Gemini API key** stored as an environment variable:

  ```bash
  export GEMINI_API_KEY="your_api_key_here"
  ```

---

## ⚙️ Installation

Open a terminal in the project directory and install the dependencies:

```bash
pip install librosa soundfile noisereduce pydub imageio-ffmpeg faster-whisper google-generativeai setuptools
```

---

## 🚀 Usage

Run the script with an audio file as input (e.g., `.wav`, `.mp3`, `.m4a`, etc.):

```bash
python AudioTTo.py path/to/audio_file.wav
```

### Optional arguments

| Argument    | Description                                             | Default                |
| ----------- | ------------------------------------------------------- | ---------------------- |
| `--threads` | Number of parallel CPU processes used for transcription | `4` or `cpu_count()-1` |

Example:

```bash
python AudioTTo.py university_lecture.wav --threads 6
```

---

## 🧠 How it works

1. 🔊 **Noise reduction** – Cleans the input audio using `noisereduce`.
2. ✂️ **Chunking** – Splits the audio into 10-minute segments.
3. 🧩 **Parallel transcription** – Uses multiple CPU cores for faster processing.
4. 📝 **LaTeX generation** – Sends the transcript to Gemini to generate a `.tex` file.
5. 📄 **PDF compilation** – Automatically compiles the `.tex` into a PDF.
6. 🧹 **Cleanup** – Removes temporary files and keeps only:

   * `*_transcription.txt`
   * `*_notes.tex`
   * `*_notes.pdf`

---

## 📁 Output structure

After execution, your results will be in:

```
output/<audio_file_name>/
├── audiofile_clean.wav
├── chunk_0.wav
├── chunk_1.wav
├── audiofile_transcription.txt
├── audiofile_notes.tex
└── audiofile_notes.pdf
```

Only `.txt`, `.tex`, and `.pdf` files are kept at the end.

---

## ⚠️ Common errors

| Error                      | Possible cause                    | Solution                                   |
| -------------------------- | --------------------------------- | ------------------------------------------ |
| `pdflatex not found`       | No LaTeX distribution installed   | Install TeX Live / MikTeX                  |
| `Gemini API key not found` | `GEMINI_API_KEY` variable not set | Export the API key                         |
| `PDF compilation error`    | Broken or invalid `.tex` file     | Check the `.log` file in the output folder |

---

## 💡 Tips

* Avoid **spaces or special characters** in file names (use `_` or `-` instead).
* If you only need transcription (no PDF), comment out the LaTeX generation part.
* For best results, use **clear audio** with minimal background noise.

---

## 📜 License

This project is released under the **MIT License**.
You are free to use, modify, and distribute this software — even commercially —
as long as you **include attribution** to the original author.

---

## ✨ Author

**AudioTTo** — developed by *[Manumarzo]*

