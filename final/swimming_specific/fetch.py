"""PDFs named by a URL instead of a path.

A text file of links is the input, one URL per line. Each is fetched just
before it is read, not all of them up front: a list of two hundred should not
spend twenty minutes downloading before the first page is extracted, and a link
that 404s should cost you that link at the moment it comes up, in the log
beside the document it belongs to.

Fetched PDFs are KEPT (config.DOWNLOAD_DIR) and reused. That is what makes a
stopped run resumable, and it means the source of a page the audit flagged can
still be opened afterwards. The flip side: a URL whose content changes is not
re-fetched. Delete the file, or the folder, to force a fresh copy.
"""
import csv
import hashlib
import re
from pathlib import Path
from urllib.parse import unquote, urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import DOWNLOAD_DIR, HTTP_RETRIES
from log import log

# A wrong link should cost you a download, not the disk. Result books run to a
# couple of MB; anything near this is not the document you meant.
MAX_BYTES = 200 * 1024 * 1024

# (connect, read). Split because a slow server is not a dead one: give up fast
# on one that never answers, patiently on one that is merely large.
TIMEOUT = (15, 120)


def _session() -> requests.Session:
    """GET's mirror of llm._session. Retried on 429 and 5xx, which arrive before
    any body was sent, so replaying one costs nothing but time."""
    s = requests.Session()
    retry = Retry(total=HTTP_RETRIES, backoff_factor=2,
                  status_forcelist=(429, 500, 502, 503, 504),
                  allowed_methods=frozenset({"GET"}), raise_on_status=False)
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.mount("http://", HTTPAdapter(max_retries=retry))
    # Some federation sites answer python-requests' default agent with a 403.
    s.headers["User-Agent"] = "swim-results-ocr/1.0"
    return s


SESSION = _session()


def _is_url(cell) -> bool:
    return str(cell).strip().lower().startswith(("http://", "https://"))


def read_links(path) -> list:
    """The URLs in a file, in order, without repeats.

    One per line is the expected shape. It is read with the csv module rather
    than splitlines so that a list exported from a spreadsheet — extra columns,
    a header row, quoted fields — also works: what identifies the URL is that
    it starts with http, not its column or the heading above it.

    Blank lines and lines starting with # are ignored, so a list can be
    commented and links can be turned off without deleting them.
    """
    rows, urls, seen, no_link = [], [], set(), []
    with open(path, newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.reader(fh))

    for n, cells in enumerate(rows, 1):
        cells = [c.strip() for c in cells]
        if not any(cells) or cells[0].startswith("#"):
            continue
        url = next((c for c in cells if _is_url(c)), None)
        if not url:
            no_link.append(n)
        elif url in seen:
            log.warning(f"! {path} line {n}: {url} is already in the list — read once")
        else:
            seen.add(url)
            urls.append(url)

    # Named lines, not just a count: on a hand-typed list this is usually one
    # typo, and the line number is the whole of what you need to fix it.
    if no_link:
        shown = ", ".join(str(n) for n in no_link[:5])
        more = f" (+{len(no_link) - 5} more)" if len(no_link) > 5 else ""
        log.warning(f"! {path}: no http link on line(s) {shown}{more} — skipped")

    if not urls:
        raise SystemExit(f"no http(s) links in {path} — expected one URL per line")
    return urls


def stem_of(url: str) -> str:
    """A readable name for a URL: its last path segment, without the extension.

    The query string is dropped. It is usually a session token or a download
    counter, and two links differing only there are the same document."""
    base = Path(unquote(urlparse(url).path)).stem
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("._-")
    return base[:60] or "download"


def local_name(url: str) -> str:
    """What the fetched file is called on disk.

    Readable, but ending in a hash of the WHOLE url — including the query and
    the host — so that two events both publishing a `results.pdf` cannot
    overwrite each other, and so a second run finds the copy the first fetched
    instead of downloading it again."""
    return f"{stem_of(url)}_{hashlib.sha1(url.encode()).hexdigest()[:8]}.pdf"


def _is_pdf(p) -> bool:
    """Does this file begin with the PDF marker? Cheap, and the only check that
    separates a real document from a saved error page."""
    try:
        with open(p, "rb") as fh:
            return fh.read(5).startswith(b"%PDF")
    except OSError:
        return False


def download(url: str, into=None) -> Path:
    """Fetch one PDF, return where it landed. A good local copy is reused.

    Written to a .part file and renamed only once it is complete AND starts
    with %PDF, so an interrupted run cannot leave a truncated file behind that
    the next run mistakes for a finished download.
    """
    dest = Path(into or DOWNLOAD_DIR) / local_name(url)
    if _is_pdf(dest):
        log.info(f"  already fetched: {dest.name}")
        return dest

    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(".part")
    log.info(f"  fetching {url}")

    got = 0
    with SESSION.get(url, timeout=TIMEOUT, stream=True) as r:
        r.raise_for_status()
        with open(part, "wb") as fh:
            for chunk in r.iter_content(65536):
                got += len(chunk)
                if got > MAX_BYTES:
                    fh.close()
                    part.unlink(missing_ok=True)
                    raise RuntimeError(f"larger than {MAX_BYTES // 1024**2} MB — "
                                       f"is this really a PDF?")
                fh.write(chunk)

    # A 200 proves the server answered, not that it answered with a document:
    # a login wall and a friendly 404 page are both 200s full of HTML.
    if not _is_pdf(part):
        head = part.read_bytes()[:40]
        part.unlink(missing_ok=True)
        raise RuntimeError(f"not a PDF, starts {head!r} — a login or error page "
                           f"is the usual reason")

    part.replace(dest)
    log.info(f"  {got:,} bytes -> {dest.name}")
    return dest
