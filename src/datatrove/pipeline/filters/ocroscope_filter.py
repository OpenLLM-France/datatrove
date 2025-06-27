from datatrove.data import Document
from datatrove.pipeline.filters.base_filter import BaseFilter
from datatrove.pipeline.writers.disk_base import DiskWriter
from ocroscope import ocr_evaluation
import regex

class OCRoscopeFilter(BaseFilter):
    name = "🔭 OCRoscope"
    RE_BAD_CHARS = regex.compile(r"[\p{Cc}\p{Cs}\p{Cn}]+")

    def __init__(
        self, 
        ocr_threshold: int = 80, 
        exclusion_writer: DiskWriter = None
        ):
        super().__init__(exclusion_writer)
        self.ocr_threshold = ocr_threshold

    def filter(self, doc: Document) -> bool:
        # see https://github.com/aboSamoor/polyglot/issues/71#issuecomment-707997790
        def remove_bad_chars(text):
            return self.RE_BAD_CHARS.sub("", text)
        text = remove_bad_chars(doc.text)
        # see https://github.com/Pleias/OCRoscope?tab=readme-ov-file
        ocr_estimate = ocr_evaluation(id = doc.id, text = text)
        ocr_estimate.calculate_ocr_rate()
        ocr_quality, nonchar = ocr_estimate.ratio_segment, ocr_estimate.ratio_nonchar
        doc.metadata['ocr_quality'] = ocr_quality
        doc.metadata['nonchar'] = nonchar
        if ocr_quality is None or ocr_quality < 80:
            return False, "ocr_quality"
        return True