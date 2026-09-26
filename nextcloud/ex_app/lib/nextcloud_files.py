"""Safe access helpers for the authenticated user's regular Nextcloud Files space."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any

from .catalog import normalize_user_path

IMAGE_SUFFIXES = frozenset(
    {".avif", ".bmp", ".gif", ".heic", ".heif", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}
)


class FileUnavailable(Exception):
    """A file is missing, outside the selected personal root, or no longer readable."""


def _path_is_at_or_below(path: str, root: str) -> bool:
    candidate = PurePosixPath(normalize_user_path(path))
    base = PurePosixPath(normalize_user_path(root))
    return candidate == base or base in candidate.parents


def _path_is_below(path: str, root: str) -> bool:
    candidate = PurePosixPath(normalize_user_path(path))
    base = PurePosixPath(normalize_user_path(root))
    return candidate != base and base in candidate.parents


def _is_regular_personal_node(node: Any) -> bool:
    """Reject shared mounts and unreadable nodes using Nextcloud's DAV permissions."""
    if node is None or node.info.in_trash or node.info.is_version:
        return False
    if node.is_shared or node.is_mounted or not node.is_readable:
        return False
    return True


def _is_image(node: Any) -> bool:
    mime = (node.info.mimetype or "").lower()
    suffix = PurePosixPath(node.name).suffix.lower()
    return mime.startswith("image/") or suffix in IMAGE_SUFFIXES


async def _assert_personal_path(nc: Any, path: str, *, allow_home: bool = False) -> Any:
    """Check every ancestor through the per-user WebDAV API to reject nested mounts."""
    normalized = normalize_user_path(path)
    if not normalized:
        if allow_home:
            return None
        raise FileUnavailable("Der persönliche Dateibereich kann nicht als Suchordner registriert werden.")
    current = ""
    last_node = None
    for part in PurePosixPath(normalized).parts:
        current = f"{current}/{part}".strip("/")
        node = await nc.files.by_path(current)
        if not _is_regular_personal_node(node) or not node.is_dir:
            raise FileUnavailable("Der Ordner gehört nicht zum persönlichen Dateibereich.")
        last_node = node
    return last_node


async def list_personal_folders(nc: Any, path: str) -> list[dict[str, str]]:
    """List direct personal subfolders. Shares, external mounts, and E2EE are omitted."""
    path = normalize_user_path(path)
    await _assert_personal_path(nc, path, allow_home=True)
    nodes = await nc.files.listdir(path, depth=1)
    folders: list[dict[str, str]] = []
    for node in nodes:
        if not node.is_dir or not _is_regular_personal_node(node):
            continue
        folder_path = normalize_user_path(node.user_path)
        if folder_path != path and not _path_is_below(folder_path, path):
            continue
        folders.append(
            {"file_id": node.file_id, "path": folder_path, "name": node.name, "etag": node.etag}
        )
    return folders


async def resolve_personal_folder(nc: Any, file_id: str) -> Any:
    """Resolve a selected root by stable file id, validating its whole path."""
    node = await nc.files.by_id(file_id)
    if not node or not node.is_dir or not _is_regular_personal_node(node):
        raise FileUnavailable("Der ausgewählte Ordner ist nicht verfügbar.")
    await _assert_personal_path(nc, node.user_path)
    return node


async def scan_root(nc: Any, root_node: Any) -> tuple[Any, dict[str, Any]]:
    """Walk one validated own directory at a time, collecting current FsNodes by ID."""
    if not root_node or not root_node.is_dir or not _is_regular_personal_node(root_node):
        raise FileUnavailable("Der ausgewählte Ordner ist nicht verfügbar.")
    current_root_path = normalize_user_path(root_node.user_path)
    # Recheck every ancestor immediately before the recursive DAV walk so nested
    # shares and mount points cannot be traversed through an otherwise personal root.
    await _assert_personal_path(nc, current_root_path)
    discovered: dict[str, Any] = {}
    pending_dirs = [current_root_path]
    visited_dirs: set[str] = set()

    while pending_dirs:
        folder_path = pending_dirs.pop()
        if folder_path in visited_dirs:
            continue
        visited_dirs.add(folder_path)
        children = await nc.files.listdir(folder_path, depth=1)
        for node in children:
            if not _is_regular_personal_node(node):
                continue
            child_path = normalize_user_path(node.user_path)
            if not _path_is_below(child_path, current_root_path):
                continue
            if node.is_dir:
                pending_dirs.append(child_path)
                continue
            if not _is_image(node) or not node.file_id:
                continue
            discovered[node.file_id] = node
    return root_node, discovered


async def resolve_indexed_file(nc: Any, file_id: str, root_path: str) -> Any:
    """Re-check existence, current path, and read access immediately before use/display."""
    node = await nc.files.by_id(file_id)
    if not node or node.is_dir or not _is_regular_personal_node(node):
        raise FileUnavailable("Die Datei ist nicht mehr verfügbar.")
    path = normalize_user_path(node.user_path)
    if not _path_is_below(path, root_path):
        raise FileUnavailable("Die Datei liegt nicht mehr im ausgewählten Ordner.")
    relative = PurePosixPath(path).relative_to(PurePosixPath(normalize_user_path(root_path)))
    parent = PurePosixPath(normalize_user_path(root_path))
    for part in relative.parts[:-1]:
        parent = parent / part
        ancestor = await nc.files.by_path(parent.as_posix())
        if not _is_regular_personal_node(ancestor) or not ancestor.is_dir:
            raise FileUnavailable("Der Dateiordner ist nicht mehr verfügbar.")
    if not _is_image(node):
        raise FileUnavailable("Die Datei ist kein unterstütztes Bild.")
    return node
