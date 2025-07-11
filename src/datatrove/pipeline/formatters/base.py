from abc import ABC, abstractmethod

from datatrove.data import DocumentsPipeline
from datatrove.pipeline.base import PipelineStep
from datatrove.utils.typeshelper import StatHints
from typing import Union, Tuple, Any


class BaseFormatter(PipelineStep, ABC):
    type = "✂️ - FORMAT"

    def __init__(self):
        super().__init__()

    @abstractmethod
    def format(self, text: str) -> Union[str, Tuple[str, Any]]:
        """
        Return either the formatted text or a tuple of (text, metadata).
        """
        pass

    def run(self, data: DocumentsPipeline, rank: int = 0, world_size: int = 1) -> DocumentsPipeline:
        for doc in data:
            self.stat_update(StatHints.total)
            with self.track_time():
                doc.text = self.format(doc.text)
            yield doc

    def run(self, data: DocumentsPipeline, rank: int = 0, world_size: int = 1) -> DocumentsPipeline:
        for doc in data:
            self.stat_update(StatHints.total)
            with self.track_time():
                result = self.format(doc.text)
                if isinstance(result, tuple):
                    doc.text, metadata = result
                    doc.metadata.update(metadata)
                else:
                    doc.text = result
            yield doc