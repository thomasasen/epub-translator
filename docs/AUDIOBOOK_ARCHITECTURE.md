# Architekturentscheidung: EPUB → Fachhörbuch (ADR-001)

**Stand:** 2026-11-06. **Status:** implementierter Feature-Branch, GPU-End-to-End noch unbestätigt.

## Entscheidung

Die Übersetzungsanwendung von [TranslateBooksWithLLMs](https://github.com/hydropix/TranslateBooksWithLLMs) bleibt unangetastet. Das Hörbuchstudio ist ein separater FastAPI-Dienst auf **127.0.0.1:5100**, über denselben Nginx-Proxy auf **Port 3000** unter `/audiobook/`. Auf Wunsch des Betreibers ist **HTTP Basic Auth vollständig deaktiviert**. Wer den RunPod-Proxy-Link besitzt, kann die Oberfläche ohne Anmeldung nutzen; insbesondere Dateien hoch- und herunterladen. Für öffentliche Mehrbenutzernutzung ungeeignet.

Pfad: `/workspace/epub-translator/audiobooks/{job-id}/`, Status in `manifest.json`, atomar via `os.replace` geschrieben. Quelle `source.epub`; Audiodateien in `segments/`, Kapitel in `chapters/`; Ergebnisse `preview.mp3`, `book.m4b`, `quality.json`.

Datenfluss: EPUB-ZIP-Validierung → OPF-Spine-/XHTML-Extraktion → explizite Auslassungsbilanz → Sprechnormalisierung/Glossar → Segmente → GPU-TTS-Engine → Segmentprüfung → Freigabeprobe → Vollproduktion → FFmpeg-Lautheitsbearbeitung/MP3/M4B → optionale ASR.

## Modellentscheid

**Primär:** `Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice`, [Apache-2.0](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice), Implementierung `qwen-tts==0.1.1`. Unterstützt Deutsch und neun feste Stimmen; `generate_custom_voice(text, language="German", speaker=..., instruct=...)` ist offiziell dokumentiert. Standardstimme Ryan ist eine **vorläufige Wahl**, keine empirisch beste deutsche Fachbuchstimme. Das Modell bietet keine dokumentierte direkte IPA-/SSML-Phonemschnittstelle. Die Standardglossare wirken daher ausschließlich auf den **Sprechtext**, nicht auf die EPUB-Datei. Für natürliches Deutsch ist eine manuelle Prüfung jeder Glossareinstellung erforderlich.

**Andere Modelle:** Chatterbox Multilingual V3 unterstützt Deutsch und ist MIT-lizenziert, wird aber laut Anbieter seit August 2026 **nicht mehr gepflegt**; keine Qualitätsmessungen dieses Projekts. Qwen3-TTS Base kann Voice Cloning, benötigt aber Einwilligung und Referenzmaterial; hier bewusst nicht als Standard. Qwen3-TTS VoiceDesign entwirft Stimmen anhand von Textanweisungen; eine feste CustomVoice-Sprecheridentität ist einfacher reproduzierbar. 25Hz-Versionen sind Gegenstand von Forschungsbenchmarks, aber nicht allein dadurch als stabile öffentlich verfügbare Pakete verifiziert. Es gibt **keinen** selbst durchgeführten Hörvergleich; eine Rangliste nach subjektiver Hörqualität wäre unbelegt.

**[khimaros/autiobook](https://github.com/khimaros/autiobook)** kann EPUBs, segmentierte Audios, Wiederaufnahme und M4B. Es wurde als Architekturvorbild bewertet, aber **kein GPL-3.0-Code übernommen**. Die GPL-Kompatibilität mit dem MIT-Bestand und der separaten AGPL-3.0-Übersetzungsanwendung wäre sonst gesondert zu prüfen. autiobook ist nicht als Laufzeitabhängigkeit eingebunden.

## Schnittstellen

`QwenCustomVoiceEngine.synthesize(text, destination, speaker, instruction, seed)` und `MockEngine` teilen dieselbe Schnittstelle. Backend wird per `create_engine()` gewählt; neue Engines müssen die WAV- und Qualitätsanforderungen erfüllen. Mock nur mit explizitem `AUDIOBOOK_TEST_MOCK=1` nutzbar. `core.py`, `pipeline.py`, `server.py`, `cli.py` bleiben getrennt; CLI und UI verwenden dieselben Pipelinefunktionen.

## GPU und Isolation

Der Start findet ausschließlich bei erkannter CUDA-GPU mit ausreichend freiem VRAM statt (konservativ **mindestens 9000 MiB frei** vor Modellladung; **keine Hardwaregarantie**). TTS und Ollama teilen dieselbe GPU. Die Pipeline lädt Qwen erst bei Bedarf und gibt das Modell nach dem Auftrag frei. Sie entlädt **kein** Ollama-Modell automatisch und unterbricht daher keinen schon gestarteten Übersetzungsauftrag. Wenn Ollama VRAM bindet, zuerst die Übersetzung fertigstellen und das Ollama-Modell kontrolliert mit `ollama stop MODEL` entladen. Eine vollständige, race-sichere Verhinderung **zeitgleich neu gestarteter** Übersetzungen ist ohne Upstream-Koordinationsschnittstelle noch nicht möglich. Bei OOM stoppt der Auftrag mit Fehlerstatus; gültige Segmente bleiben erhalten.

Persistente Qwen-Modellgewichte liegen durch `HF_HOME` unter `/workspace/epub-translator/hf-cache`. Getrennte virtuelle Python-Umgebung `tts-venv`. Upstream-Commit/Python-Umgebung für Übersetzung bleiben unabhängig.

## Sicherheit und Grenzen

Vor Extraktion werden Größen, Anzahl der Dateien, relative Pfade, Kompressionsverhältnis und Einzeldateigröße geprüft. Die Web-API erlaubt nur generierte Projekt-IDs und explizit freigegebene Ausgabedateien. TTS/FFmpeg-Aufrufe nutzen Argumentlisten statt Shell. Kein externer Speech-API-Zugriff; Hugging Face lädt Gewichte bei der ersten Verwendung. Kein Freigabeautomatismus durch eine niedrige ASR-Fehlerquote.

Nicht bestätigt sind GPU-Lasttest, Langzeit-Stimmkonsistenz, vollständiger Sprachvergleich, Robustheit jedes komplexen EPUBs, Echtzeit-Kollision mit Übersetzung sowie Produktivbetrieb. Rollout erst nach GPU-Smoke-Test; siehe AUDIOBOOK_USAGE.md.
