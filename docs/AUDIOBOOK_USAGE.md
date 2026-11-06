# Hörbuchstudio: Installation, RunPod und Bedienung

## Sicherer Test ohne produktiven Merge

Startbefehl für einen **Test-Pod mit Feature-Branch** (nicht produktiven Pod überschreiben):

```bash
bash -lc 'set -euo pipefail; curl -fsSL https://raw.githubusercontent.com/thomasasen/epub-translator/feature/audiobook-high-fidelity/bootstrap.sh -o /tmp/epub-bootstrap.sh; export EPUB_DEPLOY_REF=feature/audiobook-high-fidelity; exec bash /tmp/epub-bootstrap.sh'
```

RunPod: GPU 24 GB oder 48 GB, persistenter Mount `/workspace`, HTTP-Port **nur 3000**. Das Skript verwendet ansonsten dieselbe Übersetzungs-Basis wie bisher, lädt für TTS aber die Version aus `EPUB_DEPLOY_REF`. `AUDIOBOOK_ENABLED=0` deaktiviert den Audiobereich. Die bisherigen Variablen **EPUB_USERNAME und EPUB_PASSWORD werden nicht mehr benötigt** und sollten aus dem RunPod-Template gelöscht werden. Zugriff per RunPod → Connect → HTTP 3000, **ohne Passwort**. Der Link selbst ist damit der einzige praktische Zugriffsschutz: nicht öffentlich teilen, keine vertraulichen Bücher auf einem öffentlich bekannten Pod verwenden.

Nach Prüfung und anschließendem Merge kann der reguläre `main/bootstrap.sh`-Startbefehl verwendet werden (mit `EPUB_DEPLOY_REF=main` oder ohne Variable).

## Zwei Oberflächen, ein Qwen3-TTS-Backend

Das ursprüngliche **TBL „Generate Audiobook“**-Fenster bleibt erhalten. Für EPUB-Dateien
erhält es zusätzlich **Qwen3-TTS (lokale GPU · deutsches Fachbuch)** neben den
bestehenden Optionen **Edge TTS** und **Chatterbox**. Die voreingestellte
TBL-Zielsprache wird auf Deutsch gestellt; die anderen Sprachen und Anbieter
bleiben auswählbar.

**Qwen im TBL-Dialog:** EPUB in der TBL-Dateiliste auswählen → Kopfhörer-
Symbol → Qwen3-TTS wählen → Sprecherstimme und Tempo einstellen →
**Sprachprobe erzeugen** → Probe anhören → explizit freigeben →
Hörbuch erstellen → M4B im selben Dialog herunterladen. Für Glossar,
Kapitelbearbeitung, detaillierten Jobstatus und Korrekturen öffnet der Link
„Ausführliches Hörbuchstudio öffnen“ das jeweilige Projekt unter `/audiobook/`.

**Separate Oberfläche:** Das bisherige vollständige Hörbuchstudio bleibt
unter `/audiobook/` unverändert verfügbar und nutzt denselben Backenddienst.
Die Ergebnisse und Projekte sind zwischen beiden Oberflächen geteilt.

**Technik und Updatefestigkeit:** Die TBL-Version bleibt auf den bisherigen
Commit `0cc31bc7f4aeedfcb3fe904eeaebd15d6fa0ad1f` gepinnt. Beim
Pod-Start wendet `scripts/patch_tbl_tts.py` nur einen überprüften,
idempotenten UI-Patch auf das lokale Checkout an. Edge TTS, Chatterbox
und der TBL-Backendcode werden nicht verändert. Wenn der Upstream ein
unbekanntes Dialoglayout hat, bricht die Integration mit einer klaren
Fehlermeldung ab, statt stillschweigend falsche Stellen zu verändern.
Bei `AUDIOBOOK_ENABLED=0` wird der Patch entfernt.

Die native TBL-Qwen-Integration arbeitet derzeit nur mit **EPUB**
aus dem gemeinsamen Ausgabeverzeichnis `translated_files`. Andere TBL-Dateitypen
verwenden weiterhin die ursprünglichen Anbieter. Auch diese Oberfläche
fordert vor der vollständigen Qwen-Produktion eine ausdrücklich angehörte
und freigegebene Sprachprobe. Das Original-EPUB wird nicht verändert.

## Hörbuch erstellen

1. Den bekannten RunPod-Proxy-Link öffnen; unter `/audiobook/` das Hörbuchstudio aufrufen.
2. Eine bereits übersetzte EPUB aus `translated_files` wählen oder eine deutsche EPUB direkt hochladen. Erneutes Übersetzen ist nicht notwendig.
3. Kapitel, geschätzte Dauer und ausgeschlossene Bestandteile prüfen. Tabellen werden zunächst zur manuellen Nachprüfung gemeldet.
4. Sprecher, Sprechtempo, Qualitätsprofil, Ausspracheglossar und optional Bildunterschriften/Fußnoten einstellen. Einzelbegriffe können mit dem Vorlesen-Knopf geprüft werden. Danach **Sprachprobe erzeugen**.
5. Sprachprobe vollständig anhören; vor allem Fachbegriffe, Zahlen, Pause und Stimmenkontinuität kontrollieren. Nur bei Zufriedenheit **Sprachprobe freigeben**.
6. **Ganzes Hörbuch erzeugen** starten. Mit Pausieren oder Abbrechen wird nach dem aktuellen Segment gestoppt; die bisherigen Segmente bleiben erhalten. Anschließend kann **Fortsetzen** genutzt werden. Fertiges `book.m4b` mit Kapitelmarken laden oder MP3-Kapitel verwenden.
7. Qualitätsbericht lesen und Warnsegmente erneut generieren. Nach einer erneuten Generierung des Segments muss das M4B neu exportiert werden.

**Bei knapper GPU:** Übersetzung zu Ende bringen, `ollama ps` prüfen und das Ollama-Modell nach dem Ende per `ollama stop <modellname>` entladen. Nicht während einer laufenden Übersetzung entladen. Der Modellwechsel erfolgt nicht automatisch.

## Umfang: TBL-Standard statt KI-Zusatzinhalte

Die Hörbuchproduktion verwendet ausschließlich die tatsächlich im EPUB vorhandenen Textinhalte. TBL bewahrt beim Übersetzen EPUB-Struktur und Formatierung; es erzeugt im Standard keine eigenständigen Beschreibungen von Bildern oder Diagrammen. Daher beschreibt das Hörbuchstudio Abbildungen **nicht** automatisch und setzt **keine** zusätzliche Vision-KI ein. Bilder ohne Sprechertext werden protokolliert, Tabellen zur Prüfung gemeldet. Bereits vorhandene Bildunterschriften können optional vorgelesen werden. Es werden keine Bildinhalte hinzuerfunden.

Als Voreinstellung verwendet Qwen3-TTS ausdrücklich `language="German"` und einen **lebendigen, leicht zügigen, aber gut verständlichen** Sprechstil für deutschsprachige Sach- und Fachbücher. Das Starttempo beträgt **1,05×** (FFmpeg-Tempoprozessierung); 1,0× und 1,1× bleiben auswählbar. Der Vortrag soll interessiert und professionell wirken, nicht monoton, hektisch oder theatralisch. Es werden keine künstlichen Atemgeräusche eingefügt. Die Hörprobe verwendet dieselbe Tempobearbeitung wie der Export. Bei bereits angelegten Projekten bleiben die gespeicherten Einstellungen unverändert und können im Hörbuchstudio angepasst werden. Stimme, Aussprache und Langzeithörbarkeit müssen vor einer längeren Produktion durch die verpflichtende Sprachprobe geprüft werden; ein realer GPU-Hörtest steht noch aus.

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
