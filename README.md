# EPUB Translator: RunPod + Ollama + TranslateBooksWithLLMs

Dieses Repository enthält ein startfertiges **RunPod-GPU-Deployment** für [TranslateBooksWithLLMs](https://github.com/hydropix/TranslateBooksWithLLMs) zusammen mit einem **lokal auf der GPU laufenden Ollama-Modell**. Damit gibt es keine OpenRouter-API-Limits oder KI-API-Gebühren. Die Laufzeit des RunPod-GPU-Pods und der Speicher bleiben kostenpflichtig.

## 1. Einmalig ein RunPod-Pod-Template anlegen

In [RunPod](https://console.runpod.io/pods) ein **Custom Pod Template** erstellen, nicht Serverless.

| Template-Feld | Eintrag |
|---|---|
| Container Image | `runpod/pytorch:1.0.3-cu1281-torch291-ubuntu2404` |
| Docker Entrypoint | **Voreinstellung beibehalten** |
| Docker Start Command | siehe folgenden Befehl |
| Expose HTTP Ports | **3000** |
| Volume Mount Path | **/workspace** |
| Persistent Volume | **100 GB empfohlen** |
| Container Disk | mindestens **20 GB** |
| GPU | **48 GB VRAM** bevorzugt, **24 GB** möglich |

**Einziger Docker Start Command:**

```bash
bash -lc 'set -euo pipefail; curl -fsSL https://raw.githubusercontent.com/thomasasen/epub-translator/main/bootstrap.sh -o /tmp/epub-bootstrap.sh; exec bash /tmp/epub-bootstrap.sh'
```

RunPod überschreibt damit das Docker-CMD; der NVIDIA-Entrypoint des Basis-Images bleibt aktiv. Das Skript installiert selbstständig Ollama, das Modell, Python-Abhängigkeiten und den passwortgeschützten Reverse-Proxy. Ein vollautomatischer Start erfordert ausgehenden Internetzugang.

## 2. Zwei Pflichtvariablen eintragen

Im Template unter **Environment Variables**:

| Name | Wert |
|---|---|
| `EPUB_USERNAME` | z. B. `translator` |
| `EPUB_PASSWORD` | ein starkes Passwort mit **mindestens 12 Zeichen** |

Der Start **schlägt ohne diese Variablen absichtlich fehl**. Das Passwort nicht in das öffentliche GitHub-Repository oder in den Startbefehl schreiben. Ein Template mit eingetragenem Passwort nicht öffentlich teilen.

Den Pod anschließend aus dem Template starten. Über **RunPod → Connect → HTTP Port 3000** den HTTPS-Link öffnen (üblicherweise `https://<pod-id>-3000.proxy.runpod.net`). Die Browser-Anmeldung erfolgt mit den beiden Variablen.

Der erste Start kann wegen des großen Modelldownloads und der Paketinstallation dauern. Modelle, Dateien und Checkpoints liegen auf dem persistenten Volume, daher brauchen spätere Starts die Downloads normalerweise nicht erneut.

## 3. Modelle und Qualitätsvorgaben

Das Skript wählt automatisch nach dem VRAM **einer einzelnen GPU**:

| VRAM | Modell | Größe | Kontext |
|---|---|---|---|
| ab 44.000 MiB, typischerweise 48-GB-GPU | `gemma4:31b-it-q8_0` | ca. 34 GB | 8192 |
| 22.000–43.999 MiB, typischerweise 24-GB-GPU | `gemma4:31b-it-qat` | ca. 19 GB | 4096 |
| darunter | Abbruch mit Hinweis | – | – |

[Gemma-4-Tags bei Ollama](https://ollama.com/library/gemma4/tags). Die Q8-Variante nutzt eine höhere Gewichtspräzision, ist jedoch **nicht automatisch** die sprachlich beste Lösung. Für hohe Übersetzungsqualität erst ein Kapitel testen und gegen andere Modelle sowie das Original prüfen.

Optionale Environment Variables:

| Name | Beschreibung |
|---|---|
| `EPUB_MODEL` | anderen Ollama-Modellnamen verwenden; dann keine automatische Modellauswahl |
| `EPUB_CONTEXT` | Kontextfenster in Tokens; mindestens 2048 |
| `MAX_TOKENS_PER_CHUNK` | Standard 800; bei EPUB-Formatproblemen testweise 450 |
| `TBL_REF` | bestimmter Git-Commit/Tag des Upstreams; Standard: `0cc31bc7f4aeedfcb3fe904eeaebd15d6fa0ad1f` (v1.5.18) |

Für eine gleichbleibende Übersetzung sind **PARALLEL_TRANSLATIONS=1** und ein festes Ollama-Kontextfenster konfiguriert. In der Weboberfläche Englisch → Deutsch wählen, Glossar und Stilvorgaben kontrollieren und auf Wunsch Refinement einschalten. Ein zweiter Durchgang kann Texte glätten, ist aber keine Garantie gegen Übersetzungsfehler.

## 4. Persistenz und Verzeichnisstruktur

Alle Projektdateien liegen auf dem RunPod-Volume unter `/workspace/epub-translator/`:

```text
/workspace/epub-translator/
├── upstream/           TranslateBooksWithLLMs, Python venv, Checkpoints und Uploads
├── ollama-models/      heruntergeladene Modellgewichte
├── translated_files/   fertige EPUB-Übersetzungen
└── logs/               ollama.log, translator.log, nginx.log, pip.log
```

Ein **Pod-Stopp unterbricht** eine laufende Übersetzung. Das Upstream-Projekt verfügt über Checkpoints zum späteren Fortsetzen. Die Wiederaufnahme sollte zunächst mit einem Testbuch geprüft werden. Beim Entfernen des Pods darauf achten, das Volume nicht versehentlich zu löschen.

RunPod berechnet GPU-Laufzeit, solange der Pod läuft, und gegebenenfalls persistenten Speicher. Ergebnisse nach Abschluss herunterladen und den Pod stoppen.

## 5. Zugriffsschutz

Der RunPod-Webproxy ist aus dem Internet erreichbar. Deshalb lauscht **Nginx mit HTTP Basic Auth auf Port 3000**. Die interne Übersetzungs-App wird ausschließlich an `127.0.0.1:5000` und Ollama an `127.0.0.1:11434` gebunden. **Ports 5000 und 11434 niemals in RunPod exponieren.**

Der Zugriff über den RunPod-HTTPS-Proxy ist TLS-geschützt. Nginx verlangt das Passwort auch für API-, Upload- und WebSocket-Zugriffe. Dies ist für einen privaten Einzelbenutzer-Pod ausgelegt, nicht für eine öffentliche Mehrbenutzer-Anwendung.

## 6. Fehlerdiagnose im RunPod-Terminal

```bash
nvidia-smi
ollama list
ollama ps

# Interner App-Healthcheck
curl -fsS http://127.0.0.1:5000/api/health

# Muss OHNE Login 401 liefern
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:3000/

tail -n 100 /workspace/epub-translator/logs/translator.log
tail -n 100 /workspace/epub-translator/logs/ollama.log
```

Bei einer 502-Antwort in der Weboberfläche prüfen, ob der Start vollständig durchgelaufen ist. Bei zu wenig VRAM ein kleineres Modell, kleinere Kontextlänge oder eine größere GPU wählen. Bei fehlenden Dateien den Mount-Pfad und die Persistenz des Volumes prüfen.

## 7. Qualitätssicherung nach Red-Team-Review

Für hochwertige Übersetzungen genügt es nicht, eine gute GPU und ein großes Modell zu verwenden. Das Repository enthält deshalb eine ausführliche [**Qualitätsstrategie und Red-Team-Auswertung**](QUALITY.md).

**Vor der Vollübersetzung:** Vergleiche mehrere repräsentative Kapitel mit demselben Glossar und identischen Einstellungen. Bewerte Bedeutungstreue, Vollständigkeit, natürliches Deutsch, Konsistenz und Erzählstil. Die erste Auswahl `gemma4:31b` ist ein Ausgangspunkt und kein garantierter Sieger.

**Nach der Übersetzung:** Das Skript `audit_epub.py` ist auf RunPod unter `/workspace/epub-translator/audit_epub.py` verfügbar. Es prüft EPUB-Struktur, Kapitel, Absätze, Links, Bilder und auffällig unveränderte Textblöcke. Ein Beispiel:

```bash
find /workspace/epub-translator -iname '*.epub'
python3 /workspace/epub-translator/audit_epub.py \
  "/pfad/zum/original.epub" "/pfad/zur/uebersetzung.epub" \
  --json "/workspace/epub-translator/translated_files/audit.json"
```

Bei kritischen Abweichungen meldet die Prüfung einen Fehlercode. Warnungen müssen überprüft werden; optional behandelt `--strict` auch Warnungen als Fehler. **Diese Prüfung bewertet keine Übersetzungssemantik.** Auch einen EPUB-Reader-Test und manuelle Stichproben durchführen.

Nach dem Ollama-Modelldownload startet das Bootstrapskript nun eine echte Test-Inferenz und zeigt bei möglichem CPU-Offloading eine Warnung. Dadurch entdecken wir Modell-Ladeprobleme, bevor du ein ganzes Buch startest.

## 8. Stand der Validierung

Eine [GitHub-Actions-Prüfung](.github/workflows/shell-lint.yml) kontrolliert Bash-Syntax, ShellCheck sowie synthetische EPUB-Integritätstests. **Ein Live-Test auf einem RunPod-Pod wurde noch nicht durchgeführt**; insbesondere GPU-Erkennung, WebSocket, Passwortanmeldung und eine vollständige EPUB-Übersetzung müssen dort getestet werden.

**Quellen:** [TranslateBooksWithLLMs](https://github.com/hydropix/TranslateBooksWithLLMs) · [Upstream-Dokumentation](https://github.com/hydropix/TranslateBooksWithLLMs/blob/main/docs/PROVIDERS.md) · [RunPod-Beispieltemplate](https://github.com/runpod-workers/pod-template).

Die hier enthaltenen Deployment-Skripte folgen der vorhandenen MIT-Lizenz. TranslateBooksWithLLMs wird nicht mitgeliefert und steht separat unter AGPL-3.0.
