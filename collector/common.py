"""Shared helpers: paths, HTTP session, JSON files and file names."""
import datetime as dt
import gzip
import hashlib
import json
import pathlib
import re
import unicodedata

import requests

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))

USER_AGENT = "cs-skin-prices/1.0 (+https://github.com/JulioPeixoto/cs-skin-prices)"


def session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
    return s


def now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def read_json(path: pathlib.Path, default=None):
    if not path.exists():
        return default
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as f:
            return json.load(f)
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: pathlib.Path, obj, pretty: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(obj, ensure_ascii=False, indent=1 if pretty else None,
                      separators=None if pretty else (",", ":"))
    if path.suffix == ".gz":
        # mtime=0 keeps the bytes stable when the content does not change
        with open(path, "wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as f:
            f.write(text.encode("utf-8"))
    else:
        path.write_text(text + "\n", encoding="utf-8")


def slug(name: str) -> str:
    """File-safe, stable name for an item: readable part plus a short hash."""
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    base = re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")[:80]
    digest = hashlib.sha1(name.encode("utf-8")).hexdigest()[:8]
    return f"{base}-{digest}"
