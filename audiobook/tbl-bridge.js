/**
 * Adapter for TBL's native "Generate Audiobook" modal.
 *
 * Edge TTS / Chatterbox remain managed by upstream TBL. This adapter adds
 * Qwen3-TTS using the independent audiobook API, with mandatory preview
 * approval. The full standalone studio stays available at /audiobook/.
 *
 * Does not use the TBL TTS route, monkey-patch fetch, or change translations.
 */
const API = '/audiobook/api';
const VOICES = ['Ryan', 'Aiden', 'Serena', 'Vivian', 'Dylan', 'Eric', 'Uncle_Fu', 'Ono_Anna', 'Sohee'];

function el(tag, attrs, text) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs || {})) {
        if (key === 'className') node.className = value;
        else node.setAttribute(key, value);
    }
    if (text !== undefined) node.textContent = text;
    return node;
}

function addChoice(parent, value, label, selected) {
    const option = el('option', { value }, label);
    option.selected = !!selected;
    parent.append(option);
}

async function request(path, method, payload) {
    const response = await fetch(API + path, {
        method: method || 'GET',
        headers: payload ? { 'Content-Type': 'application/json' } : undefined,
        body: payload ? JSON.stringify(payload) : undefined,
        cache: 'no-store'
    });
    let result;
    try { result = await response.json(); }
    catch { throw new Error('Ungültige Antwort des Hörbuchdienstes (HTTP ' + response.status + ')'); }
    if (!response.ok) throw new Error(result.detail || result.error || 'HTTP ' + response.status);
    return result;
}

function setNotice(target, message, isError) {
    target.textContent = message;
    target.style.color = isError ? '#fca5a5' : '#bdd4e7';
}

export function enhanceTtsModal(filename, filepath) {
    const modal = document.getElementById('ttsModal');
    const provider = document.getElementById('ttsModalProvider');
    if (!modal || !provider || document.getElementById('ttsModalQwenOptions')) return;

    const epub = typeof filename === 'string' && filename.toLowerCase().endsWith('.epub');
    const option = el('option', { value: 'qwen-local' }, 'Deutsche Hörbuchstimme (lokale GPU)');
    option.disabled = !epub;
    provider.prepend(option);

    // Our deployment translates into German by default; retain all TBL choices.
    const edgeLanguage = document.getElementById('ttsModalLanguage');
    const chatterboxLanguage = document.getElementById('ttsModalChatterboxLang');
    if (edgeLanguage) edgeLanguage.value = 'German';
    if (chatterboxLanguage) chatterboxLanguage.value = 'de';

    const section = el('div', { id: 'ttsModalQwenOptions', style: 'display:none; padding: 14px 0;' });
    section.append(el('p', { style: 'font-size:13px; color:#aab7c7;' },
        'Lokal, deutsch und für Fachbücher optimiert. Vor der Vollproduktion ist eine Hörprobe mit ausdrücklicher Freigabe erforderlich.'));
    const engineField = el('div', { className: 'form-group' });
    engineField.append(el('label', { for: 'ttsModalGermanEngine' }, 'Deutsche TTS-Stimme'));
    const engine = el('select', { id: 'ttsModalGermanEngine', className: 'form-control' });
    addChoice(engine, 'qwen-base-german', 'Thorsten (Qwen3 Base · Hochdeutsch)', true);
    addChoice(engine, 'cosyvoice-thorsten', 'Thorsten (CosyVoice3 · Hochdeutsch)', false);
    addChoice(engine, 'qwen-customvoice', 'Andere Qwen-Stimmen (fremdsprachiger Akzent möglich)', false);
    const cosyOption = Array.from(engine.options).find(o => o.value === 'cosyvoice-thorsten');
    cosyOption.disabled = true;
    engineField.append(engine);
    section.append(engineField);
    const voiceHint = el('p', { id: 'ttsModalGermanHint', style: 'font-size:12px; color:#aab7c7;' },
        'Die deutsche Thorsten-Referenz (CC0) wird beim ersten Hörtest automatisch geladen. Kein englischer Ryan-Akzent als Vorgabe.');
    section.append(voiceHint);

    const voiceField = el('div', { id: 'ttsModalQwenVoiceField', className: 'form-group',
        style: 'display:none;' });
    voiceField.append(el('label', { for: 'ttsModalQwenVoice' }, 'Sprecherstimme'));
    const voice = el('select', { id: 'ttsModalQwenVoice', className: 'form-control' });
    VOICES.forEach(name => addChoice(voice, name, name, name === 'Ryan'));
    voiceField.append(voice);
    section.append(voiceField);
    engine.addEventListener('change', () => {
        const legacy = engine.value === 'qwen-customvoice';
        voiceField.style.display = legacy ? 'block' : 'none';
        voiceHint.textContent = legacy ?
            'Diese Stimmen sind nicht deutsch-muttersprachlich; ein Akzent ist möglich.' :
            engine.value === 'cosyvoice-thorsten' ?
            'Deutsches Thorsten-CosyVoice3-Modell; der zusätzliche lokale Dienst muss laufen.' :
            'Echte deutsche Thorsten-Referenz (CC0), Qwen3 Base Voice Cloning. Download beim ersten Start.';
    });
    request('/capabilities').then(data => {
        const available = data.engines?.find(x => x.id === 'cosyvoice-thorsten')?.available;
        cosyOption.disabled = !available;
        cosyOption.textContent = available ?
            'Thorsten (CosyVoice3 · Hochdeutsch)' :
            'Thorsten (CosyVoice3 · Dienst nicht gestartet)';
    }).catch(() => { cosyOption.disabled = true; });

    const speedField = el('div', { className: 'form-group' });
    speedField.append(el('label', { for: 'ttsModalQwenSpeed' }, 'Sprechtempo'));
    const speed = el('select', { id: 'ttsModalQwenSpeed', className: 'form-control' });
    addChoice(speed, '1', 'Natürlich 1,0×', false);
    addChoice(speed, '1.05', 'Lebendig 1,05× (Standard)', true);
    addChoice(speed, '1.1', 'Zügig 1,1×', false);
    speedField.append(speed);
    section.append(speedField);

    const tocField = el('label', { style: 'display:flex; align-items:center; gap:9px; margin:12px 0 16px;' });
    const skipToc = el('input', { id: 'ttsModalSkipToc', type: 'checkbox', checked: '',
        style: 'width:auto; margin:0;' });
    tocField.append(skipToc, el('span', {}, 'Inhaltsverzeichnis nicht vorlesen (Standard)'));
    section.append(tocField);

    const state = el('div', { id: 'ttsModalQwenJob', style: 'display:none; margin-top:16px;' });
    const notice = el('p', { id: 'ttsModalQwenNotice', 'aria-live': 'polite', style: 'font-size:13px;' });
    const progress = el('progress', { id: 'ttsModalQwenProgress', max: '1', value: '0', style: 'width:100%;' });
    const audio = el('audio', { id: 'ttsModalQwenAudio', controls: '', preload: 'none', style: 'display:none; width:100%; margin-top:10px;' });
    const approve = el('button', { id: 'ttsModalQwenApprove', type: 'button', className: 'btn btn-primary',
        style: 'display:none; margin-top:12px;' }, 'Sprachprobe gehört – Hörbuch erstellen');
    const download = el('a', { id: 'ttsModalQwenDownload', href: '#', download: 'book.m4b',
        style: 'display:none; margin:12px 0; color:#7dd3fc;' }, 'Fertiges Hörbuch herunterladen (M4B)');
    const studio = el('a', { id: 'ttsModalQwenStudio', href: '/audiobook/',
        style: 'display:inline-block; margin:12px 0; color:#7dd3fc;' }, 'Ausführliches Hörbuchstudio öffnen');
    state.append(notice, progress, audio, approve, download, el('div', {}, ''), studio);
    section.append(state);
    modal.querySelector('.modal-body').append(section);

    // Keep native TBL's Edge/Chatterbox behavior. Our patch adds Qwen to
    // upstream's provider change handler and this only sets the initial view.
    if (epub) {
        provider.value = 'qwen-local';
        document.getElementById('ttsModalEdgeOptions').style.display = 'none';
        document.getElementById('ttsModalChatterboxOptions').style.display = 'none';
        document.getElementById('ttsModalGpuStatus').style.display = 'none';
        section.style.display = 'block';
        document.getElementById('ttsModalGenerate').textContent = 'Sprachprobe erzeugen';
    }
}

export async function generateQwenFromTbl({ filename, modal, generateBtn }) {
    const section = document.getElementById('ttsModalQwenJob');
    const notice = document.getElementById('ttsModalQwenNotice');
    const progress = document.getElementById('ttsModalQwenProgress');
    const audio = document.getElementById('ttsModalQwenAudio');
    const approve = document.getElementById('ttsModalQwenApprove');
    const download = document.getElementById('ttsModalQwenDownload');
    const studio = document.getElementById('ttsModalQwenStudio');
    if (!filename.toLowerCase().endsWith('.epub')) {
        setNotice(notice, 'Deutsche TTS-Stimmen unterstützen in dieser Integration nur EPUB-Dateien.', true);
        return;
    }
    section.style.display = 'block';
    generateBtn.disabled = true;
    generateBtn.textContent = 'Projekt wird vorbereitet …';
    approve.style.display = 'none';
    download.style.display = 'none';
    audio.style.display = 'none';
    setNotice(notice, 'EPUB wird für die deutsche Hörbuchproduktion importiert …', false);

    let bookId;
    let timer = null;
    let polling = false;
    let phase = 'preview';
    function clearTimer() {
        if (timer !== null) window.clearInterval(timer);
        timer = null;
    }

    async function update() {
        if (!modal.isConnected) { clearTimer(); return; }
        if (polling || !bookId) return;
        polling = true;
        try {
            const info = await request('/books/' + bookId);
            progress.max = Math.max(1, info.total || 1);
            progress.value = Math.min(progress.max, info.done || 0);
            if (info.status === 'failed') {
                clearTimer();
                setNotice(notice, 'Generierung fehlgeschlagen: ' + (info.errors || []).join('; '), true);
                generateBtn.disabled = false;
                generateBtn.textContent = 'Erneut versuchen';
                return;
            }
            if (info.status === 'preview_ready' && phase === 'preview') {
                clearTimer();
                phase = 'approval';
                setNotice(notice, 'Sprachprobe fertig. Bitte vollständig anhören und erst danach freigeben.', false);
                audio.src = API + '/books/' + bookId + '/download/preview';
                audio.style.display = 'block';
                approve.style.display = 'inline-block';
                generateBtn.style.display = 'none';
                return;
            }
            if (info.status === 'completed' && phase === 'full') {
                clearTimer();
                phase = 'done';
                setNotice(notice, 'Hörbuch fertig. Die M4B-Datei enthält Kapitelmarken.', false);
                download.href = API + '/books/' + bookId + '/download/m4b';
                download.style.display = 'inline-block';
                generateBtn.style.display = 'none';
                return;
            }
            if (info.status === 'paused' || info.status === 'cancelled') {
                clearTimer();
                setNotice(notice, 'Job wurde angehalten. Über das Hörbuchstudio fortsetzen.', false);
                return;
            }
            setNotice(notice, (phase === 'full' ? 'Hörbuch wird erstellt' : 'Sprachprobe wird erstellt') +
                ' (' + (info.done || 0) + '/' + (info.total || '?') + ' Segmente) …', false);
        } catch (err) {
            clearTimer();
            setNotice(notice, err.message, true);
        } finally {
            polling = false;
        }
    }

    try {
        const project = await request('/import-translated', 'POST', { name: filename });
        bookId = project.id;
        studio.href = '/audiobook/?book=' + encodeURIComponent(bookId);
        const backend = document.getElementById('ttsModalGermanEngine').value;
        const speaker = backend === 'qwen-customvoice' ?
            document.getElementById('ttsModalQwenVoice').value : 'Thorsten';
        const speed = Number(document.getElementById('ttsModalQwenSpeed').value);
        const skip_toc = document.getElementById('ttsModalSkipToc').checked;
        await request('/books/' + bookId + '/config', 'PUT', {
            settings: { backend, speaker, speed, skip_toc }
        });
        await request('/books/' + bookId + '/run', 'POST', { preview: true });
        generateBtn.textContent = 'Sprachprobe läuft …';
        timer = window.setInterval(update, 2000);
        await update();
        approve.addEventListener('click', async () => {
            approve.disabled = true;
            try {
                await request('/books/' + bookId + '/approve', 'POST');
                await request('/books/' + bookId + '/run', 'POST', { preview: false });
                phase = 'full';
                approve.style.display = 'none';
                audio.style.display = 'none';
                generateBtn.textContent = 'Hörbuch wird erstellt …';
                timer = window.setInterval(update, 2000);
                await update();
            } catch (err) {
                approve.disabled = false;
                setNotice(notice, err.message, true);
            }
        }, { once: false });
    } catch (err) {
        clearTimer();
        setNotice(notice, err.message, true);
        generateBtn.disabled = false;
        generateBtn.textContent = 'Sprachprobe erneut versuchen';
        if (bookId) studio.href = '/audiobook/?book=' + encodeURIComponent(bookId);
    }
}
