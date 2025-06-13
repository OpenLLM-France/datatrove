from .base import BaseExtractor
from text_extract.extract import extract_text
from text_extract.utils import Config

def extract(html, config):
    res = extract_text(html, config, fast=True)
    if res is None:
        return None
    text, info = res
    metadata = {
        'extraction_info': info,
        'config': config,
    }
    return text, metadata

class OpenWebMathExtractor(BaseExtractor):
    name = "⛏ OpenWebMathExtractor"

    def __init__(
        self,
        timeout: float = 1,
    ):
        super().__init__(timeout)
        self.randomized_config = Config("configs/randomized_all.yaml")


    def extract(self, text: str) -> str:
        """

        Args:
          text: str: html content

        Returns: plain text extracted text

        """
        randomized_config_sample = self.randomized_config.sample()
        res = extract(text, randomized_config_sample)
        randomized_text, metadata = res
        return randomized_text