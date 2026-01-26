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

    // Modal Elements
    const settingsBtn = document.getElementById('settings-btn');
    const settingsModal = document.getElementById('settings-modal');
    const closeModalBtn = document.getElementById('close-modal-btn');
    const apiKeyInput = document.getElementById('api-key-input');
    const saveKeyBtn = document.getElementById('save-key-btn');
    const keyStatus = document.getElementById('key-status');
    const toggleKeyBtn = document.getElementById('toggle-key-visibility');

    // --- Burger Menu Logic ---
    burgerBtn.addEventListener('click', () => {
        sidebar.classList.toggle('open');
        burgerBtn.classList.toggle('open');

        // Refresh outputs list when opening the sidebar
        if (sidebar.classList.contains('open')) {
            loadOutputs();
        }
    });

    let audioFile = null;
    let pdfFile = null;
    let ws = null;

    // --- Modal Logic ---
    function openModal() {
        settingsModal.classList.remove('hidden');
        checkKeyStatus();
    }

    function closeModal() {
        settingsModal.classList.add('hidden');
    }

    settingsBtn.addEventListener('click', openModal);
    closeModalBtn.addEventListener('click', closeModal);

    // Close modal when clicking outside
    let modalMouseDownTarget = null;
    settingsModal.addEventListener('mousedown', (e) => {
        modalMouseDownTarget = e.target;
    });
    settingsModal.addEventListener('mouseup', (e) => {
        if (e.target === settingsModal && modalMouseDownTarget === settingsModal) {
            closeModal();
        }
        modalMouseDownTarget = null;
    });

    // --- Visibility Toggle Logic ---
    function updateToggleVisibility() {
        if (apiKeyInput.value.length > 0) {
            toggleKeyBtn.classList.add('visible');
        } else {
            toggleKeyBtn.classList.remove('visible');
            // Reset to password mode if cleared, for UX consistency
            apiKeyInput.setAttribute('type', 'password');
            updateToggleIcon('password');
        }
    }

    function updateToggleIcon(type) {
        if (type === 'text') {
            toggleKeyBtn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="feather feather-eye-off"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"></path><line x1="1" y1="1" x2="23" y2="23"></line></svg>';
        } else {
            toggleKeyBtn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="feather feather-eye"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path><circle cx="12" cy="12" r="3"></circle></svg>';
        }
    }

    if (apiKeyInput) {
        apiKeyInput.addEventListener('input', updateToggleVisibility);
    }

    if (toggleKeyBtn) {
        toggleKeyBtn.addEventListener('click', () => {
            const type = apiKeyInput.getAttribute('type') === 'password' ? 'text' : 'password';
            apiKeyInput.setAttribute('type', type);
            updateToggleIcon(type);
        });
    }

    // --- API Key Logic ---
    async function getKeyStatus() {
        try {
            const res = await fetch('/api/key-status');
            return await res.json();
        } catch (err) {
            console.error("Error fetching key status:", err);
            return { is_set: false };
        }
    }

    async function checkKeyStatus() {
        const data = await getKeyStatus();
        if (data.is_set) {
            keyStatus.textContent = 'API Key is set ✅';
            keyStatus.className = 'key-status set';
            apiKeyInput.placeholder = '••••••••••••••••';
        } else {
            keyStatus.textContent = 'API Key missing ❌';
            keyStatus.className = 'key-status missing';
        }
    }

    saveKeyBtn.addEventListener('click', async () => {
        const key = apiKeyInput.value.trim();
        if (!key) {
            showToast("Please enter an API Key.", 'error');
            return;
        }

        saveKeyBtn.disabled = true;
        saveKeyBtn.textContent = 'Saving...';

        try {
            const res = await fetch('/api/key', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ api_key: key })
            });

            if (res.ok) {
                showToast("API Key saved successfully!", 'success');
                apiKeyInput.value = '';
                if (typeof updateToggleVisibility === 'function') {
                    updateToggleVisibility();
                } else {
                    const toggleKeyBtn = document.getElementById('toggle-key-visibility');
                    if (toggleKeyBtn) toggleKeyBtn.classList.remove('visible');
                }

                checkKeyStatus();
                closeModal();
            } else {
                showToast("Error saving API Key.", 'error');
            }
        } catch (err) {
            console.error("Error saving key:", err);
            showToast("Error saving API Key.", 'error');
        } finally {
            saveKeyBtn.disabled = false;
            saveKeyBtn.textContent = 'Save';
        }
    });

    // --- Threads Configuration Logic ---
    const threadConfigBtn = document.getElementById('thread-config-btn');
    const threadsModal = document.getElementById('threads-modal');
    const closeThreadsBtn = document.getElementById('close-threads-btn');
    const saveThreadsBtn = document.getElementById('save-threads-btn');
    const threadsSlider = document.getElementById('threads-slider');
    const threadsDisplay = document.getElementById('threads-value-display');
    const maxCpuDisplay = document.getElementById('max-cpu-display');

    let currentThreads = 4;

    function openThreadsModal() {
        threadsModal.classList.remove('hidden');
    }

    function closeThreadsModal() {
        threadsModal.classList.add('hidden');
    }

    if (threadConfigBtn) threadConfigBtn.addEventListener('click', openThreadsModal);
    if (closeThreadsBtn) closeThreadsBtn.addEventListener('click', closeThreadsModal);

    // Close threads modal when clicking outside
    let threadsModalMouseDownTarget = null;
    if (threadsModal) {
        threadsModal.addEventListener('mousedown', (e) => {
            threadsModalMouseDownTarget = e.target;
        });
        threadsModal.addEventListener('mouseup', (e) => {
            if (e.target === threadsModal && threadsModalMouseDownTarget === threadsModal) {
                closeThreadsModal();
            }
            threadsModalMouseDownTarget = null;
        });
    }

    threadsSlider.addEventListener('input', () => {
        threadsDisplay.textContent = threadsSlider.value;
    });

    saveThreadsBtn.addEventListener('click', async () => {
        const val = parseInt(threadsSlider.value);
        saveThreadsBtn.disabled = true;
        saveThreadsBtn.textContent = 'Saving...';

        try {
            const res = await fetch('/api/save-threads', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ threads: val })
            });
            if (res.ok) {
                currentThreads = val;
                showToast(`Threads set to ${val}`, 'success');
                closeThreadsModal();
            } else {
                showToast('Error saving configuration', 'error');
            }
        } catch (e) {
            console.error(e);
            showToast('Error saving configuration', 'error');
        } finally {
            saveThreadsBtn.disabled = false;
            saveThreadsBtn.textContent = 'Save';
        }
    });

    async function initThreadsInfo() {
        try {
            const res = await fetch('/api/info');
            const data = await res.json();

            const cpuCount = data.cpu_count || 4;
            const saved = data.saved_threads || 4;

            let maxThreads = Math.max(1, cpuCount - 1);
            if (cpuCount <= 1) maxThreads = 1;

            threadsSlider.max = maxThreads;
            threadsSlider.value = Math.min(saved, maxThreads);

            maxCpuDisplay.textContent = maxThreads;
            threadsDisplay.textContent = threadsSlider.value;
            currentThreads = parseInt(threadsSlider.value);

        } catch (e) {
            console.error("Failed to fetch app info:", e);
        }
    }

    initThreadsInfo();

    // --- Drag & Drop Logic ---
    ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
        document.body.addEventListener(eventName, preventDefaults, false);
    });

    function preventDefaults(e) {
        e.preventDefault();
        e.stopPropagation();
    }

    // --- Drag & Drop Logic ---
    function setupDragDrop(zone, input, fileType, callback) {
        zone.addEventListener('click', () => input.click());
        input.addEventListener('change', (e) => handleFiles(e.target.files, fileType, callback));

        // Highlight drop zone
        ['dragenter', 'dragover'].forEach(eventName => {
            zone.addEventListener(eventName, (e) => {
                zone.classList.add('dragover');
                // Explicitly show that a copy action is allowed (helps on some OSs)
                if (e.dataTransfer) {
                    e.dataTransfer.dropEffect = 'copy';
                }
            }, false);
        });

        ['dragleave', 'drop'].forEach(eventName => {
            zone.addEventListener(eventName, () => {
                zone.classList.remove('dragover');
            }, false);
        });

        zone.addEventListener('drop', (e) => {
            handleFiles(e.dataTransfer.files, fileType, callback);
        });
    }

    function handleFiles(files, type, callback) {
        if (files.length > 0) {
            const file = files[0];
            const fileName = file.name.toLowerCase();

            // Validation Logic with Extension Fallback
            let isValid = false;

            if (type === 'audio') {
                // Check MIME type OR extension
                const allowedExtensions = ['.mp3', '.wav', '.m4a', '.flac', '.ogg', '.aac', '.wma'];
                if (file.type.startsWith('audio/') || allowedExtensions.some(ext => fileName.endsWith(ext))) {
                    isValid = true;
                } else {
                    showToast('Please upload a valid audio file (mp3, wav, m4a, ...).', 'error');
                }
            } else if (type === 'pdf') {
                if (file.type === 'application/pdf' || fileName.endsWith('.pdf')) {
                    isValid = true;
                } else {
                    showToast('Please upload a valid PDF file.', 'error');
                }
            }

            if (isValid) {
                callback(file);
            }
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
        pagesInput.disabled = false;
        pagesInput.placeholder = "e.g., 1-5 (Optional)";
    });

    function checkStartReady() {
        startBtn.disabled = !audioFile;
    }

    // --- Upload & Process Logic ---
    startBtn.addEventListener('click', async () => {
        if (!audioFile) return;

        // CHECK API KEY
        const keyData = await getKeyStatus();
        if (!keyData.is_set) {
            showToast("Gemini API Key is missing! Please configure it in Settings.", 'error');
            openModal();
            return;
        }

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
            statusIndicator.textContent = 'Elaboration in progress...';
            statusIndicator.style.color = '#3b82f6'; // Blue

            // Send config to start
            ws.send(JSON.stringify({
                audio_filename: audioName,
                slides_filename: pdfName,
                pages: pages,
                threads: currentThreads
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
                pagesInput.disabled = true; // Disable again until new PDF
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
        const terminalWindow = document.getElementById('terminal-window');

        if (message.startsWith('\r')) {
            const cleanMessage = message.replace(/^\r+/, '');
            const lastLine = terminalWindow.lastElementChild;
            if (lastLine) {
                lastLine.textContent = `> ${cleanMessage}`;
            } else {
                const div = document.createElement('div');
                div.className = 'log-line';
                div.textContent = `> ${cleanMessage}`;
                terminalWindow.appendChild(div);
            }
        } else {
            const div = document.createElement('div');
            div.className = 'log-line';
            div.textContent = `> ${message}`;
            terminalWindow.appendChild(div);
        }
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

    // --- Toast Notification Logic ---
    function showToast(message, type = 'info') {
        const container = document.getElementById('toast-container');

        // DEDUPLICATION: Check if identical toast exists
        const existingToasts = container.querySelectorAll('.toast');
        for (let t of existingToasts) {
            if (t.innerText.includes(message)) {
                return; // Ignore duplicate
            }
        }

        const toast = document.createElement('div');
        toast.className = `toast ${type}`;

        let icon = 'ℹ️';
        if (type === 'error') icon = '⚠️';
        if (type === 'success') icon = '✅';

        toast.innerHTML = `<span>${icon}</span> <span>${message}</span>`;
        container.appendChild(toast);

        // Auto remove after 3s
        setTimeout(() => {
            toast.classList.add('hiding');
            toast.addEventListener('animationend', () => {
                if (toast.parentElement) toast.remove();
            });
        }, 3000);
    }
});
