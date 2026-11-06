# Qualitätsstrategie und Red-Team-Befunde

Ziel: **höchstmögliche Übersetzungsqualität** bei EPUB-Büchern, nicht bloß eine möglichst schnelle oder billige Übersetzung. Diese Anleitung ist für **Englisch → Deutsch** ausgelegt, lässt sich aber auf andere Sprachen übertragen.

## Red-Team-Ergebnis

| Risiko | Einstufung vor der Überarbeitung | Maßnahme / Restrisiko |
|---|---|---|
| Festes Modell, keine Vergleichsmessung | **hoch** | Vergleich mindestens zweier Modelle an echten Kapiteln; Q8 ist kein Qualitätsbeweis |
| Ausgelassene / unübersetzte Passagen | **hoch** | Neues Offline-Werkzeug `audit_epub.py`; bewertet Struktur und offensichtliche Auslassungen, **nicht** die Semantik |
| Falsche Eigennamen, Terminkonsistenz, Anrede | **hoch** | Glossar **vorher** extrahieren und manuell prüfen; mehrere Textstellen vergleichen |
| Refinement verschiebt Fakten oder fügt Inhalte hinzu | **hoch** | Nur mit Quellenvergleich einsetzen; nicht automatisch als Qualitätsgewinn ansehen |
| Kurze Kontexte, Qualitätsverlust an Abschnittsgrenzen | **mittel/hoch** | Sequenzielle Übersetzung, begrenzte Chunk-Größe, eigene Kontext-/Abschnittstests |
| Modell passt nicht vollständig auf GPU | **hoch** für Kosten/Laufzeit | Tatsächlicher Ollama-Inferenztest und Warnung bei CPU-Offloading |
| Ausgabe beschädigt (EPUB, Verweise, Bilder) | **hoch** | Offline-Strukturprüfung mit Warnungen für Anker, Bilder und Kapitel |
| Offener Zugriff über RunPod-Proxy | **hoch, vom Betreiber bewusst akzeptiert** | Basic Auth auf Wunsch deaktiviert. HTTPS-Proxy-Link geheim halten; keine Veröffentlichung von 5000/5100/11434 |
| Fehlende Validierung auf echter Hardware | **offen** | ShellCheck und Regressionstests vorhanden; vollständiger RunPod-E2E-Test **noch ausstehend** |

## 1. Modellwahl als Experiment behandeln

Das voreingestellte `gemma4:31b-it-q8_0` ist ein **vernünftiger erster Kandidat**, kein nachgewiesener Sieger. Im [Benchmark des Upstream-Projekts für Deutsch](https://github.com/hydropix/TranslateBooksWithLLMs/wiki/Language-german) erreichte `gemma4:31b` 7,7/10, während `gemma3:27b` bei 7,5/10 lag; die Stichprobe umfasst nur kurze Testtexte, keine konsistente Buchübersetzung über hunderte Seiten. Der Bewertungsansatz ist **nicht** als unabhängiger Beweis für die beste Buchübersetzung zu verstehen.

[Google TranslateGemma](https://blog.google/innovation-and-ai/technology/developers-tools/translategemma/) ist eigens für Übersetzungen trainiert und ist als Vergleich sinnvoll. **Aber:** Vor der Bewertung muss überprüft werden, ob das Promptformat von TranslateBooksWithLLMs das Modell korrekt anspricht. Einen fehlerhaften Prompt sollte man dem Modell nicht als Qualitätsmangel anrechnen. Weitere Kandidaten können `qwen3.5` oder spätere geeignete Modelle sein; Modellnamen und Verfügbarkeit vor dem Test unter [Ollama](https://ollama.com/search) prüfen.

Mit der optionalen **RunPod-Environment-Variable `EPUB_MODEL`** lässt sich das Modell beim nächsten Neustart wechseln. Der Bootstrap lädt das neue Modell aufs persistente Volume. Das vorige bleibt dort erhalten. Alternativ im laufenden Pod `ollama pull <modell>` verwenden und in der Anwendung das Modell auswählen. Bei 24 GB VRAM mit QAT/Q4 rechnen, bei 48 GB VRAM kann Q8 passen. `ollama ps` muss nach dem Inferenztest möglichst **100% GPU** anzeigen.

**Vergleichsprobe:** Nicht nur einen Absatz, sondern mindestens drei voneinander unabhängige Passagen:
- Einleitung oder beschreibende Prosa mit der Erzählstimme.
- Ein dialogreiches Kapitel mit Namen, Pronomen, Anreden und Humor.
- Ein sachlich anspruchsvoller Abschnitt mit Fachbegriffen, Zahlen, Zitaten oder Fußnoten.

Gleiche Abschnitte, gleiche Glossare, gleiche Textbereinigung, gleiche Prompt-/Stilregeln. Qualität blind gegenüber Modellnamen vergleichen. Rechenzeit und Geschwindigkeit getrennt protokollieren.

## 2. Prüfkriterien für jede Probe

Pro Kriterium 1 (schlecht) bis 5 (sehr gut):

| Kriterium | Was konkret zu prüfen ist |
|---|---|
| Bedeutungstreue | Keine sinnverändernden Ergänzungen, Auslassungen oder falschen Bezüge |
| Vollständigkeit | Alle Absätze, Dialogzeilen, Negationen, Zahlen und Fußnoten übernommen |
| Deutscher Sprachstil | Natürliches, idiomatisches Deutsch ohne wörtliche Anglizismen |
| Konsistenz | Namen, Anrede, Terminologie, Perspektive und Erzählzeit durchgehend stabil |
| Textcharakter | Humor, Register, Rhythmus und Intention bleiben erkennbar |

**Harte Ausschlusskriterien:** Ein Absatz fehlt; eine Negation wird umgedreht; Sprecher oder Handlungsträger werden verwechselt; wichtige Zahlen sind falsch. Solche Fehler dürfen nicht durch schöne Formulierungen oder eine höhere Gesamtpunktzahl kompensiert werden.

Eine KI kann bei der Bewertung Hinweise liefern, ist aber als Judge potenziell voreingenommen. Eine manuelle Prüfung des Originals an repräsentativen Stellen bleibt notwendig. Für kommerziell zu veröffentlichende Übersetzungen ist menschliches Lektorat weiterhin anzuraten.

## 3. Glossar und Stil vor der ganzen Übersetzung

1. In TranslateBooksWithLLMs unter **Glossaries** ein neues Glossar für das gesamte Buch erstellen.
2. **Auto-extract** auf dem EPUB durchführen. Ergebnis kontrollieren, besonders Personen, Orte, Fachbegriffe, Institutionen, Titel und Geschlechter/Pronomen.
3. Glossar vor Start der Vollübersetzung sichern. Nicht einfach jede automatisch vorgeschlagene Übersetzung übernehmen.
4. Unter **Styles** einen Stil definieren oder aus dem Original ableiten. Für Sachbücher: Klarheit, eindeutige Terminologie, nüchterne Aussagen. Für Romane: Erzählstimme und Dialogregister bewahren, nicht standardmäßig ausschmücken.
5. Bei Englisch → Deutsch *Sie/du* und Geschlecht/Bezüge in Dialogen kontrollieren.
6. **Text Cleanup** bei bereits sauber formatierten EPUBs zunächst ausschalten, um unbeabsichtigte Eingriffe zu vermeiden.

## 4. Chunking, Kontext und Refinement

- `PARALLEL_TRANSLATIONS=1`: Sequenziell, damit die App vorherige übersetzte Abschnitte als Kontext verwenden kann.
- `MAX_TOKENS_PER_CHUNK=800`: konservativer Ausgangspunkt bei strukturierten EPUBs. **Nicht blind größer setzen**. Größere Chunks können zusammenhängender klingen, aber HTML-Tag-Erhaltung und Fehlerkorrektur erschweren. Bei Layoutproblemen 450 testen; bei reinen Prosatexten 1200–1500 vergleichen.
- `EPUB_CONTEXT=8192` auf 48 GB ist ein **vorsichtiger Startwert**, kein Qualitätsoptimum. Wer über 16K/32K nachdenkt, muss mittels `ollama ps` und `nvidia-smi` sicherstellen, dass das Modell nicht auf die CPU ausweicht.
- **Refinement** erst an der Probe mit und ohne aktivieren. Es kann Lesbarkeit verbessern und gleichzeitig die Aussage verschieben. Nur bei nachgewiesenem Vorteil für das gesamte Buch verwenden.

## 5. Nachbearbeitung: EPUB technisch prüfen

Das Tool `audit_epub.py` wird beim Pod-Start nach `/workspace/epub-translator/audit_epub.py` geladen. Es arbeitet **offline** mit Python-Standardbibliothek.

Beispiel im RunPod-Terminal:

```bash
python3 /workspace/epub-translator/audit_epub.py \
  "/workspace/epub-translator/upstream/data/uploads/original.epub" \
  "/workspace/epub-translator/translated_files/translated.epub" \
  --json "/workspace/epub-translator/translated_files/audit.json"
```

**Die zwei EPUB-Pfade sind Beispiele**: tatsächlichen Namen und Upload-Pfad nach der Übersetzung über `find /workspace/epub-translator -iname '*.epub'` bestimmen.

Das Werkzeug prüft:
- Ob beide EPUB-Dateien technisch lesbar sind und XHTML-Spine-Kapitel enthalten.
- Anzahl der Kapitel, HTML-Absätze, Überschriften, Bild- und Linkelemente.
- Verdächtig verkürzte oder aufgeblähte Kapitel.
- Identische lange Textblöcke, die eventuell unübersetzt blieben.
- Fehlende HTML-Anker und veränderte Linkanzahlen.

Ohne `--strict` ist der Exit-Code bei einer nur verdächtigen Abweichung weiterhin 0; bei kritischen Strukturfehlern 1. Mit `--strict` wird auch jede Warnung zum Fehler. **Warnungen sind Prüfanlässe, keine bewiesenen Übersetzungsfehler**. Neue Metadaten, unterschiedliche Textlängen und bewusste redaktionelle Veränderungen können Abweichungen erzeugen.

**Nicht enthalten:** Bedeutungsvergleich, Satz-für-Satz-Abgleich, semantische Vollständigkeit, sicherer Nachweis gegen Halluzinationen, grafische EPUB-Reader-Prüfung. Für maximale Qualität sind Originalvergleich und Sichtprüfung in Calibre/Jellyfin oder einem EPUB-Reader notwendig.

## 6. Freigabekriterien für ein vollständiges Buch

Eine Übersetzung gilt erst dann als brauchbar, wenn (a) die Stichproben nach den oben genannten Kriterien überzeugen, (b) der technische EPUB-Audit keine ungeklärten kritischen Fehler und keine ungeklärten wesentlichen Warnungen liefert, (c) Glossarbegriffe im ganzen Buch konsistent sind und (d) ein EPUB-Reader Inhaltsverzeichnis, Bilder, Fußnoten und Kapitelsprünge korrekt darstellt.

Außerdem gilt: **Ein GPU-Pod und ein lokales Modell liefern Unabhängigkeit und planbare Kosten, aber keine Garantie für die Qualität proprietärer Spitzenmodelle.** Für die besten Ergebnisse ist ein Blindvergleich mit einem hochwertigen Cloud-Modell als Referenz sinnvoll, auch wenn die anschließende Serienübersetzung lokal stattfindet.

## 7. Hörbuchproduktion

Die separate Hörbuchpipeline verwendet einen eigenen Qualitätsprozess mit manueller Sprachprobenfreigabe, nachprüfbarer Segmentvollständigkeit und optionaler ASR-Kontrolle. Details: [Hörbuch-Qualitätsstandard](docs/AUDIOBOOK_QUALITY.md). Die Übersetzungsqualität und die synthetische Sprechqualität sind voneinander unabhängig zu bewerten. **Eine automatische Hörbuch-Freigabe allein durch WER oder eine niedrige ASR-Fehlerquote ist ausgeschlossen.**
