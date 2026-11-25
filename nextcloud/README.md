# Skjalf for Nextcloud 34

Skjalf is a Nextcloud External App for private semantic image search. The app uses ALIGN on the CPU (`kakaobrain/align-base`), stores Chroma vectors with cosine distance and keeps folder, file and job state in SQLite. SQLite, the model cache and the vector data live under `APP_PERSISTENT_STORAGE`; original files stay in Nextcloud.

The app reads files only through the per-request authenticated AppAPI context and Nextcloud WebDAV. There are no mounts of the Nextcloud data directory. The AppAPI user is read from the verified request context, never from an API parameter. Shares, external storage, the trash bin and unreadable folders are excluded. All indexing is manual: syncing, new or changed files, pausing and resuming never start indexing on their own.

## Local development setup with Nextcloud 34

This Compose setup is a separate test system with its own MariaDB, Nextcloud database and Skjalf data volume. It does not touch any existing Nextcloud installation.

1. Use `nextcloud/` as your working directory for Docker Compose. Copy `.env.example` to `.env` and replace `APP_SECRET` with a long random value. Leave the `AA_VERSION` placeholder as it is for now; it is only needed once Skjalf starts.
2. Start only the database and Nextcloud first:

   ```sh
   docker compose up -d db nextcloud
   ```

   Then set up Nextcloud in your browser at `http://localhost:8080`. The Compose stack does not create a Nextcloud admin account; you choose the username and password in the setup dialog.

   Next, also allow the internal Docker hostname `nextcloud`, which Skjalf uses to call the Nextcloud API. Check the existing entries first:

   ```sh
   docker compose exec -u www-data nextcloud php occ config:system:get trusted_domains
   ```

   On a fresh setup with only one entry, index `1` is free:

   ```sh
   docker compose exec -u www-data nextcloud php occ config:system:set trusted_domains 1 --value=nextcloud
   ```

   If there are already several entries, use a free index instead, without replacing an existing hostname. Both the browser address and the internal hostname must stay allowed. Setting `NEXTCLOUD_TRUSTED_DOMAINS` in the Compose environment alone does not reliably fix an installation that was already set up in the browser.

3. Check AppAPI in Nextcloud. Nextcloud 30.0.1 and later installs AppAPI automatically by default. If `app_api` is present in the app management but disabled, enable it; only install AppAPI there if it is actually missing. Then read the installed AppAPI version:

   ```sh
   docker compose exec -u www-data nextcloud php occ app:list
   ```

   Enter the listed version of `app_api` in `.env` as `AA_VERSION`. Don't start Skjalf while the example placeholder is still there.

4. Now build and start only the Skjalf service:

   ```sh
   docker compose up --build -d skjalf
   ```

   Skjalf runs in the same Docker network, `skjalf_default`. As a Nextcloud administrator, then register the manual daemon configuration:

   ```sh
   docker compose exec -u www-data nextcloud php occ app_api:daemon:register skjalf-manual "Skjalf local" manual-install http skjalf http://nextcloud/index.php --net=skjalf_default
   ```

   This Compose setup uses `manual-install` because Compose already starts the app container itself. The "Check connection" button in the GUI may still trigger a Docker API check such as `http://skjalf/v1.44/_ping`. Skjalf does not provide a Docker API and listens on port `23000`, so this check does not apply to the manual daemon. Changing the daemon host to `skjalf:23000` does not make the Docker API check valid either. What counts is a successful app heartbeat and a successful enable step with menu registration. `app_api:daemon:list` must show the type `manual-install` for `skjalf-manual`. Background: [AppAPI connection check](https://github.com/nextcloud/app_api/blob/main/lib/Controller/DaemonConfigController.php).

5. Register the already running ExApp. Run the command from the `nextcloud/` folder: it reads `APP_SECRET` from `.env` and inserts the value into the JSON text. The JSON text is in single quotes; only the secret part briefly leaves them. The `routes` below are the AppAPI access rules from `appinfo/info.xml`; `APP_HOST`, `APP_PORT`, `APP_ID` and `APP_SECRET` must exactly match the running Compose setup.

   ```sh
   docker compose exec -u www-data nextcloud php occ app_api:app:register skjalf skjalf-manual --json-info '{"id":"skjalf","name":"Skjalf","daemon_config_name":"skjalf-manual","version":"0.1.1","secret":"'"$(. ./.env && printf %s "$APP_SECRET")"'","host":"skjalf","protocol":"http","port":23000,"external-app":{"routes":[{"url":"^/?heartbeat$","verb":"GET","access_level":"PUBLIC"},{"url":"^/?init$","verb":"POST","access_level":"USER"},{"url":"^/?enabled$","verb":"PUT","access_level":"USER"},{"url":"^/?$","verb":"GET","access_level":"USER"},{"url":"^/?api/.*$","verb":"GET,POST,DELETE","access_level":"USER"},{"url":"^/?js/.*$","verb":"GET","access_level":"USER"},{"url":"^/?css/.*$","verb":"GET","access_level":"USER"},{"url":"^/?img/.*$","verb":"GET","access_level":"USER"}]}}' --wait-finish
   docker compose exec -u www-data nextcloud php occ app_api:app:enable skjalf
   ```

6. Open Skjalf from the Nextcloud menu entry. Choose your own folders, sync them and start indexing explicitly. Syncing again updates the metadata and marks changed or new files as pending; it does not index them automatically. Removing a folder selection deletes only the matching Skjalf index.

## Updating an existing Compose installation

Run the update from the repository root. Check the checkout first. Only if `git status --short` shows no changes, fetch the new version with a fast-forward:

```sh
git status --short
git pull --ff-only
cd nextcloud
docker compose up -d --build --force-recreate --no-deps skjalf
```

The Dockerfile installs the frontend dependencies and builds the web interface automatically inside the image. You don't need to run `npm install` or `npm run build` in the repository for this. The command only rebuilds and replaces the Skjalf container; the existing AppAPI registration and the persistent volumes are kept. For code-only changes you don't need to disable and re-enable the app. Afterwards, fully reload the Nextcloud page in your browser (hard reload).

If `appinfo/info.xml` or the routes registered with AppAPI have changed, also update the metadata of the existing registration. If AppAPI would skip the change because the version is the same, bump the patch version consistently in `appinfo/info.xml`, `package.json`, `APP_VERSION` in the Dockerfile and `APP_VERSION` in `docker-compose.yml`; then rebuild Skjalf as described above. Next, copy the XML to a separate path in the Nextcloud container, so that a possibly stale file bind mount isn't used, and call `app_api:app:update`:

```sh
docker compose cp ./appinfo/info.xml nextcloud:/tmp/skjalf-info-update.xml
docker compose exec -u www-data nextcloud php occ app_api:app:update skjalf --info-xml /tmp/skjalf-info-update.xml --wait-finish
```

This updates the existing registration; running `app_api:app:register` again or deleting volumes is not intended for this.

## Existing Nextcloud installation

Don't reinstall or reinitialize Nextcloud. Install AppAPI in the existing instance and register a `manual-install` daemon that can reach the already running Skjalf container and Nextcloud through their respective internal network addresses. Build the local CPU image with `docker build -t skjalf:dev -f nextcloud/Dockerfile nextcloud` and start it in a Docker network that can reach the AppAPI service. Example for the container (adjust the values for your network and URL):

```sh
docker run -d --name skjalf --restart unless-stopped --network "${NEXTCLOUD_NETWORK}" --network-alias skjalf \
  -e APP_ID=skjalf -e APP_VERSION=0.1.1 -e APP_HOST=skjalf -e APP_PORT=23000 \
  -e APP_SECRET="${APP_SECRET}" -e AA_VERSION="${AA_VERSION}" \
  -e NEXTCLOUD_URL="${NEXTCLOUD_URL}" \
  -e APP_PERSISTENT_STORAGE=/app_data -v skjalf-appdata:/app_data \
  skjalf:dev
```

Set `NEXTCLOUD_NETWORK`, `APP_SECRET`, `AA_VERSION` and `NEXTCLOUD_URL` in your shell to your own values. `NEXTCLOUD_URL` must be reachable from the container. Register the daemon so that Nextcloud can reach the app host `skjalf`. In the JSON command from step 5, insert the secret from `$APP_SECRET` (if the shell variable is set, `"secret":"'"$APP_SECRET"'"` is enough). If you name the container differently, change `APP_HOST` consistently in `docker run`, the daemon network and the JSON registration. `APP_PORT` stays `23000` in all three places unless you configure a different port. The app only needs its own persistent volume; don't mount the Nextcloud data directory or personal files into the container.

## How it works and limits

- When the interface is opened or refreshed, Skjalf fully syncs every selected folder over WebDAV. A failed scan is never treated as a deletion.
- Indexing uses a single worker and, for each image, handles the download, the ALIGN embedding and the ETag check. After an app restart, running jobs are paused.
- The number of results can be set per search (default 10, at most 100); the server validates the limit. Before showing a result, Skjalf checks file permission, folder membership and ETag again. Previews and file links are loaded by the signed-in Nextcloud browser session.
- Changes and new files are only indexed after an explicit start. Broken or unsupported images are recorded per file; the job carries on with the remaining images.
- Dependencies are pinned or bounded in `requirements.txt` and `package.json`; there is intentionally no npm lockfile.
- Only Nextcloud 34 is supported (see `appinfo/info.xml`).

## Troubleshooting

### Blank page when opening the app

After a code change, rebuild Skjalf as described in "Updating an existing Compose installation". The Dockerfile also builds the frontend bundle; a separate npm install is not required.

If the browser console or network panel shows an HTML 404 response from the AppAPI proxy for `js/skjalf-main.js` or `img/skjalf.svg`, stored proxy routes are probably missing. Update the AppAPI metadata as described above. Recreating the container alone does not update existing proxy routes.

### HTTP 400 when enabling the app

If `/heartbeat` succeeds but `/enabled?enabled=1` fails with HTTP 500 and the traceback contains an HTTP 400 for `GET /ocs/v1.php/cloud/capabilities`, check the Nextcloud `trusted_domains` first. For this Compose stack, the internal hostname `nextcloud` must be allowed; see the setup above. The HTTP 400 code alone does not prove the cause: if the error persists afterwards, you need the Nextcloud logs or the response to that API call to diagnose it further. After fixing it, disable and re-enable Skjalf in the Nextcloud app management so the menu registration runs again. A new frontend or container build is not needed for this.

## Testing

The unit tests in `tests/` run offline with stand-ins for Nextcloud, the ALIGN model and Chroma. From the `nextcloud/` folder:

```sh
pip install "nc-py-api>=0.30,<0.31" "fastapi>=0.115,<1" "pillow>=10,<13" numpy
python -m unittest tests/test_service.py
```

You can build the frontend locally with `npm install && npm run build`; the output in `ex_app/js/` is not committed. Docker Compose, container start, AppAPI registration, Nextcloud WebDAV, the browser UI and the ALIGN model download are not covered by the unit tests and need to be checked manually after installation.
