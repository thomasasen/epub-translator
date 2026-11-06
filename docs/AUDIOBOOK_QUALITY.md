# Hörbuch-Qualitätsstandard und Red-Team

Ziel ist eine natürliche, ruhige deutsche Fachbuchstimme, ohne inhaltliche Abstriche oder erfundene Übergänge. **Priorität: Texttreue vor Effekt und Geschwindigkeit.**

## Sprachproben

Bei ausreichend Textmaterial wählt die Pipeline drei Textgruppen: sachliche Prosa, Passagen mit Fachterminologie sowie Passagen mit Zahlen/Abkürzungen. Insgesamt etwa 5–10 Minuten als Zielwert, nicht als garantiere Laufzeit. Bei sehr kurzen Büchern kann es weniger sein.

Menschliche Bewertung je 1–5, Gewichtung:

| Merkmal | Gewicht |
| --- | ---: |
| Natürlichkeit/Sprecherqualität | 25 % |
| Fachbegriffe/Aussprache | 25 % |
| Texttreue/Vollständigkeit | 25 % |
| Sprachrhythmus/Pausen | 15 % |
| Stimmenkontinuität | 10 % |

**Harte Fehler:** ausgelassene Negationen, falsche Beträge, Zahlendreher, zusätzliche Aussagen, doppelte Sätze, kaputte Kapitelmarken. Diese Fehler können nicht durch subjektiv schönen Klang ausgeglichen werden.

## Automatische Prüfung

`quality.json` dokumentiert für jedes Sollsegment Vorhandensein, Laufzeit, Sample-Rate, sampled Clipping, RMS und Stilleanteil; Warnungen und bewusst nicht vertonte EPUB-Bestandteile. Optionales `faster-whisper` vergleicht die ASR-Erkennung mit dem gespeicherten Sprechtext. Eine ASR-Abweichung kann durch das Erkennungsmodell verursacht sein; WER/Ähnlichkeit sind **kein Beweis** der Fehlerfreiheit und **keine automatische Audio-Freigabe**.

Segment-Fingerprints beinhalten Sprechtext, Stimmen-/Modellparameter und Ausspracheglossar. Bei Änderung werden alte WAVs nicht wiederverwendet; keine willkürliche Löschung des alten Cache. Statusmeldungen werden atomar gespeichert. Teilweise generierte temporäre WAVs sind von gültigen Ergebnissen getrennt.

## Mastering

FFmpeg erzeugt PCM-Kapitel, einzelne MP3-Dateien (`128 kbit/s`) und ein AAC-M4B (`128 kbit/s`) mit Kapiteln/Metadaten, optional Cover. Filter: `atempo` für kontrolliertes Tempo und `loudnorm=I=-19:TP=-2:LRA=11` als **Ausgangswert**. Ohne echte Hörprobe sind die Parameter kein belegter Studiostandard für jedes Buch. Starke Kompression und Blind-Crossfades werden vermieden. Segmentübergänge und Klicks bei direkt aneinandergelegten WAVs sind im echten Hörtest zu kontrollieren.

## Red-Team-Matrix

| Risiko | Maßnahme | Restrestrisiko |
| --- | --- | --- |
| Fachbegriff falsch | JSON-Glossar pro Buch | Schreibumschreibungen können andere Wörter beeinflussen; Probe anhören |
| Auslassung/Dopplung | Segment-Sollbestand, optional ASR | ASR ist fehlbar, Langformtest offen |
| Zahlen verändert | Source-Text nicht semantisch umschreiben | Modell kann Zahl trotzdem falsch sprechen |
| Stimme wechselt | Fester Sprecher, Modell-ID, Instruktion/Seed | Seed allein garantiert keine konsistente Stimme |
| Schnittkante | FFT-/Sample-Prüfung, kein aggressiver Crossfade | Manuelle Hörprüfung notwendig |
| Kapitelreihenfolge | OPF-Spine | Sonderfälle EPUB-Navigation nicht vollständig getestet |
| Pod-Abbruch | Atomare Manifestdatei, Hash-Cache | Beim Stromausfall ggf. letzte WAV ungültig |
| GPU-OOM | freier VRAM, kein stiller CPU-Fallback | simultane Übersetzungsstarts nicht technisch blockiert |
| M4B beschädigt | FFprobe + synthetischer Exporttest | Fremdplayer-Tests fehlen |
| Übersetzungsregression | kein Patch am AGPL-Upstream, Nginx-Isolation | End-to-End-Regression am Pod fehlt |
| URL ohne Passwort | Portminimierung, Pfadprüfung, Uploadlimits | Jeder mit URL hat vollen Zugriff |

## Verifikationsstatus

Lokale Unit-/Integrationstests werden in GitHub Actions ausgeführt; die konkreten Workflow-Ergebnisse sind vor Rollout zu prüfen. **Kein GPU-/Langform-Hörtest und kein echter RunPod-E2E-Test liegt in diesem Branch als Messergebnis vor.** Ein Test mit zwei echten TTS-Engines wird erst möglich, wenn ein zweiter realer Adapter eingebunden und beide Kandidaten auf identischen Proben aufgenommen wurden.
