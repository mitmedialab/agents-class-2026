"""Import the public Our Gardens portfolio directory into a local demo catalog.

Run with the Course Agent Python environment from class-agent:
    python examples/import_gardens_demo.py

Imports only source-linked public works and portfolio URLs. Preserves newer
indexed works and leaves student accounts, preferences and feedback untouched.
"""

import hashlib
import os
import re
from pathlib import Path

import httpx

from course_server.peer_discovery.models import Build, Catalog
from course_server.peer_discovery.preview import clean_title
from course_server.peer_discovery.store import PeerStore

SNAPSHOT = (
    "https://raw.githubusercontent.com/rainscyy/MyGarden4.0/"
    "0f4e44c2f58e7df5b6ed439846291659768cd8db/public/course-snapshot.json"
)


def main() -> None:
    response = httpx.get(SNAPSHOT, timeout=30)
    response.raise_for_status()
    snapshot = response.json()
    sites = {
        "agents2026-" + s["id"]: s["website"]
        for s in snapshot["students"]
        if re.fullmatch(r"[a-z0-9-]+", s["id"])
        and s["website"] == f"https://mitmedialab.github.io/agents2026-{s['id']}/"
    }
    store = PeerStore(Path(os.environ.get("PEER_DISCOVERY_PATH", "var/peer-discovery")))

    def merge(catalog: Catalog) -> None:
        catalog.sites.update(sites)
        records = {(b.source_url.removesuffix("index.html"), b.week): b for b in catalog.builds}
        for row in snapshot["builds"]:
            author = "agents2026-" + row["studentId"]
            url, week = row["sourceUrl"], row["week"]
            text = row.get("sourceExcerpt", "").strip()
            key = (url.removesuffix("index.html"), week)
            if (
                author not in sites
                or not url.startswith(sites[author])
                or not text
                or not isinstance(week, int)
                or not 1 <= week <= 14
                or row.get("origin") == "Local course documentation"
            ):
                continue
            reviewed = clean_title(row.get("title") or "")
            if key in records:
                if reviewed:
                    records[key].title = records[key].reviewed_title = reviewed
                continue
            # Some single-page portfolios host several weeks on the same URL.
            identity = f"{week}:{url}" if url == sites[author] else url
            records[key] = Build(
                id="build-" + hashlib.sha256(identity.encode()).hexdigest()[:16],
                project_id=author,
                week=week,
                title=reviewed or f"Week {week} · {author}",
                reviewed_title=reviewed or None,
                source_url=url,
                content=text,
                source_hash=hashlib.sha256(text.encode()).hexdigest(),
                observed_at=row["observedAt"],
                truncated=True,
            )
        catalog.builds = list(records.values())

    result = store.update_catalog(merge)
    print(f"{len(result.sites)} portfolio sites; {len(result.builds)} indexed records")


if __name__ == "__main__":
    main()
