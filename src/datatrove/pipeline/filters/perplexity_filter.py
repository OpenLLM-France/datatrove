from datatrove.data import Document
from datatrove.utils.perplexity import KenlmModel

from datatrove.data import Document
from datatrove.pipeline.filters.base_filter import BaseFilter
from datatrove.pipeline.writers.disk_base import DiskWriter

class PerplexityFilter(BaseFilter):
    name = "🙊 CCNet perplexity filter"
    _requires_dependencies = ["kenlm"]

    def __init__(
        self,
        language: str | None = "en",
        model_dataset: str = "wikipedia",
        min_ppl: float = 10.,
        max_ppl: float = 1000.,
        exclusion_writer: DiskWriter = None,
        label_only: bool = False,
        language_from_metadata: bool = False,
        use_ccnet=False,
    ) -> None:
        super().__init__(exclusion_writer)
        self.label_only = label_only
        self.min_ppl = min_ppl
        self.max_ppl = max_ppl
        self.model_dataset = model_dataset
        self.language = language
        self.language_from_metadata = language_from_metadata
        self.use_ccnet = use_ccnet
        self._models = {}  # key = language

    def get_model(self, language: str) -> KenlmModel:
        if language not in self._models:
            self._models[language] = KenlmModel(
                model_dataset=self.model_dataset,
                language=language,
                ccnet=self.use_ccnet,
            )
        return self._models[language]

    def filter(self, doc: Document) -> bool | tuple[bool, str]:
        # Get language
        if self.language_from_metadata:
            language = doc.metadata.get("language")
        else:
            language = self.language 
        # Apply perplexity if possible
        model = self.get_model(language)
        try:
            ppl = model.get_perplexity(doc.text)
            doc.metadata["ccnet_perplexity"] = ppl
        except Exception as e:
            self._models[language] = None
            doc.metadata["ccnet_perplexity"] = None
            return True
        # Filter based on perplexity
        if self.label_only:
            return True
        if ppl < self.min_ppl:
            return False, 'too_low_ppl'
        if ppl > self.max_ppl:
            return False, 'too_high_ppl'
        return True