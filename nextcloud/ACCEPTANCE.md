# Abnahme auf Nextcloud 34

Die folgenden Prüfungen sind für eine spätere Freigabe vorgesehen. Sie wurden bei der Erstellung nicht ausgeführt. Auf Wunsch des Nutzers wurden keine Abhängigkeiten installiert und keine Tests, Builds oder Container gestartet.

## Einrichtung und erster Lauf

- In einer separaten Nextcloud-34-Testinstallation die App nach der README registrieren. Der Menüeintrag „Skjalf“ erscheint nur bei aktivierter App.
- Die Modellinitialisierung abschließen. Ein fehlgeschlagener Download muss sichtbar sein und darf keine erfolgreiche Bereitschaft vortäuschen.
- Einen eigenen Ordner mit Unterordnern und wenigen Bildern registrieren. Die Registrierung allein erzeugt keine Embeddings.
- Die Indexierung manuell starten. Fortschritt, ausstehende Bilder und Fehler sind nachvollziehbar. Eine defekte Bilddatei verhindert die Verarbeitung weiterer Bilder nicht.
- Nach abgeschlossener Einrichtung die Internetverbindung unterbrechen: vorhandene Modellgewichte müssen für Indexierung und Suche ausreichen.

## Änderungen und Wiederaufnahme

- Neue Bilder hinzufügen und vorhandene ändern. „Aktualisieren“ zeigt sie als ausstehend; die Verarbeitung beginnt erst nach manuellem Start.
- Einen weiteren Lauf starten: unveränderte Bilder werden übersprungen, geänderte Bilder neu verarbeitet.
- Einen Lauf pausieren. Nach der aktuell laufenden Datei werden keine weiteren Bilder verarbeitet. Fortsetzen verarbeitet den Rest.
- Den Container während eines Laufs neu starten. Der Lauf bleibt pausiert; seine Registrierung und bereits erfolgreich verarbeiteten Bilder bleiben erhalten.
- Eine Datei während der Verarbeitung ändern. Ein Embedding darf nicht mit dem ETag einer anderen Dateiversion als aktuell markiert werden.
- Bilder umbenennen, verschieben und löschen. Nach dem Abgleich existieren keine veralteten Treffer; Bewegungen innerhalb eines registrierten Ordners aktualisieren den Öffnungslink.
- Eine Registrierung während eines Laufs entfernen. Originaldateien bleiben erhalten; ein noch laufender Worker darf den entfernten Index nicht wiederherstellen.

## Suche und Zugriffsgrenzen

- Eine kleine Referenzsammlung mit passenden englischen Beschreibungen durchsuchen und die Rangfolge mit der Desktop-ALIGN-Verarbeitung vergleichen.
- Suchtreffer stammen nur aus dem ausgewählten registrierten Ordner einschließlich seiner Unterordner. Vorschau, Dateiname und Öffnungslink passen zur Datei.
- Vor der Suche gelöschte oder geänderte Dateien werden nicht als aktuelle Treffer angezeigt, auch wenn zuvor kein manueller Abgleich erfolgte.
- Mit einem zweiten Konto prüfen: Ordner, Status, Embeddings, Suchtreffer und Vorschauen des ersten Kontos dürfen nicht erreichbar sein. Manipulierte Nutzer- oder Registrierungs-IDs ändern daran nichts.
- Ohne authentifizierte Nextcloud-Sitzung sind Nutzerschnittstellen nicht zugänglich. Ein fehlendes oder ungültiges AppAPI-Signaturheader wird abgewiesen; der öffentliche Heartbeat enthält keine Nutzerdaten.
- Geteilte Ordner, externe Speicher und Ende-zu-Ende-verschlüsselte Ordner werden ausgeschlossen, auch wenn sie unterhalb eines ausgewählten Ordners liegen.
- Überlappende Ordnerregistrierungen werden verständlich abgewiesen.

## Dokumentation der späteren Prüfung

Für jede tatsächlich durchgeführte Prüfung Nextcloud-Version, AppAPI-Version, Container-Image, CPU, RAM, Bildanzahl und Ergebnis dokumentieren. Laufzeit und Speicherbedarf mit einer repräsentativen Sammlung messen; eine Sammlung bis 10.000 Bilder ist das Ziel, keine bereits gemessene Leistungszusage.
