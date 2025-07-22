from typing import TYPE_CHECKING, Callable, Literal

from datatrove.io import DataFileLike, DataFolderLike, get_datafolder
from datatrove.pipeline.readers.base import BaseDiskReader
from datatrove.pipeline.base import PipelineStep
from datatrove.data import DocumentsPipeline

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
    _requires_dependencies = ["warcio", ("cchardet", "faust-cchardet"), ("magic", "python-magic")]

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

def process_record(record: "ArcWarcRecord") -> dict | None:
    import cchardet
    import magic
    import tldextract

    content_bytes = record.content_stream().read()

    rec_type = record.rec_type
    if rec_type != "response":
        return

    url = record.rec_headers.get("WARC-Target-URI", "")
    fqdn = tldextract.extract(url).fqdn
    if not url or "/robots.txt" not in url.lower():
        return

    try:
        text = content_bytes.decode("utf-8", errors="replace")
        encoding = "utf-8"
    except Exception:
        encoding = cchardet.detect(content_bytes).get("encoding") or "utf-8"
        try:
            text = content_bytes.decode(encoding, errors="replace")
        except Exception as e:
            text = f"# {str(e)}"

    mime_type = record.rec_headers.get("WARC-Identified-Payload-Type", None)
    if mime_type is None:
        mime_type = magic.from_buffer(content_bytes, mime=True)
    if "html" in mime_type:
        text = "# html"

    if text == "":
        text = "# empty"

    return {
        "text": text,
        "fqdn": fqdn,
        "url": url,
        "id": record.rec_headers.get("WARC-Record-ID"),
        "date": record.rec_headers.get("WARC-Date"),
        "encoding": encoding,
        "mime_type": mime_type,
        "rec_type": rec_type,
    }


class RobotsMerger(PipelineStep):
    def __init__(self, input_folder: DataFolderLike, output_folder: DataFolderLike):
        super().__init__()
        self.input_folder = input_folder
        self.output_folder = output_folder
        self.robotstxt_dict = {}

    def run(self, data: DocumentsPipeline, rank: int = 0, world_size: int = 1) -> DocumentsPipeline:
        import gzip
        import orjson
        from dateutil import parser
        import os
        from pathlib import Path
        import tldextract

        input_path = Path(self.input_folder)

        for filepath in input_path.glob("*.jsonl.gz"):
            with gzip.open(filepath, "rt", encoding="utf-8") as gzfile:
                print(f"Reading {filepath}")
                for line in gzfile:
                    data = orjson.loads(line)
                    text = data['text']
                    metadata = data['metadata']
                    fqdn = tldextract.extract(metadata['url']).fqdn 
                    date = metadata['date']

                    stored = self.robotstxt_dict.get(fqdn)
                    if stored is None or parser.parse(date) > parser.parse(stored["date"]):
                        self.robotstxt_dict[fqdn] = {"text": text, "date": date}

        # Save robots_dict to a jsonl file using orjson
        os.makedirs(self.output_folder, exist_ok=True)
        with open(os.path.join(self.output_folder, "robotstxt_dict.jsonl"), "wb") as out_f:
            for key, value in self.robotstxt_dict.items():
                line = orjson.dumps({"key": key, "value": value}) + b"\n"
                out_f.write(line)