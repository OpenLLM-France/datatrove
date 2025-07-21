from datatrove.pipeline.writers.disk_base import DiskWriter
from datatrove.data import Document
from datatrove.pipeline.filters.base_filter import BaseFilter
from functools import cached_property
import os
from datatrove.utils.text import SPLIT_TEXT_DOCUMENTS, split_into_parts
import re
from loguru import logger
from typing import List, Tuple

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
        max_token_per_char: float = 0.38,
        mode: str = "CHUNKS",
        separator: str = " ",
        min_length: int = 1000,
        max_length: int = None,
        replace_span: str = "\n\n[...]\n\n",
        removed_spans_in_metadata: bool = False, # For debugging only
        threshold_removal: float = 0.5,
        label_only: bool = False,
        normalize_digits: bool = False,
        batch_size: int = 1,
    ):
        super().__init__(exclusion_writer, batch_size)
        self.tokenizer_name_or_path = tokenizer_name_or_path
        if label_only:
            max_token_per_char = float("inf")
        self.max_token_per_char = max_token_per_char
        self.replace_span = replace_span
        self.removed_spans_in_metadata = removed_spans_in_metadata
        self.threshold_removal = threshold_removal
        self.normalize_digits = normalize_digits
        self.mode = mode
        self.separator = separator
        self.min_length = min_length
        self.max_length = max_length

    @cached_property
    def tokenizer(self) -> "Tokenizer":
        if not self.tokenizer_name_or_path:
            raise ValueError("self.tokenizer_name_or_path needs to be set!")
        tokenizer = load_tokenizer(self.tokenizer_name_or_path)
        return tokenizer
    
    def filter(self, doc: Document, token_counts=None) -> bool | tuple[bool, str]:
        doc.text = doc.text.strip()
        if not doc.text:
            return False, "empty_text"
        units = split_into_parts(doc.text, self.mode, self.separator, self.min_length, self.max_length)

        if token_counts is None:
            norm_units = [self._normalize_digits(unit) for unit in units]
            encoded_chunks = self.tokenizer.encode_batch(norm_units)
            token_counts = [len(encoded_chunk.ids) for encoded_chunk in encoded_chunks]
        doc.metadata["token_counts"] = token_counts

        kept_spans = []
        removed_spans = []
        doc.metadata["char_counts"] = []
        doc.metadata["token_per_chars"] = []
        for unit, token_count in zip(units, token_counts):
            if not len(unit):
                continue
            # Calculate metric
            length = len(unit)
            token_per_char = token_count / length
            doc.metadata["char_counts"].append(length)
            doc.metadata["token_per_chars"].append(token_per_char)
            # Filter
            if token_per_char < self.max_token_per_char:
                kept_spans.append(unit)
                self.stat_update("kept_span")
            else:
                kept_spans.append("<<removed_span>>")
                self.stat_update("removed_span")
                removed_spans.append(unit)

        clean_text = "".join(kept_spans)
        if self.removed_spans_in_metadata:
            doc.metadata['removed_spans'] = removed_spans
        doc.metadata['num_removed_spans'] = len(removed_spans)

        if 1 - len(clean_text)/len(doc.text) >= self.threshold_removal:
            return False, "too_much_removed_span"
        else:
            doc.text = re.sub(r'(<<removed_span>>\s*)+', self.replace_span, clean_text).strip()
            return True
        
    def filter_batch(self, batch: List[Document]) -> List[bool | Tuple[bool, str]]:
        if self.batch_size == 1:
            return list(map(self.filter, batch))
        if self.batch_size > 1 and self.mode != SPLIT_TEXT_DOCUMENTS:
            logger.warning(f"{self.batch_size=} > 1 only implemented for DOCUMENT split")
            return list(map(self.filter, batch))
        else:
            results = []
            encoded_texts = self.tokenizer.encode_batch([self._normalize_digits(doc.text.strip()) for doc in batch])
            token_counts = [len(encoded_text.ids) for encoded_text in encoded_texts]

            for doc, token_count in zip(batch, token_counts):
                result = self.filter(doc, [token_count])
                results.append(result)
            return results

    def _normalize_digits(self, text):
        if self.normalize_digits:
            return re.sub(r'\d+', '0', text)
        else:
            return text