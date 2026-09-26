"""Offline service tests. These are authored for CI but were not executed here."""
from __future__ import annotations

import asyncio
import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from nc_py_api.files import FsNode
from PIL import Image

from ex_app.lib.nextcloud_files import (
    _is_regular_personal_node,
    resolve_indexed_file,
    scan_root,
)
from ex_app.lib.service import AppDisabled, SkjalfService


class FakeNode:
    def __init__(self, file_id: str, path: str, etag: str):
        self.file_id = file_id
        self.user_path = path
        self.etag = etag


class FakeFiles:
    def __init__(self):
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        image = Image.new("RGB", (2, 2), (180, 40, 70))
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        self.png = buffer.getvalue()

    async def download2stream(self, _node, destination):
        self.started.set()
        await self.release.wait()
        destination.write(self.png)


class FakeNC:
    def __init__(self, user="alice"):
        self._user = user
        self.files = FakeFiles()

    @property
    def user(self):
        async def resolve_user():
            return self._user
        return resolve_user()


class FakeCollection:
    def __init__(self):
        self.upserts = []
        self.deletes = []

    def upsert(self, **kwargs):
        self.upserts.append(kwargs)

    def delete(self, **kwargs):
        self.deletes.append(kwargs)


class FakeChromaClient:
    def __init__(self, collection_name):
        self.names = [collection_name]
        self.deleted = []

    def list_collections(self):
        return list(self.names)

    def delete_collection(self, name):
        self.deleted.append(name)
        self.names.remove(name)


class FakeVector:
    def tolist(self):
        return [0.1, 0.2, 0.3]


class FakeEncoder:
    def encode_image(self, _image):
        return FakeVector()


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.service = SkjalfService(Path(self.temp.name) / "state", Path(self.temp.name) / "models")
        self.user = "alice"
        self.root_id = "a" * 32
        self.file_id = "12345"
        with self.service.lock, self.service.db:
            self.service.db.execute(
                "INSERT INTO roots(user_id,root_id,file_id,path,etag,available) VALUES(?,?,?,?,?,1)",
                (self.user, self.root_id, "root-file", "/Photos", "root-etag"),
            )

    def tearDown(self):
        self.service.close()
        self.temp.cleanup()

    def test_verified_nextcloud_context_is_the_only_identity_source(self):
        nc = FakeNC("alice")
        self.assertEqual(asyncio.run(self.service.user_id(nc)), "alice")
        with self.assertRaises(AppDisabled):
            asyncio.run(self.service.start(nc, self.root_id))

    def test_sdk_fsnode_filters_use_info_trash_and_keep_permission_guards(self):
        def node(*, permissions="G", **extra):
            return FsNode(
                "files/alice/Photos/photo.jpg",
                file_id="photo-id",
                etag='"etag-1"',
                mimetype="image/jpeg",
                permissions=permissions,
                **extra,
            )

        self.assertTrue(_is_regular_personal_node(node()))
        self.assertFalse(_is_regular_personal_node(node(trashbin_filename="photo.jpg")))
        shared = node(permissions="SG")
        mounted = node(permissions="MG")
        unreadable = node(permissions="R")
        version = node()
        version.info.is_version = True
        self.assertFalse(_is_regular_personal_node(shared))
        self.assertFalse(_is_regular_personal_node(mounted))
        self.assertFalse(_is_regular_personal_node(unreadable))
        self.assertFalse(_is_regular_personal_node(version))

    def test_scan_root_returns_sdk_nodes_by_file_id_and_file_resolver_uses_id_first(self):
        root_node = FsNode(
            "files/alice/Photos/", file_id="root-id", etag='"root-etag"', permissions="G"
        )
        image_node = FsNode(
            "files/alice/Photos/photo.jpg",
            file_id="photo-id",
            etag='"photo-etag"',
            mimetype="image/jpeg",
            permissions="G",
        )

        class DavFiles:
            async def by_path(self, path):
                self.last_path = path
                return root_node

            async def by_id(self, file_id):
                self.last_file_id = file_id
                return image_node

            async def listdir(self, path, depth=1):
                self.last_listing = (path, depth)
                return [image_node] if path == "Photos" else []

        files = DavFiles()
        nc = SimpleNamespace(files=files)

        async def run():
            scanned_root, discovered = await scan_root(nc, root_node)
            resolved = await resolve_indexed_file(nc, "photo-id", "Photos")
            return scanned_root, discovered, resolved

        scanned_root, discovered, resolved = asyncio.run(run())
        self.assertIs(scanned_root, root_node)
        self.assertIs(discovered["photo-id"], image_node)
        self.assertIs(resolved, image_node)
        self.assertEqual(files.last_file_id, "photo-id")

    def test_indexed_count_aliases_work_for_roots_and_root_status(self):
        self.assertEqual(self.service.roots(self.user)[0]["indexed"], 0)
        self.assertEqual(self.service.root_status(self.user, self.root_id)["indexed"], 0)

        with self.service.lock, self.service.db:
            self.service.db.execute(
                "INSERT INTO files(user_id,root_id,file_id,path,etag,status) VALUES(?,?,?,?,?,'indexed')",
                (self.user, self.root_id, self.file_id, "/Photos/a.jpg", "etag-1"),
            )

        self.assertEqual(self.service.roots(self.user)[0]["indexed"], 1)
        self.assertEqual(self.service.root_status(self.user, self.root_id)["indexed"], 1)

    def test_reconcile_failure_keeps_existing_rows(self):
        node = FakeNode("root-file", "/Photos", "root-etag")
        with self.service.lock, self.service.db:
            self.service.db.execute(
                "INSERT INTO files(user_id,root_id,file_id,path,etag,status) VALUES(?,?,?,?,?,'indexed')",
                (self.user, self.root_id, self.file_id, "/Photos/a.jpg", "etag-1"),
            )

        async def run():
            with patch("ex_app.lib.service.resolve_personal_folder", new=AsyncMock(return_value=node)), \
                 patch("ex_app.lib.service.scan_root", new=AsyncMock(side_effect=OSError("WebDAV unavailable"))):
                with self.assertRaises(OSError):
                    await self.service.reconcile_root(FakeNC(), self.root_id)

        asyncio.run(run())
        with self.service.lock:
            record = self.service.db.execute(
                "SELECT status,etag FROM files WHERE user_id=? AND root_id=? AND file_id=?",
                (self.user, self.root_id, self.file_id),
            ).fetchone()
        self.assertEqual((record["status"], record["etag"]), ("indexed", "etag-1"))

    def test_interrupted_running_jobs_are_paused_on_restart(self):
        with self.service.lock, self.service.db:
            self.service.db.execute(
                "INSERT INTO jobs(user_id,root_id,status,total,processed,failed,pause_requested,updated_at) "
                "VALUES(?,?, 'running', 4, 2, 0, 0, 1)", (self.user, self.root_id)
            )
        db_path = Path(self.temp.name) / "state" / "skjalf.sqlite3"
        self.service.close()
        restarted = SkjalfService(Path(self.temp.name) / "state", Path(self.temp.name) / "models")
        try:
            with restarted.lock:
                job = restarted.db.execute(
                    "SELECT status,processed FROM jobs WHERE user_id=? AND root_id=?", (self.user, self.root_id)
                ).fetchone()
            self.assertEqual((job["status"], job["processed"]), ("paused", 2))
        finally:
            restarted.close()
            # The fixture's service field now refers to the closed original handle.
            self.service = SkjalfService(Path(self.temp.name) / "state", Path(self.temp.name) / "models")

    def test_root_removal_fences_an_in_flight_embedding_commit(self):
        nc = FakeNC()
        node = FakeNode(self.file_id, "/Photos/a.png", "etag-1")
        with self.service.lock, self.service.db:
            self.service.db.execute(
                "INSERT INTO files(user_id,root_id,file_id,path,etag,status) VALUES(?,?,?,?,?,'pending')",
                (self.user, self.root_id, self.file_id, node.user_path, node.etag),
            )
        collection_name = "r_" + self.root_id
        collection = FakeCollection()
        client = FakeChromaClient(collection_name)
        self.service.enabled = True
        self.service.encoder = FakeEncoder()

        async def run():
            with patch.object(self.service, "_vector_collection", return_value=(client, collection)), \
                 patch("ex_app.lib.service.resolve_indexed_file", new=AsyncMock(return_value=node)):
                row = self.service.db.execute(
                    "SELECT file_id,path,etag FROM files WHERE user_id=? AND root_id=? AND file_id=?",
                    (self.user, self.root_id, self.file_id),
                ).fetchone()
                worker = asyncio.create_task(self.service._index_one(nc, self.user, self.root_id, row, self.service.encoder))
                await nc.files.started.wait()
                await self.service.remove_root(nc, self.root_id)
                nc.files.release.set()
                await worker

        asyncio.run(run())
        self.assertEqual(collection.upserts, [])
        self.assertEqual(client.deleted, [collection_name])

    def test_disabling_app_pauses_queued_work(self):
        with self.service.lock, self.service.db:
            self.service.db.execute(
                "INSERT INTO jobs(user_id,root_id,status,total,processed,failed,pause_requested,updated_at) "
                "VALUES(?,?, 'queued', 1, 0, 0, 0, 1)", (self.user, self.root_id)
            )
        asyncio.run(self.service.set_enabled(False))
        with self.service.lock:
            job = self.service.db.execute(
                "SELECT status,pause_requested FROM jobs WHERE user_id=? AND root_id=?", (self.user, self.root_id)
            ).fetchone()
        self.assertEqual((job["status"], job["pause_requested"]), ("queued", 1))


if __name__ == "__main__":
    unittest.main()
