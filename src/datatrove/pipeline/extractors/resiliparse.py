from .base import BaseExtractor

class Resiliparse(BaseExtractor):
    """
    Resiliparse extractor
    """

    name = "⛏ Resiliparse"
    _requires_dependencies = ["resiliparse"]

    def __init__(
        self,
        timeout: float = 1,
    ):
        super().__init__(timeout)

    def extract(self, text: str) -> str:
        """
        Args:
          text: str: html content

        Returns: plain text extracted text
        """
        from resiliparse.parse.html import HTMLTree
        # from resiliparse.parse.encoding import bytes_to_str, detect_encoding
        from resiliparse.extract.html2text import extract_plain_text

        # # html_doc = bytes_to_str(data, detect_encoding(content_stream))
        tree = HTMLTree.parse(text)

        # ⚠️⚠️⚠️ extract texts from the html documents
        result = extract_plain_text(
            tree,
            alt_texts=False,
            links=False,
            preserve_formatting=True,
        )
        return result
