from datatrove.utils.text import split_into_parts
from datatrove.pipeline.base import PipelineStep
from datatrove.data import Document, DocumentsPipeline
import re

class SplitDocument(PipelineStep):
    type = "📑 - SPLIT & MERGE"
    name = "📑  Split Document"

    def __init__(
        self,
        mode: str = "CHUNKS",
        separator: str = " ",
        min_length: int = 1000,
    ):
        super().__init__()
        self.mode = mode
        self.separator = separator
        self.min_length = min_length

    def run(self, data: DocumentsPipeline, rank: int = 0, world_size: int = 1) -> DocumentsPipeline:
        for doc in data:
            units = split_into_parts(doc.text, mode=self.mode, separator=self.separator, min_length=self.min_length)
            doc.text = doc.text.strip()
            doc.metadata["chunk_count"] = len(units)
            doc.metadata["initial_length"] = len(doc.text)
            for i, unit in enumerate(units):
                doc_metadata = {"__doc__" + k: v for k, v in doc.metadata.items()}
                splitted_doc = Document(text=unit, id=doc.id, metadata=doc_metadata)
                splitted_doc.metadata["chunk_index"] = i
                yield splitted_doc

from collections import defaultdict
from typing import Dict, Any

def merge_chunk_metadata(target: defaultdict[str, list], source: Dict[str, Any], prefix: str = "__doc__") -> None:
    for k, v in source.items():
        if not k.startswith(prefix):
            if isinstance(v, list):
                target[k].extend(v)
            else:
                target[k].append(v)


class MergeDocument(PipelineStep):
    type = "📑 - SPLIT & MERGE"
    name = "📑  Merge Document"

    def __init__(
        self,
        replace_span: str = "\n\n[...]\n\n",
    ):
        super().__init__()
        self.replace_span = replace_span

    def run(self, data: DocumentsPipeline, rank: int = 0, world_size: int = 1) -> DocumentsPipeline:
        doc = None 
        for chunk in data:
            if (doc is None) or (doc.id != chunk.id):
                # Yield the previous document if it exists
                if doc is not None:
                    if previous_chunk_index < doc.metadata["chunk_count"] - 1:
                        doc.text += "<<removed_span>>"
                    doc.text = re.sub(r'(<<removed_span>>)+', self.replace_span, doc.text).strip()
                    doc.metadata.update(chunk_metadata)  # Merge chunk metadata
                    doc.metadata["final_length"] = len(doc.text)
                    yield doc
                # New document, reset the doc and chunk_metadatas
                doc = Document(
                    id=chunk.id, 
                    text="",
                    metadata={k.removeprefix("__doc__"): v for k, v in chunk.metadata.items() if k.startswith("__doc__")}
                )
                chunk_metadata = defaultdict(list)  # Initialize as dict of lists
                previous_chunk_index = -1
            # Append the chunk text
            if chunk.metadata["chunk_index"] != previous_chunk_index + 1:
                doc.text += "<<removed_span>>"
            doc.text += chunk.text
            # Merge chunk metadata into dict of lists
            merge_chunk_metadata(chunk_metadata, chunk.metadata)
            previous_chunk_index = chunk.metadata["chunk_index"]
