from .base import BaseExtractor

class Resiliparse(BaseExtractor):
    """
    Resiliparse extractor
    """

    name = "⛏ Resiliparse"
    _requires_dependencies = ["resiliparse"]

    def __init__(
        self,
        favour_precision: bool = True,
        include_images: bool = False,
        timeout: float = 1,
        deduplicate: bool = True,
        **kwargs,
    ):
        super().__init__(timeout)
        self.favour_precision = favour_precision
        self.include_images = include_images
        self.deduplicate = deduplicate
        self.kwargs = kwargs
        if self.include_images:
            raise NotImplementedError

    def extract(self, text: str) -> str:
        """

        Args:
          text: str: html content

        Returns: plain text extracted text

        """
        from resiliparse.extract.html2text import extract_plain_text

        # ⚠️⚠️⚠️ extract texts from the html documents
        return extract_plain_text(
            text,
            alt_texts=False,
            links=False,
            preserve_formatting=True,
        )