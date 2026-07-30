from typing import TYPE_CHECKING, Callable, Literal

from datatrove.io import DataFileLike, DataFolderLike
from datatrove.pipeline.readers.base import BaseDiskReader
from datatrove.pipeline.base import PipelineStep
from datatrove.data import DocumentsPipeline
from dateutil import parser
from pathlib import Path
import tldextract
import gzip
import orjson
import os

if TYPE_CHECKING:
    from warcio.recordloader import ArcWarcRecord


class WarcForRobotsReader(BaseDiskReader):
    """Read data from WARC files.
        Will read each record as a separate document.

    Args:
        data_folder: a str, tuple or DataFolder object representing a path/filesystem
        paths_file: optionally provide a file with one path per line (without the `data_folder` prefix) to read.
        compression: the compression to use (default: "infer")
        limit: limit the number of documents to read. Useful for debugging
        skip: skip the first n rows
        file_progress: show progress bar for files
        doc_progress: show progress bar for documents
        adapter: function to adapt the data dict from the source to a Document.
            Takes as input: (self, data: dict, path: str, id_in_file: int | str)
                self allows access to self.text_key and self.id_key
            Returns: a dict with at least a "text" and "id" keys
        text_key: the key containing the text data (default: "text").
        id_key: the key containing the id for each sample (default: "id").
        default_metadata: a dictionary with any data that should be added to all samples' metadata
        recursive: whether to search files recursively. Ignored if paths_file is provided
        glob_pattern: pattern that all files must match exactly to be included (relative to data_folder). Ignored if paths_file is provided
        shuffle_files: shuffle the files within the returned shard. Mostly used for data viz. purposes, do not use with dedup blocks
    """

    name = "🕷 Warc For Robots"
    _requires_dependencies = ["warcio", ("magic", "python-magic"), "tldextract"]

    def __init__(
        self,
        data_folder: DataFolderLike,
        paths_file: DataFileLike | None = None,
        compression: Literal["infer", "gzip", "zstd"] | None = "infer",
        limit: int = -1,
        skip: int = 0,
        file_progress: bool = False,
        doc_progress: bool = False,
        adapter: Callable = None,
        text_key: str = "text",
        id_key: str = "id",
        default_metadata: dict = None,
        recursive: bool = True,
        glob_pattern: str | None = None,
        shuffle_files: bool = False,
    ):
        self.compression = compression
        super().__init__(
            data_folder,
            paths_file,
            limit,
            skip,
            file_progress,
            doc_progress,
            adapter,
            text_key,
            id_key,
            default_metadata,
            recursive,
            glob_pattern,
            shuffle_files,
        )

    def read_file(self, filepath: str):
        from warcio.archiveiterator import ArchiveIterator

        with self.data_folder.open(filepath, "rb", compression=self.compression) as f:
            for ri, record in enumerate(ArchiveIterator(f)):
                with self.track_time():
                    extracted_data = process_record(record)
                    if not extracted_data:
                        continue
                    document = self.get_document_from_dict(extracted_data, filepath, ri)
                    if not document:
                        continue
                yield document

# RFC 9309 §2.3.1 maps HTTP statuses onto a few "access results". We keep that
# classification explicit because two of them are opposites for opt-out purposes:
# "unavailable" means the site published no rules at all (crawling is allowed),
# while "unreachable" means we never learned what the rules are (assume disallow).
STATUS_SUCCESS = "success"  # 2xx: follow the parseable rules in the body
STATUS_REDIRECT = "redirect"  # 3xx: the rules live at another location
STATUS_UNAVAILABLE = "unavailable"  # 4xx: "the crawler MAY access any resources"
STATUS_UNREACHABLE = "unreachable"  # 5xx (+429): "MUST assume complete disallow"
STATUS_UNKNOWN = "unknown"  # missing or unparseable status line

# The two classes for which Common Crawl's own robots parser (crawler-commons) reaches
# a verdict: rules read from the body (2xx), or ALLOW_ALL because the site publishes no
# robots.txt (4xx). Every other class sets crawler-commons' deferVisits flag, which
# means "no answer, come back later" rather than a statement about the site's wishes.
CONCLUSIVE_STATUS = frozenset({STATUS_SUCCESS, STATUS_UNAVAILABLE})


def classify_status(status_code: str | int | None) -> str:
    """Classify an HTTP status code according to RFC 9309 §2.3.1.

    429 is grouped with 5xx rather than with the rest of 4xx, which is what Common Crawl
    itself does: crawler-commons' SimpleRobotRulesParser.failedFetch() would answer
    ALLOW_ALL for any 4xx, but Nutch intercepts the status first
    (HttpRobotRulesParser.getRobotRulesSet: `else if (code >= 500 || code == 429)`) and
    returns DEFER_VISIT_RULES, gated on http.robots.503.defer.visits (default true,
    documented as covering "any other 5xx server error and HTTP 429 Too Many Requests").
    A rate limit says nothing about permissions, so this also matches the RFC's intent.
    """
    try:
        code = int(status_code)
    except (TypeError, ValueError):
        return STATUS_UNKNOWN
    if 200 <= code < 300:
        return STATUS_SUCCESS
    if 300 <= code < 400:
        return STATUS_REDIRECT
    if code == 429 or 500 <= code < 600:
        return STATUS_UNREACHABLE
    if 400 <= code < 500:
        return STATUS_UNAVAILABLE
    return STATUS_UNKNOWN


def process_record(record: "ArcWarcRecord") -> dict | None:
    import magic
    from urllib.parse import urlparse

    # only response records can carry a robots.txt body
    if record.rec_type != "response":
        return

    url = record.rec_headers.get("WARC-Target-URI", "")
    # robots.txt is only authoritative at the site root
    if not url or urlparse(url).path.lower() != "/robots.txt":
        return

    # The robotstxt/ WARCs hold *every* robots.txt fetch, not only the successful
    # ones: ~1/3 are 404/3xx/403/429/5xx. Keep the status so the merge policy can
    # tell "site allows everything" (4xx) from "fetch failed" (5xx/429) instead of
    # guessing from the body.
    status_code = record.http_headers.get_statuscode() if record.http_headers else None
    status_class = classify_status(status_code)

    # only now do we pay for reading/decoding the payload
    content_bytes = record.content_stream().read()

    mime_type = record.rec_headers.get("WARC-Identified-Payload-Type", None)
    if mime_type is None:
        mime_type = magic.from_buffer(content_bytes, mime=True)

    if "html" in (mime_type or ""):
        # A robots.txt URL that served HTML has no rules to parse (in practice this is
        # always an error or redirect page - see status_class for *why* it failed). A
        # lone comment keeps the stored text parseable as an empty rule set.
        text = "# html"
    else:
        # robots.txt is spec'd as UTF-8; replace undecodable bytes rather than guess
        text = content_bytes.decode("utf-8", errors="replace")
        if text == "":
            text = "# empty"

    return {
        "text": text,
        "fqdn": tldextract.extract(url).fqdn,
        "url": url,
        "id": record.rec_headers.get("WARC-Record-ID"),
        "date": record.rec_headers.get("WARC-Date"),
        "mime_type": mime_type,
        "rec_type": record.rec_type,
        "status_code": status_code,
        "status_class": status_class,
    }


class RobotsMerger(PipelineStep):
    def __init__(self, input_folder: DataFolderLike, output_folder: DataFolderLike):
        super().__init__()
        self.input_folder = input_folder
        self.output_folder = output_folder
        self.robotstxt_dict = {}

    @staticmethod
    def _should_replace(stored: dict | None, new_class: str, new_date: str) -> bool:
        """Merge policy: Common Crawl's own verdicts, keyed on the *newest* observation.

        A 2xx (these are the rules) and a 4xx (there are no rules, so ALLOW_ALL) are both
        conclusive, so recency alone decides between them: a site that has since deleted
        its robots.txt no longer restricts anything, and one that has since added rules
        does. That is the whole point of applying an up-to-date robots.txt retroactively,
        and it is why a newer 4xx is allowed to supersede an older rule set.

        deferVisits classes (3xx/429/5xx) are not verdicts, so they never displace a
        conclusive record however recent they are; they only fill in for domains where
        nothing conclusive was ever observed.
        """
        if stored is None:
            return True
        new_conclusive = new_class in CONCLUSIVE_STATUS
        stored_conclusive = stored["status_class"] in CONCLUSIVE_STATUS
        if new_conclusive != stored_conclusive:
            return new_conclusive
        return parser.parse(new_date) > parser.parse(stored["date"])

    def run(self, data: DocumentsPipeline, rank: int = 0, world_size: int = 1) -> DocumentsPipeline:
        input_path = Path(self.input_folder)

        shards = sorted(input_path.glob("*.jsonl.gz"))
        if not shards:
            # writing an empty dict here would silently drop every document downstream
            raise ValueError(f"No *.jsonl.gz shard found in {input_path}")

        for filepath in shards:
            with gzip.open(filepath, "rt", encoding="utf-8") as gzfile:
                print(f"Reading {filepath}")
                for line in gzfile:
                    record = orjson.loads(line)
                    text = record['text']
                    metadata = record['metadata']
                    fqdn = metadata['fqdn']
                    status_class = metadata['status_class']
                    date = metadata['date']

                    stored = self.robotstxt_dict.get(fqdn)
                    if self._should_replace(stored, status_class, date):
                        self.robotstxt_dict[fqdn] = {
                            "text": text,
                            "date": date,
                            "status_class": status_class,
                        }

        # Save robots_dict to a jsonl file using orjson
        os.makedirs(self.output_folder, exist_ok=True)
        with open(os.path.join(self.output_folder, "robotstxt_dict.jsonl"), "wb") as out_f:
            for key, value in self.robotstxt_dict.items():
                line = orjson.dumps({"fqdn": key, **value}) + b"\n"
                out_f.write(line)