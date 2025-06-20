from datatrove.pipeline.writers.disk_base import DiskWriter
from datatrove.data import Document
from datatrove.pipeline.filters.base_filter import BaseFilter
from functools import cached_property
import os
from datatrove.utils.text import SPLIT_TEXT_DOCUMENTS, split_into_parts, split_into_chunks

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
        filter_mode: str = SPLIT_TEXT_DOCUMENTS,
        label_only = False,
    ):
        super().__init__(exclusion_writer)
        self.tokenizer_name_or_path = tokenizer_name_or_path
        if label_only:
            min_token_per_char = 0.
            max_token_per_char = float("inf")
        self.min_token_per_char = min_token_per_char
        self.max_token_per_char = max_token_per_char
        self.min_length_chunk = min_length_chunk # in number of characters
        self.filter_mode = filter_mode

    @cached_property
    def tokenizer(self) -> "Tokenizer":
        if not self.tokenizer_name_or_path:
            raise ValueError("self.tokenizer_name_or_path needs to be set!")
        tokenizer = load_tokenizer(self.tokenizer_name_or_path)
        return tokenizer
    
    def filter(self, doc: Document) -> bool | tuple[bool, str]:
        units = split_into_parts(doc.text, mode=self.filter_mode)
        encoded_chunks = self.tokenizer.encode_batch(units)
        token_lengths = [len(encoded_chunk.ids) for encoded_chunk in encoded_chunks]

        kept_spans = []
        doc.metadata["token_per_chars"] = []
        for unit, token_length in zip(units, token_lengths):
            if len(unit) == 0:
                token_per_char = float('inf')
            else:
                token_per_char = token_length / len(unit)
            doc.metadata["token_per_chars"].append(token_per_char)
            if self.min_token_per_char < token_per_char < self.max_token_per_char:
                kept_spans.append(unit)
                self.stat_update("kept_span")
            if (token_per_char < self.min_token_per_char) or (token_per_char > self.max_token_per_char):
                self.stat_update("removed_span")
        clean_text = "".join(kept_spans)
        if clean_text.strip() == "":
            return False
        else:
            doc.text = clean_text
            return True