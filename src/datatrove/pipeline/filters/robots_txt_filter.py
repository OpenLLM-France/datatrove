from datatrove.data import Document
from datatrove.pipeline.filters.base_filter import BaseFilter
from datatrove.pipeline.writers.disk_base import DiskWriter
from datatrove.pipeline.readers.warc_for_robots import (
    CONCLUSIVE_STATUS,
    STATUS_SUCCESS,
    STATUS_UNAVAILABLE,
)
import urllib.robotparser
import tldextract
import json
import os


class RobotsTxtFilter(BaseFilter):
    """
    Removes documents whose url is disallowed by the robots.txt of the site it came from.

    Common Crawl already enforced robots.txt for `CCBot` when it fetched these pages, so this filter
    is purely retroactive: it catches sites that changed their robots.txt (or started failing) after
    being crawled. The store it reads is `robotstxt_dict.jsonl`, as produced by `RobotsMerger`, which
    keeps the most recent conclusive record per fqdn.

    Args:
        robots_txt_path: folder holding `robotstxt_dict.jsonl`, or `robots.db` with use_database
        use_database: look the rules up in `robots.db` (built by `robots_jsonl_to_db.py`) instead of
            loading the jsonl into memory. The jsonl costs ~0.85 GB of RAM per million records *in
            every worker process* - ~50 GB for a full CC dump - while the db answers from disk in a
            few dozen microseconds at flat memory.
        www_fallback: when the document's own fqdn has no conclusive record, retry the lookup with
            `www.` toggled. Roughly a third of the 3xx records are bare<->www redirects, where the
            rules are stored under the sibling fqdn.
        exclusion_writer: optionally save the dropped documents
    """

    name = "🤖🚫 Check robots.txt"
    _requires_dependencies = ["tldextract"]

    def __init__(
        self,
        robots_txt_path: str | None = None,
        use_database: bool = False,
        www_fallback: bool = True,
        exclusion_writer: DiskWriter = None,
    ):
        super().__init__(exclusion_writer)
        self.robots_txt_path = robots_txt_path
        self.use_database = use_database
        self.www_fallback = www_fallback
        self.robots_txt_dict = None
        self.db = None
        self.db_has_status = True
        self.tld_extractor = tldextract.TLDExtract()

    def __getstate__(self):
        # a sqlite3.Connection cannot be pickled to a worker, and one inherited through a fork
        # cannot be shared safely either - drop it and let the worker open its own
        return {**self.__dict__, "db": None}

    def get_db(self):
        """Open `robots.db` read-only, lazily, so the connection is created in the process that
        uses it rather than in the one that builds the pipeline."""
        if self.db is None:
            import sqlite3

            db_path = os.path.join(self.robots_txt_path, "robots.db")
            if not os.path.isfile(db_path):
                # sqlite would only say "unable to open database file", which reads like a
                # permission problem rather than "you never built the store"
                raise FileNotFoundError(
                    f"use_database=True but there is no robots.db in {self.robots_txt_path}. "
                    f"Build it from the merger's output with `python robots_jsonl_to_db.py "
                    f"{self.robots_txt_path}`, or pass use_database=False to read the jsonl."
                )
            try:
                self.db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, check_same_thread=False)
                columns = {row[1] for row in self.db.execute("PRAGMA table_info(robots)")}
            except sqlite3.OperationalError as e:
                raise RuntimeError(f"could not open {db_path}: {e}") from e
            if not columns:
                raise ValueError(f"{db_path} holds no `robots` table")
            # a db built from a store that predates the status field only holds successful fetches
            self.db_has_status = "status_class" in columns
        return self.db

    def get_record(self, fqdn: str) -> dict | None:
        """The stored record for one key, from whichever backend is configured."""
        if not self.use_database:
            return self.get_robots_txt_dict().get(fqdn)
        db = self.get_db()
        query = (
            "SELECT text, status_class FROM robots WHERE fqdn = ?"
            if self.db_has_status
            else "SELECT text FROM robots WHERE fqdn = ?"
        )
        row = db.execute(query, (fqdn,)).fetchone()
        if row is None:
            return None
        status_class = row[1] if self.db_has_status else None
        return {"text": row[0], "status_class": status_class or STATUS_SUCCESS}

    def load_robots_txt(self) -> dict[str, dict]:
        data = {}
        with open(os.path.join(self.robots_txt_path, "robotstxt_dict.jsonl"), 'r', encoding='utf-8') as f:
            for line in f:
                info = json.loads(line)
                data[info["fqdn"]] = {
                    "text": info["text"],
                    # stores written before the reader recorded http statuses only held successful
                    # fetches, so an absent status_class means "these are the rules"
                    "status_class": info.get("status_class", STATUS_SUCCESS),
                }
        return data

    def get_robots_txt_dict(self):
        if self.robots_txt_dict is None:
            self.robots_txt_dict = self.load_robots_txt()
        return self.robots_txt_dict

    @staticmethod
    def sibling_fqdn(fqdn: str) -> str:
        """The same host with `www.` toggled, which is where a bare<->www redirect leads."""
        return fqdn[4:] if fqdn.startswith("www.") else f"www.{fqdn}"

    def lookup(self, fqdn: str) -> dict | None:
        record = self.get_record(fqdn)
        if not self.www_fallback or (record is not None and record["status_class"] in CONCLUSIVE_STATUS):
            return record
        # only a conclusive sibling is worth borrowing: a non-conclusive one says nothing that the
        # record we already have does not, and an exact-fqdn record always wins otherwise
        sibling = self.get_record(self.sibling_fqdn(fqdn))
        if sibling is not None and sibling["status_class"] in CONCLUSIVE_STATUS:
            return sibling
        return record

    def filter(self, doc: Document) -> bool:
        # Extract fdn
        url = doc.metadata['url']
        fqdn = self.tld_extractor(url).fqdn.lower()
        if not fqdn:
            # IP literals and hosts outside the public suffix list. Stores merged before empty
            # fqdns were dropped hold a '' record, and it is one arbitrary site's rules.
            return False, "robots_txt_no_fqdn"
        # Find the robots.txt
        record = self.lookup(fqdn)

        if record is None:
            return False, "robots_txt_not_found"

        status_class = record["status_class"]
        doc.metadata["robots_txt_status_class"] = status_class

        # The status classes that carry no rules to parse. Follows RFC 9309 §2.3.1 and what Common
        # Crawl's own parser would have decided at fetch time: 4xx means the site publishes no
        # robots.txt at all, so crawling is allowed; a 3xx left unresolved after the follow limit is
        # ALLOW_NONE in crawler-commons; 429/5xx is "MUST assume complete disallow".
        if status_class != STATUS_SUCCESS:
            if status_class == STATUS_UNAVAILABLE:
                return True
            return False, f"robots_txt_{status_class}"

        # Initialize the robot parser. The "# html" / "# empty" placeholder bodies the reader writes
        # parse to an empty rule set, i.e. allow-all - which is only reachable here, on a 2xx.
        try: # Only for malformed robots.txt - extremely rare
            rp = urllib.robotparser.RobotFileParser()
            rp.parse(record["text"].splitlines())
            can_fetch = rp.can_fetch("CCBot", url)
        except ValueError:
            return True

        if not can_fetch:
            return False, 'robots_txt_disallow'
        else:
            return True