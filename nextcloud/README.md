# Skjalf für Nextcloud 34

Skjalf ist eine Nextcloud External App für private semantische Bildsuche. Die App verwendet CPU ALIGN (`kakaobrain/align-base`), speichert Chroma-Vektoren mit Kosinus-Abstand und hält Ordner-, Datei- und Jobstatus in SQLite. SQLite, Modellcache und Vektordaten liegen unter `APP_PERSISTENT_STORAGE`; Originaldateien bleiben in Nextcloud.

Die App liest Dateien ausschließlich über den pro Anfrage authentifizierten AppAPI-Kontext und Nextcloud WebDAV. Es gibt keine Mounts auf das Nextcloud-Datenverzeichnis. AppAPI-Nutzer wird aus dem verifizierten Request-Kontext gelesen, niemals aus einem API-Parameter. Freigaben, externe Speicher, Papierkorb und nicht lesbare Ordner werden ausgeschlossen. Jede Indexierung ist manuell: Abgleich, neue oder geänderte Datei, Pausieren und Fortsetzen lösen selbst keine Indexierung aus.

## Lokale Entwicklungsumgebung mit Nextcloud 34

Diese Compose-Umgebung ist ein separates Testsystem mit eigener MariaDB, Nextcloud-Datenbank und Skjalf-Datenvolume. Sie verändert keine bestehende Nextcloud-Installation.

1. Docker Compose starten und `nextcloud/` als Arbeitsordner verwenden. `.env.example` als `.env` übernehmen und `APP_SECRET` durch einen langen zufälligen Wert ersetzen. Lass den `AA_VERSION`-Platzhalter zunächst stehen; er wird erst gebraucht, wenn Skjalf gestartet wird.
2. Zuerst nur Datenbank und Nextcloud starten:

   ```sh
   docker compose up -d db nextcloud
   ```

   Richte Nextcloud danach unter `http://localhost:8080` im Browser ein. Der Compose-Stack setzt kein Nextcloud-Admin-Konto; Benutzername und Passwort legst du im Einrichtungsdialog fest.

   Erlaube anschließend auch den internen Docker-Hostnamen `nextcloud`, über den Skjalf die Nextcloud-API aufruft. Prüfe zuerst die vorhandenen Einträge:

   ```sh
   docker compose exec -u www-data nextcloud php occ config:system:get trusted_domains
   ```

   Bei einer frischen Einrichtung mit nur einem Eintrag ist Index `1` frei:

   ```sh
   docker compose exec -u www-data nextcloud php occ config:system:set trusted_domains 1 --value=nextcloud
   ```

   Falls bereits mehrere Einträge vorhanden sind, verwende stattdessen einen freien Index, ohne einen vorhandenen Hostnamen zu ersetzen. Die Browseradresse und der interne Hostname müssen beide erlaubt bleiben. Das Setzen von `NEXTCLOUD_TRUSTED_DOMAINS` im Compose-Environment allein behebt eine bereits im Browser eingerichtete Installation nicht zuverlässig.

3. Prüfe AppAPI in Nextcloud. Nextcloud ab Version 30.0.1 installiert AppAPI standardmäßig automatisch. Wenn `app_api` in der App-Verwaltung vorhanden, aber deaktiviert ist, aktiviere es; installiere AppAPI dort nur, wenn es tatsächlich fehlt. Lies anschließend die installierte AppAPI-Version aus:

   ```sh
   docker compose exec -u www-data nextcloud php occ app:list
   ```

   Trage die angezeigte Version von `app_api` in `.env` als `AA_VERSION` ein. Starte Skjalf nicht, solange dort noch der Beispiel-Platzhalter steht.

4. Baue und starte nun nur den Skjalf-Dienst:

   ```sh
   docker compose up --build -d skjalf
   ```

   Skjalf läuft im selben Docker-Netzwerk `skjalf_default`. Als Nextcloud-Administrator registriere danach die manuelle Daemon-Konfiguration:

   ```sh
   docker compose exec -u www-data nextcloud php occ app_api:daemon:register skjalf-manual "Skjalf local" manual-install http skjalf http://nextcloud/index.php --net=skjalf_default
   ```

   Für diese Compose-Umgebung wird `manual-install` verwendet: Compose startet den App-Container bereits selbst. Der GUI-Button „Verbindung prüfen“ kann trotzdem eine Docker-API-Prüfung wie `http://skjalf/v1.44/_ping` auslösen. Skjalf stellt keine Docker-API bereit und hört auf Port `23000`; dieser Test ist für den manuellen Daemon nicht geeignet. Auch eine Änderung des Daemon-Hosts auf `skjalf:23000` macht den Docker-API-Test nicht gültig. Maßgeblich sind ein erfolgreicher App-Heartbeat und die erfolgreiche Aktivierung mit Menüregistrierung. Unter `app_api:daemon:list` muss für `skjalf-manual` der Typ `manual-install` angezeigt werden. Hintergrund: [AppAPI-Verbindungsprüfung](https://github.com/nextcloud/app_api/blob/main/lib/Controller/DaemonConfigController.php).

5. Vor dem Befehl den vollständigen Platzhalterwert `<APP_SECRET aus .env>` durch den Secret-Wert aus `.env` ersetzen. Der JSON-Text steht in einfachen Anführungszeichen; die Shell ersetzt den Platzhalter daher nicht automatisch. Das bereits laufende ExApp registrieren. Die `routes` unten sind die AppAPI-Zugriffsregeln aus `appinfo/info.xml`; `APP_HOST`, `APP_PORT`, `APP_ID` und `APP_SECRET` müssen exakt zur laufenden Compose-Umgebung passen.

   ```sh
   docker compose exec -u www-data nextcloud php occ app_api:app:register skjalf skjalf-manual --json-info '{"id":"skjalf","name":"Skjalf","daemon_config_name":"skjalf-manual","version":"0.1.1","secret":"<APP_SECRET aus .env>","host":"skjalf","protocol":"http","port":23000,"external-app":{"routes":[{"url":"^/?heartbeat$","verb":"GET","access_level":"PUBLIC"},{"url":"^/?init$","verb":"POST","access_level":"USER"},{"url":"^/?enabled$","verb":"PUT","access_level":"USER"},{"url":"^/?$","verb":"GET","access_level":"USER"},{"url":"^/?api/.*$","verb":"GET,POST,DELETE","access_level":"USER"},{"url":"^/?js/.*$","verb":"GET","access_level":"USER"},{"url":"^/?css/.*$","verb":"GET","access_level":"USER"},{"url":"^/?img/.*$","verb":"GET","access_level":"USER"}]}}' --wait-finish
   docker compose exec -u www-data nextcloud php occ app_api:app:enable skjalf
   ```

6. Öffne Skjalf über den Nextcloud-Menüeintrag. Wähle eigene Ordner aus, gleiche sie ab und starte die Indizierung ausdrücklich. Ein erneuter Abgleich aktualisiert Metadaten und markiert geänderte/neue Dateien als ausstehend; er indexiert sie nicht automatisch. Das Entfernen einer Ordnerauswahl löscht ausschließlich den zugehörigen Skjalf-Index.

### Leere Seite beim Öffnen

AppAPI stellt die eingebettete Oberfläche in `#content` bereit. Wenn ein älteres Bundle noch auf einer leeren Seite mountet, baue die Weboberfläche aus `nextcloud/` neu und ersetze nur den Skjalf-Container:

```sh
npm install --no-audit --no-fund
npm run build
docker compose build skjalf
docker compose up -d --force-recreate skjalf
```

Lade die Nextcloud-Seite anschließend neu. Eine erneute AppAPI-Registrierung ist für diesen Frontend-Neubau nicht erforderlich.

### Wenn das Menü vorhanden ist, die Seite aber leer bleibt

Wenn Browser-Konsole oder Netzwerkanzeige für `js/skjalf-main.js` oder `img/skjalf.svg` eine HTML-404-Antwort aus dem AppAPI-Proxy zeigen, fehlen wahrscheinlich die gespeicherten Proxy-Routen. Baue das App-Image neu und erstelle nur den Skjalf-Container neu:

```sh
docker compose up --build -d --force-recreate --no-deps skjalf
```

Aktualisiere anschließend die registrierten App-Metadaten aus der aktuellen XML-Datei. Kopiere sie an einen separaten Pfad im Nextcloud-Container: Ein bereits bestehender Datei-Bind-Mount kann nach dem Austausch der Hostdatei noch auf die alte Datei zeigen. Die Version `0.1.1` sorgt dafür, dass AppAPI die Metadatenaktualisierung nicht wegen gleicher Version überspringt.

```sh
docker compose cp ./appinfo/info.xml nextcloud:/tmp/skjalf-info-update.xml
docker compose exec -u www-data nextcloud php occ app_api:app:update skjalf --info-xml /tmp/skjalf-info-update.xml --wait-finish
```

Lade danach die Nextcloud-Seite im Browser neu. Diese Folge aktualisiert die vorhandene Registrierung, ohne Skjalf abzumelden oder seine persistenten Daten-Volumes zu löschen.

## Bestehende Nextcloud-Installation

Installiere oder initialisiere Nextcloud nicht neu. Installiere AppAPI in der vorhandenen Instanz und registriere einen `manual-install`-Daemon, der das bereits laufende Skjalf-Containerziel und Nextcloud über ihre jeweiligen internen Netzwerkadressen erreichen kann. Baue das lokale CPU-Image mit `docker build -t skjalf:dev -f nextcloud/Dockerfile nextcloud` und starte es in einem Docker-Netzwerk, das den AppAPI-Dienst erreicht. Beispiel für den Container (Werte für dein Netzwerk und deine URL anpassen):

```sh
docker run -d --name skjalf --restart unless-stopped --network "${NEXTCLOUD_NETWORK}" --network-alias skjalf \
  -e APP_ID=skjalf -e APP_VERSION=0.1.1 -e APP_HOST=skjalf -e APP_PORT=23000 \
  -e APP_SECRET="${APP_SECRET}" -e AA_VERSION="${AA_VERSION}" \
  -e NEXTCLOUD_URL="${NEXTCLOUD_URL}" \
  -e APP_PERSISTENT_STORAGE=/app_data -v skjalf-appdata:/app_data \
  skjalf:dev
```

Setze `NEXTCLOUD_NETWORK`, `APP_SECRET`, `AA_VERSION` und `NEXTCLOUD_URL` in deiner Shell auf die eigenen Werte. `NEXTCLOUD_URL` muss aus dem Container erreichbar sein. Registriere den Daemon so, dass Nextcloud den App-Host `skjalf` erreichen kann. Ersetze im JSON-Befehl außerdem den Secret-Platzhalter durch den Wert aus `$APP_SECRET`; einfache Anführungszeichen verhindern Shell-Ersetzung. Bei einem anders benannten Container muss `APP_HOST` in `docker run`, dem Daemon-Netzwerk und der JSON-Registrierung konsistent geändert werden. `APP_PORT` bleibt in allen drei Stellen `23000`, solange du keinen anderen Port konfigurierst. Die App benötigt nur ihr eigenes persistentes Volume; mounte weder das Nextcloud-Datenverzeichnis noch persönliche Dateien in den Container.

## Ablauf und Grenzen

### HTTP 400 beim Aktivieren

Wenn `/heartbeat` erfolgreich ist, `/enabled?enabled=1` aber mit HTTP 500 scheitert und der Traceback einen HTTP 400 bei `GET /ocs/v1.php/cloud/capabilities` enthält, prüfe zuerst die Nextcloud-`trusted_domains`. Für diesen Compose-Stack muss der interne Hostname `nextcloud` zugelassen sein; siehe Einrichtung oben. Der HTTP-400-Code allein beweist die Ursache nicht: Falls der Fehler danach bestehen bleibt, sind die Nextcloud-Logs bzw. die Antwort auf diesen API-Aufruf zur weiteren Diagnose erforderlich. Nach der Korrektur Skjalf in der Nextcloud-App-Verwaltung deaktivieren und erneut aktivieren, damit die Menüregistrierung wiederholt wird. Ein erneuter Frontend- oder Container-Build ist dafür nicht nötig.

- Beim Öffnen oder Aktualisieren der Oberfläche gleicht Skjalf jeden ausgewählten Ordner vollständig über WebDAV ab. Ein fehlgeschlagener Scan wird nicht als Löschung interpretiert.
- Die Indizierung verwendet einen Worker und verarbeitet pro Bild den Download, die ALIGN-Einbettung und den ETag-Abgleich. Nach einem App-Neustart werden laufende Jobs pausiert.
- Die Suche liefert bis zu zehn Treffer und prüft vor jeder Anzeige erneut Dateiberechtigung, Ordnerzugehörigkeit und ETag. Vorschau und Dateilink werden vom angemeldeten Nextcloud-Browser geladen.
- Änderungen und neue Dateien werden erst nach einem ausdrücklichen Start indexiert. Fehlerhafte oder nicht unterstützte Bilder werden pro Datei vermerkt; ein Job läuft für weitere Bilder weiter.
- Abhängigkeiten sind in `requirements.txt` und `package.json` gepinnt beziehungsweise begrenzt. Es wurde absichtlich kein Lockfile durch eine Paketinstallation erstellt. Die konkrete Abhängigkeitsauflösung und der AppAPI/Nextcloud-34-Laufzeitmix sind in dieser Arbeitsumgebung nicht verifiziert.

## Prüfung

Unit-Tests liegen unter `tests/`. Docker Compose, Containerstart, AppAPI-Registrierung, Nextcloud-WebDAV, Browser-UI und ALIGN-Modelldownload müssen nach der Installation anhand von [ACCEPTANCE.md](ACCEPTANCE.md) manuell geprüft werden. In dieser Arbeitsumgebung wurden auf ausdrückliche Anweisung keine Abhängigkeiten installiert, Tests oder Builds ausgeführt und keine Nextcloud-Instanz gestartet.
