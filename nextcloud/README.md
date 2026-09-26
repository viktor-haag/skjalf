# Skjalf für Nextcloud 34

Skjalf ist eine Nextcloud External App für private semantische Bildsuche. Die App verwendet CPU ALIGN (`kakaobrain/align-base`), speichert Chroma-Vektoren mit Kosinus-Abstand und hält Ordner-, Datei- und Jobstatus in SQLite. SQLite, Modellcache und Vektordaten liegen unter `APP_PERSISTENT_STORAGE`; Originaldateien bleiben in Nextcloud.

Die App liest Dateien ausschließlich über den pro Anfrage authentifizierten AppAPI-Kontext und Nextcloud WebDAV. Es gibt keine Mounts auf das Nextcloud-Datenverzeichnis. AppAPI-Nutzer wird aus dem verifizierten Request-Kontext gelesen, niemals aus einem API-Parameter. Freigaben, externe Speicher, Papierkorb und nicht lesbare Ordner werden ausgeschlossen. Jede Indexierung ist manuell: Abgleich, neue oder geänderte Datei, Pausieren und Fortsetzen lösen selbst keine Indexierung aus.

## Lokale Entwicklungsumgebung mit Nextcloud 34

Diese Compose-Umgebung ist ein separates Testsystem mit eigener MariaDB, Nextcloud-Datenbank und Skjalf-Datenvolume. Sie verändert keine bestehende Nextcloud-Installation.

1. Docker Compose starten und `nextcloud/` als Arbeitsordner verwenden. `.env.example` als `.env` übernehmen; `APP_SECRET` durch einen langen zufälligen Wert ersetzen und `AA_VERSION` auf die installierte AppAPI-Version setzen. Beide Werte müssen mit der unten beschriebenen Registrierung übereinstimmen.
2. `docker compose up --build -d` starten und Nextcloud unter `http://localhost:8080` einmalig einrichten.
3. AppAPI über die Nextcloud-Appverwaltung installieren und aktivieren. Die AppAPI-Version muss mit `AA_VERSION` in `.env` übereinstimmen.
4. Der Compose-Dienst `skjalf` ist bereits gebaut und läuft im selben Docker-Netzwerk `skjalf_default`. Als Nextcloud-Administrator die manuelle Daemon-Konfiguration registrieren:

   ```sh
   docker compose exec -u www-data nextcloud php occ app_api:daemon:register skjalf-manual "Skjalf local" manual-install http skjalf http://nextcloud/index.php --net=skjalf_default
   ```

5. Vor dem Befehl den vollständigen Platzhalterwert `<APP_SECRET aus .env>` durch den Secret-Wert aus `.env` ersetzen. Der JSON-Text steht in einfachen Anführungszeichen; die Shell ersetzt den Platzhalter daher nicht automatisch. Das bereits laufende ExApp registrieren. Die `routes` unten sind die AppAPI-Zugriffsregeln aus `appinfo/info.xml`; `APP_HOST`, `APP_PORT`, `APP_ID` und `APP_SECRET` müssen exakt zur laufenden Compose-Umgebung passen.

   ```sh
   docker compose exec -u www-data nextcloud php occ app_api:app:register skjalf skjalf-manual --json-info '{"id":"skjalf","name":"Skjalf","daemon_config_name":"skjalf-manual","version":"0.1.0","secret":"<APP_SECRET aus .env>","host":"skjalf","protocol":"http","port":23000,"routes":[{"url":"^/?heartbeat$","verb":"GET","access_level":"PUBLIC"},{"url":"^/?init$","verb":"POST","access_level":"USER"},{"url":"^/?enabled$","verb":"PUT","access_level":"USER"},{"url":"^/?$","verb":"GET","access_level":"USER"},{"url":"^/?api/.*$","verb":"GET,POST,DELETE","access_level":"USER"},{"url":"^/?js/.*$","verb":"GET","access_level":"USER"},{"url":"^/?css/.*$","verb":"GET","access_level":"USER"},{"url":"^/?img/.*$","verb":"GET","access_level":"USER"}]}' --wait-finish
   docker compose exec -u www-data nextcloud php occ app_api:app:enable skjalf
   ```

6. Öffne Skjalf über den Nextcloud-Menüeintrag. Wähle eigene Ordner aus, gleiche sie ab und starte die Indizierung ausdrücklich. Ein erneuter Abgleich aktualisiert Metadaten und markiert geänderte/neue Dateien als ausstehend; er indexiert sie nicht automatisch. Das Entfernen einer Ordnerauswahl löscht ausschließlich den zugehörigen Skjalf-Index.

## Bestehende Nextcloud-Installation

Installiere oder initialisiere Nextcloud nicht neu. Installiere AppAPI in der vorhandenen Instanz und registriere einen `manual-install`-Daemon, der das bereits laufende Skjalf-Containerziel und Nextcloud über ihre jeweiligen internen Netzwerkadressen erreichen kann. Baue das lokale CPU-Image mit `docker build -t skjalf:dev -f nextcloud/Dockerfile nextcloud` und starte es in einem Docker-Netzwerk, das den AppAPI-Dienst erreicht. Beispiel für den Container (Werte für dein Netzwerk und deine URL anpassen):

```sh
docker run -d --name skjalf --restart unless-stopped --network "${NEXTCLOUD_NETWORK}" --network-alias skjalf \
  -e APP_ID=skjalf -e APP_VERSION=0.1.0 -e APP_HOST=skjalf -e APP_PORT=23000 \
  -e APP_SECRET="${APP_SECRET}" -e AA_VERSION="${AA_VERSION}" \
  -e NEXTCLOUD_URL="${NEXTCLOUD_URL}" \
  -e APP_PERSISTENT_STORAGE=/app_data -v skjalf-appdata:/app_data \
  skjalf:dev
```

Setze `NEXTCLOUD_NETWORK`, `APP_SECRET`, `AA_VERSION` und `NEXTCLOUD_URL` in deiner Shell auf die eigenen Werte. `NEXTCLOUD_URL` muss aus dem Container erreichbar sein. Registriere den Daemon so, dass Nextcloud den App-Host `skjalf` erreichen kann. Ersetze im JSON-Befehl außerdem den Secret-Platzhalter durch den Wert aus `$APP_SECRET`; einfache Anführungszeichen verhindern Shell-Ersetzung. Bei einem anders benannten Container muss `APP_HOST` in `docker run`, dem Daemon-Netzwerk und der JSON-Registrierung konsistent geändert werden. `APP_PORT` bleibt in allen drei Stellen `23000`, solange du keinen anderen Port konfigurierst. Die App benötigt nur ihr eigenes persistentes Volume; mounte weder das Nextcloud-Datenverzeichnis noch persönliche Dateien in den Container.

## Ablauf und Grenzen

- Beim Öffnen oder Aktualisieren der Oberfläche gleicht Skjalf jeden ausgewählten Ordner vollständig über WebDAV ab. Ein fehlgeschlagener Scan wird nicht als Löschung interpretiert.
- Die Indizierung verwendet einen Worker und verarbeitet pro Bild den Download, die ALIGN-Einbettung und den ETag-Abgleich. Nach einem App-Neustart werden laufende Jobs pausiert.
- Die Suche liefert bis zu zehn Treffer und prüft vor jeder Anzeige erneut Dateiberechtigung, Ordnerzugehörigkeit und ETag. Vorschau und Dateilink werden vom angemeldeten Nextcloud-Browser geladen.
- Änderungen und neue Dateien werden erst nach einem ausdrücklichen Start indexiert. Fehlerhafte oder nicht unterstützte Bilder werden pro Datei vermerkt; ein Job läuft für weitere Bilder weiter.
- Abhängigkeiten sind in `requirements.txt` und `package.json` gepinnt beziehungsweise begrenzt. Es wurde absichtlich kein Lockfile durch eine Paketinstallation erstellt. Die konkrete Abhängigkeitsauflösung und der AppAPI/Nextcloud-34-Laufzeitmix sind in dieser Arbeitsumgebung nicht verifiziert.

## Prüfung

Unit-Tests liegen unter `tests/`. Docker Compose, Containerstart, AppAPI-Registrierung, Nextcloud-WebDAV, Browser-UI und ALIGN-Modelldownload müssen nach der Installation anhand von [ACCEPTANCE.md](ACCEPTANCE.md) manuell geprüft werden. In dieser Arbeitsumgebung wurden auf ausdrückliche Anweisung keine Abhängigkeiten installiert, Tests oder Builds ausgeführt und keine Nextcloud-Instanz gestartet.
