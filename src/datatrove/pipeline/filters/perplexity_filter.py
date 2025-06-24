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
        language_from_metadata = False,
        model_dataset: str = "wikipedia",
        min_ppl: float = 10.,
        max_ppl: float = 1000.,
        exclusion_writer: DiskWriter = None,
        label_only: bool = False,
    ) -> None:
        super().__init__(exclusion_writer)
        self.label_only = label_only
        self.min_ppl = min_ppl
        self.max_ppl = max_ppl
        self.language_from_metadata = language_from_metadata

        if self.language_from_metadata:
            self.models = {}
            for language in ["en", "fr", "es", "ar", "pt"]:
                self.models[language] = KenlmModel(model_dataset=model_dataset, language=language)
        else:
            self.model = KenlmModel(model_dataset=model_dataset, language=language)

    def filter(self, doc: Document) -> bool:
        if self.language_from_metadata:
            language = doc.metadata.get("language", None)
            model = self.models.get(language, None)
            if model:
                ppl = self.models[language].get_perplexity(doc.text)
            else:
                return True
        else:
            model = self.model
            ppl = model.get_perplexity(doc.text)
        doc.metadata[f"ccnet_perplexity_{model.language}"] = ppl

        if self.label_only:
            return True
        
        if ppl < self.min_ppl:
            return False, 'too_low_ppl'
        
        if ppl > self.max_ppl:
            return False, 'too_high_ppl'
        
        return True