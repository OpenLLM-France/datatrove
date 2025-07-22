from typing import Callable, Literal

from datatrove.io import DataFileLike, DataFolderLike
from datatrove.pipeline.readers.base import BaseDiskReader
from datatrove.utils.logging import logger


class JsonReader(BaseDiskReader):
    """Read data from JSON files.
       Supports either:
       - a list of JSON objects in the file
       - a single JSON object in the file

    Args:
        data_folder: a str, tuple or DataFolder object representing a path/filesystem
        paths_file: optionally provide a file with one path per line (without the `data_folder` prefix) to read.
        compression: the compression to use (default: "infer")
        limit: limit the number of documents to read. Useful for debugging
        skip: skip the first n rows
        file_progress: show progress bar for files
        doc_progress: show progress bar for documents
        adapter: function to adapt the data dict from the source to a Document.
        text_key: the key containing the text data (default: "text").
        id_key: the key containing the id for each sample (default: "id").
        default_metadata: a dictionary with any data that should be added to all samples' metadata
        recursive: whether to search files recursively. Ignored if paths_file is provided
        glob_pattern: pattern that all files must match exactly to be included (relative to data_folder). Ignored if paths_file is provided
        shuffle_files: shuffle the files within the returned shard. Mostly used for data viz. purposes, do not use with dedup blocks
    """

    name = "🦊 Json"
    _requires_dependencies = ["orjson"]

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
        self.compression = compression

    def read_file(self, filepath: str):
        import orjson
        from orjson import JSONDecodeError

        with self.data_folder.open(filepath, "r", compression=self.compression) as f:
            try:
                data = orjson.loads(f.read())
            except (UnicodeDecodeError, JSONDecodeError) as e:
                logger.warning(f"File `{filepath}` is not valid JSON: {e}")
                return

        if isinstance(data, list):
            for li, item in enumerate(data):
                with self.track_time():
                    try:
                        document = self.get_document_from_dict(item, filepath, li)
                        if document:
                            yield document
                    except Exception as e:
                        logger.warning(f"Error processing item {li} in `{filepath}`: {e}")
        elif isinstance(data, dict):
            with self.track_time():
                try:
                    document = self.get_document_from_dict(data, filepath, 0)
                    if document:
                        yield document
                except Exception as e:
                    logger.warning(f"Error processing `{filepath}`: {e}")
        else:
            logger.warning(f"Unsupported JSON structure in `{filepath}` (expected list or dict)")
