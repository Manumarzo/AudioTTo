document.addEventListener('DOMContentLoaded', () => {
    const audioDropZone = document.getElementById('audio-drop-zone');
    const pdfDropZone = document.getElementById('pdf-drop-zone');
    const audioInput = document.getElementById('audio-input');
    const pdfInput = document.getElementById('pdf-input');
    const startBtn = document.getElementById('start-btn');
    const pagesInput = document.getElementById('pages-input');
    const terminalWindow = document.getElementById('terminal-window');
    const statusIndicator = document.getElementById('status-indicator');
    const resultsList = document.getElementById('results-list');
    const burgerBtn = document.getElementById('burger-btn');
    const sidebar = document.querySelector('.sidebar');

    // --- Burger Menu Logic ---
    burgerBtn.addEventListener('click', () => {
        sidebar.classList.toggle('open');
        burgerBtn.classList.toggle('open');
    });

    let audioFile = null;
    let pdfFile = null;
    let ws = null;

    // --- Drag & Drop Logic ---
    function setupDragDrop(zone, input, fileType, callback) {
        zone.addEventListener('click', () => input.click());
        input.addEventListener('change', (e) => handleFiles(e.target.files, fileType, callback));

        zone.addEventListener('dragover', (e) => {
            e.preventDefault();
            zone.classList.add('dragover');
        });

        zone.addEventListener('dragleave', () => zone.classList.remove('dragover'));

        zone.addEventListener('drop', (e) => {
            e.preventDefault();
            zone.classList.remove('dragover');
            handleFiles(e.dataTransfer.files, fileType, callback);
        });
    }

    function handleFiles(files, type, callback) {
        if (files.length > 0) {
            const file = files[0];
            if (type === 'audio' && !file.type.startsWith('audio/')) {
                alert('Please upload a valid audio file.');
                return;
            }
            if (type === 'pdf' && file.type !== 'application/pdf') {
                alert('Please upload a valid PDF file.');
                return;
            }
            callback(file);
        }
    }

    setupDragDrop(audioDropZone, audioInput, 'audio', (file) => {
        audioFile = file;
        document.getElementById('audio-file-info').textContent = `Selected file: ${file.name}`;
        checkStartReady();
    });

    setupDragDrop(pdfDropZone, pdfInput, 'pdf', (file) => {
        pdfFile = file;
        document.getElementById('pdf-file-info').textContent = `Selected file: ${file.name}`;
    });

    function checkStartReady() {
        startBtn.disabled = !audioFile;
    }

    // --- Upload & Process Logic ---
    startBtn.addEventListener('click', async () => {
        if (!audioFile) return;

        startBtn.disabled = true;
        statusIndicator.textContent = 'Uploading file...';
        statusIndicator.style.color = '#fbbf24'; // Yellow
        log("Starting file upload...");

        try {
            // 1. Upload Audio
            const audioData = new FormData();
            audioData.append('file', audioFile);
            const audioRes = await fetch('/upload', { method: 'POST', body: audioData });
            if (!audioRes.ok) throw new Error("Audio upload error");
            const audioJson = await audioRes.json();
            log(`Audio uploaded: ${audioJson.filename}`);

            // 2. Upload PDF (if any)
            let pdfFilename = null;
            if (pdfFile) {
                const pdfData = new FormData();
                pdfData.append('file', pdfFile);
                const pdfRes = await fetch('/upload', { method: 'POST', body: pdfData });
                if (!pdfRes.ok) throw new Error("PDF upload error");
                const pdfJson = await pdfRes.json();
                pdfFilename = pdfJson.filename;
                log(`PDF uploaded: ${pdfFilename}`);
            }

            // 3. Connect WebSocket & Start Process
            startWebSocket(audioJson.filename, pdfFilename, pagesInput.value);

        } catch (err) {
            log(`❌ Errore: ${err.message}`);
            startBtn.disabled = false;
            statusIndicator.textContent = 'Error';
            statusIndicator.style.color = '#ef4444';
        }
    });

    function startWebSocket(audioName, pdfName, pages) {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        ws = new WebSocket(`${protocol}//${window.location.host}/ws/process`);

        ws.onopen = () => {
            statusIndicator.textContent = 'Processing in progress...';
            statusIndicator.style.color = '#3b82f6'; // Blue

            // Send config to start
            ws.send(JSON.stringify({
                audio_filename: audioName,
                slides_filename: pdfName,
                pages: pages
            }));
        };

        ws.onmessage = (event) => {
            const msg = event.data;
            if (msg === 'REFRESH_OUTPUTS') {
                loadOutputs();
                statusIndicator.textContent = 'Completed';
                statusIndicator.style.color = '#10b981'; // Green
                startBtn.disabled = true; // Keep disabled until new file is selected

                // Reset inputs
                audioFile = null;
                pdfFile = null;
                audioInput.value = '';
                pdfInput.value = '';
                pagesInput.value = '';
                document.getElementById('audio-file-info').textContent = '';
                document.getElementById('pdf-file-info').textContent = '';

                log("Inputs cleared. Ready for new task.");
            } else {
                log(msg);
            }
        };

        ws.onclose = () => {
            log("Connection closed.");
            if (statusIndicator.textContent !== 'Completed') {
                startBtn.disabled = false;
            }
        };

        ws.onerror = (err) => {
            log("WebSocket error.");
            console.error(err);
        };
    }

    function log(message) {
        const div = document.createElement('div');
        div.className = 'log-line';
        div.textContent = `> ${message}`;
        terminalWindow.appendChild(div);
        terminalWindow.scrollTop = terminalWindow.scrollHeight;
    }

    // --- Results Logic ---
    async function loadOutputs() {
        try {
            const res = await fetch('/outputs');
            const files = await res.json();

            resultsList.innerHTML = '';
            if (files.length === 0) {
                resultsList.innerHTML = '<div class="empty-state">No notes generated.</div>';
                return;
            }

            files.forEach(file => {
                const item = document.createElement('div');
                item.className = 'result-item';
                item.innerHTML = `
                    <h4>${file.folder}</h4>
                    <p>${file.filename}</p>
                    <a href="/view/${file.folder}/${file.filename}" class="download-btn" target="_blank">Open PDF</a>
                `;
                resultsList.appendChild(item);
            });
        } catch (err) {
            console.error("Errore caricamento output:", err);
        }
    }

    // Initial load
    loadOutputs();
});
