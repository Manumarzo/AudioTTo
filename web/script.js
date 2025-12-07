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
    // Close modal when clicking outside (Robust check)
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
                // updateToggleVisibility is defined in scope above? No, it's defined inside DOMContentLoaded but not this closure? 
                // Wait, everything is inside DOMContentLoaded. 
                // But I need to make sure updateToggleVisibility is accessible or I should just manually reset it.
                if (typeof updateToggleVisibility === 'function') {
                    updateToggleVisibility();
                } else {
                    // Fallback manual reset if function not found (though it should be)
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
                showToast('Please upload a valid audio file.', 'error');
                return;
            }
            if (type === 'pdf' && file.type !== 'application/pdf') {
                showToast('Please upload a valid PDF file.', 'error');
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

        // 🔹 1. CHECK API KEY: Prima di fare qualsiasi cosa, controlliamo la chiave
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
    // Check key status on load is not strictly necessary if we check on modal open, 
    // but good to know if we want to show a warning icon on the settings button later.
    // For now, we only check when opening the modal.

    // --- Toast Notification Logic ---
    function showToast(message, type = 'info') {
        const container = document.getElementById('toast-container');

        // 🔹 DEDUPLICATION: Check if identical toast exists
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
