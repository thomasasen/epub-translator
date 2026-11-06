# Hörbuchstudio: Installation, RunPod und Bedienung

## Sicherer Test ohne produktiven Merge

Startbefehl für einen **Test-Pod mit Feature-Branch** (nicht produktiven Pod überschreiben):

```bash
bash -lc 'set -euo pipefail; curl -fsSL https://raw.githubusercontent.com/thomasasen/epub-translator/feature/audiobook-high-fidelity/bootstrap.sh -o /tmp/epub-bootstrap.sh; export EPUB_DEPLOY_REF=feature/audiobook-high-fidelity; exec bash /tmp/epub-bootstrap.sh'
```

RunPod: GPU 24 GB oder 48 GB, persistenter Mount `/workspace`, HTTP-Port **nur 3000**. Das Skript verwendet ansonsten dieselbe Übersetzungs-Basis wie bisher, lädt für TTS aber die Version aus `EPUB_DEPLOY_REF`. `AUDIOBOOK_ENABLED=0` deaktiviert den Audiobereich. Die bisherigen Variablen **EPUB_USERNAME und EPUB_PASSWORD werden nicht mehr benötigt** und sollten aus dem RunPod-Template gelöscht werden. Zugriff per RunPod → Connect → HTTP 3000, **ohne Passwort**. Der Link selbst ist damit der einzige praktische Zugriffsschutz: nicht öffentlich teilen, keine vertraulichen Bücher auf einem öffentlich bekannten Pod verwenden.

Nach Prüfung und anschließendem Merge kann der reguläre `main/bootstrap.sh`-Startbefehl verwendet werden (mit `EPUB_DEPLOY_REF=main` oder ohne Variable).

## Hörbuch erstellen

1. Den bekannten RunPod-Proxy-Link öffnen; unter `/audiobook/` das Hörbuchstudio aufrufen.
2. Eine bereits übersetzte EPUB aus `translated_files` wählen oder eine deutsche EPUB direkt hochladen. Erneutes Übersetzen ist nicht notwendig.
3. Kapitel, geschätzte Dauer und ausgeschlossene Bestandteile prüfen. Tabellen werden zunächst zur manuellen Nachprüfung gemeldet.
4. Sprecher, Sprechtempo, Ausspracheglossar und optional Bildunterschriften/Fußnoten einstellen. Danach **Sprachprobe erzeugen**.
5. Sprachprobe vollständig anhören; vor allem Fachbegriffe, Zahlen, Pause und Stimmenkontinuität kontrollieren. Nur bei Zufriedenheit **Sprachprobe freigeben**.
6. **Ganzes Hörbuch erzeugen** starten; bei Unterbrechung **Fortsetzen**. Fertiges `book.m4b` mit Kapitelmarken laden oder MP3-Kapitel verwenden.
7. Qualitätsbericht lesen und Warnsegmente erneut generieren. Nach einer erneuten Generierung des Segments muss das M4B neu exportiert werden.

**Bei knapper GPU:** Übersetzung zu Ende bringen, `ollama ps` prüfen und das Ollama-Modell nach dem Ende per `ollama stop <modellname>` entladen. Nicht während einer laufenden Übersetzung entladen. Der Modellwechsel erfolgt nicht automatisch.

## CLI

```bash
cd /workspace/epub-translator/deployment
export PYTHONPATH=$PWD
PY=/workspace/epub-translator/tts-venv/bin/python
$PY -m audiobook.cli import /pfad/buch.epub
$PY -m audiobook.cli books
$PY -m audiobook.cli chapters BUCH_ID
$PY -m audiobook.cli status BUCH_ID
$PY -m audiobook.cli preview BUCH_ID
$PY -m audiobook.cli approve BUCH_ID
$PY -m audiobook.cli run BUCH_ID
$PY -m audiobook.cli qa BUCH_ID
$PY -m audiobook.cli qa BUCH_ID --asr
$PY -m audiobook.cli rerender BUCH_ID 0001-00002
$PY -m audiobook.cli export BUCH_ID
```

`--asr` benötigt das optionale GPU-Modul `faster-whisper==1.1.1`; manuell nachinstallieren. CLI-Einstellungen über `config BUCH_ID --speaker Ryan --speed 0.9 --glossary ./mein-glossar.json`. Wiederaufnahme funktioniert nach Prozess- und Pod-Neustart aufgrund der gültigen WAV-Segmente/Fingerprints. Unterbrechungen laufen grundsätzlich erst nach dem gerade erzeugten Segment aus.

## Qualitätsprüfung und GPU-Smoke-Test

Im RunPod-Terminal:

```bash
curl -fsS http://127.0.0.1:5000/api/health
curl -fsS http://127.0.0.1:5100/audiobook/health
curl -fsS http://127.0.0.1:3000/audiobook/health
nvidia-smi
ollama ps
tail -n 100 /workspace/epub-translator/logs/audiobook.log
```

Ein deutsches Probe-EPUB importieren, einen 5–10-Minuten-Previewtest machen (falls das Buch genug passende Abschnitte enthält), anhören und danach einen kurzen Mehrkapiteljob einschließlich M4B starten. `ffprobe -v error -show_chapters -show_format /workspace/epub-translator/audiobooks/BUCH_ID/book.m4b` kontrolliert Container und Kapitel. Externen Player zum Gegencheck verwenden.

**Bis zum ersten echten Pod-Durchlauf gilt keine Aussage über tatsächliche Sprachqualität, OOM-Freiheit oder Produktionsreife als verifiziert.** CI verwendet ausdrücklich Mock-Audio, keine Qwen-GPU-Inferenz.

## Fehlerdiagnose

Bei `CUDA`/VRAM-Fehlern: `nvidia-smi`, `ollama ps`, GPU-Zuweisung und `AUDIOBOOK_ATTENTION=sdpa` prüfen. Bei Nginx 502: zuerst die beiden lokalen Healthchecks prüfen. Bei fehlerhaften Segmenten: Qualitätsbericht und Segment-ID verwenden. Nach Änderungen am Glossar oder an den Stimmeinstellungen muss die neue Vorschau freigegeben werden. `HF_HOME` zeigt auf persistente Modellgewichte; Gewichte werden nicht bei jedem Pod-Neustart neu geladen.

Die zugrunde liegenden Modelle sind nicht automatisch für jeden urheberrechtlich geschützten Text zur öffentlichen Veröffentlichung freigegeben. Nutzungsrechte an EPUB und etwaigen Stimmen sind unabhängig vom Software-Lizenzstatus zu prüfen.
