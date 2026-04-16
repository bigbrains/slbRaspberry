"""
display/manual_ref.py — syncs and caches cropped reference photos from the CLB server.

GET /api/photos/list?source=crop  (cursor-based, newest-first)
GET /api/photos/{id}              (download)
"""
import logging
import os

import requests
from PIL import Image

log = logging.getLogger(__name__)

_CACHE_DIR = "/home/pi/slb/ref_photos"
_SIZE      = 240


def _fit(img: Image.Image) -> Image.Image:
    w, h  = img.size
    side  = min(w, h)
    img   = img.crop(((w - side) // 2, (h - side) // 2,
                      (w + side) // 2, (h + side) // 2))
    return img.resize((_SIZE, _SIZE), Image.LANCZOS)


class ManualRefPhotos:
    """Downloads and caches cropped reference photos (source=crop)."""

    def __init__(self):
        os.makedirs(_CACHE_DIR, exist_ok=True)
        self._ids: list[int] = []
        self._idx: int = 0

    # ── Sync ──────────────────────────────────────────────────────────────────

    def sync(self, api_base: str) -> bool:
        """Fetch newest IDs from server, download missing photos.
        Returns True if anything changed."""
        new_ids = self._fetch_list(api_base)
        if new_ids is None:
            return False

        changed    = new_ids != self._ids
        self._ids  = new_ids
        downloaded = self._download_missing(api_base)

        if self._ids:
            self._idx = min(self._idx, len(self._ids) - 1)

        return changed or downloaded

    # ── Navigation ────────────────────────────────────────────────────────────

    def next(self):
        if self._ids:
            self._idx = (self._idx + 1) % len(self._ids)

    def prev(self):
        if self._ids:
            self._idx = (self._idx - 1) % len(self._ids)

    # ── Access ────────────────────────────────────────────────────────────────

    @property
    def count(self) -> int:
        return len(self._ids)

    @property
    def label(self) -> str:
        if not self._ids:
            return ""
        return f"{self._idx + 1}/{len(self._ids)}"

    def current_img(self) -> Image.Image | None:
        if not self._ids:
            return None
        return self._load_img(self._ids[self._idx])

    # ── Private ───────────────────────────────────────────────────────────────

    def _fetch_list(self, api_base: str, max_photos: int = 20) -> list[int] | None:
        """GET /api/photos/list?source=crop with cursor pagination."""
        ids    = []
        before = None
        try:
            while len(ids) < max_photos:
                params: dict = {"source": "crop", "limit": min(10, max_photos - len(ids))}
                if before is not None:
                    params["before"] = before
                resp = requests.get(f"{api_base}/api/photos/list", params=params, timeout=5)
                resp.raise_for_status()
                data   = resp.json()
                photos = data.get("photos") or []
                for p in photos:
                    if isinstance(p, dict) and "id" in p:
                        ids.append(int(p["id"]))
                before = data.get("nextBefore")
                if not photos or before is None:
                    break
            return ids
        except Exception as e:
            log.warning("manual_ref fetch failed: %s", e)
            return None

    def _download_missing(self, api_base: str) -> bool:
        downloaded = False
        for id_ in self._ids:
            path = os.path.join(_CACHE_DIR, f"{id_}.jpg")
            if not os.path.exists(path):
                try:
                    r = requests.get(f"{api_base}/api/photos/{id_}", timeout=15)
                    r.raise_for_status()
                    with open(path, "wb") as fh:
                        fh.write(r.content)
                    log.info("downloaded photo %d", id_)
                    downloaded = True
                except Exception as e:
                    log.warning("download %d failed: %s", id_, e)
        return downloaded

    def _load_img(self, id_: int) -> Image.Image | None:
        path = os.path.join(_CACHE_DIR, f"{id_}.jpg")
        if not os.path.exists(path):
            return None
        try:
            img = Image.open(path)
            img.load()
            return _fit(img)
        except Exception as e:
            log.warning("open %d failed: %s", id_, e)
            return None
