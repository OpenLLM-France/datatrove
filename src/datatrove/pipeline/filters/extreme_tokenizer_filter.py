from datatrove.pipeline.writers.disk_base import DiskWriter
from datatrove.data import Document
from datatrove.pipeline.filters.base_filter import BaseFilter
from functools import cached_property
import os

def load_tokenizer(name_or_path: str) -> "Tokenizer":
    from tokenizers import Tokenizer

    if os.path.isfile(name_or_path):
        return Tokenizer.from_file(name_or_path)

    return Tokenizer.from_pretrained(name_or_path)

class ExtremeTokenizerFilter(BaseFilter):
    _requires_dependencies = ["tokenizers"]

    name = " Extreme Tokenizer Filter"

    def __init__(
        self,
        tokenizer_name_or_path: str | None = None,
        exclusion_writer: DiskWriter = None,
        min_length_chunk: int = 1000,
        min_token_per_char: float = 0.2,
        max_token_per_char: float = 0.38,
    ):
        super().__init__(exclusion_writer)
        self.tokenizer_name_or_path = tokenizer_name_or_path
        self.min_token_per_char = min_token_per_char
        self.max_token_per_char = max_token_per_char
        self.min_length_chunk = min_length_chunk # in number of characters

    @cached_property
    def tokenizer(self) -> "Tokenizer":
        if not self.tokenizer_name_or_path:
            raise ValueError("self.tokenizer_name_or_path needs to be set!")
        tokenizer = load_tokenizer(self.tokenizer_name_or_path)
        return tokenizer
    
    def filter(self, doc: Document) -> bool | tuple[bool, str]:
        from datatrove.utils.text import split_into_chunks
        chunks = split_into_chunks(doc.text, min_length=self.min_length_chunk)

        encoded_chunks = self.tokenizer.encode_batch(chunks)
        token_lengths = [len(encoded_chunk.ids) for encoded_chunk in encoded_chunks]

        kept_chunks = []
        doc.metadata["token_per_chars"] = []
        # doc.metadata["bad_chunks"] = []
        for chunk, token_length in zip(chunks, token_lengths):
            if len(chunk) == 0:
                token_per_char = float('inf')
            else:
                token_per_char = token_length / len(chunk)
            doc.metadata["token_per_chars"].append(token_per_char)
            if (token_per_char < self.min_token_per_char) or (token_per_char > self.max_token_per_char):
                # doc.metadata["bad_chunks"].append(chunk)
                # if (not kept_chunks) or (kept_chunks[-1] != "<<removed_chunk>>"):
                #     kept_chunks.append("<<removed_chunk>>")
                continue
            kept_chunks.append(chunk)
        doc.text = '\n'.join(kept_chunks)
        return True