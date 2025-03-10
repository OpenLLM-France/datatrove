from datatrove.data import Document
from datatrove.pipeline.filters.base_filter import BaseFilter
from datatrove.pipeline.writers.disk_base import DiskWriter

import json
import urllib.robotparser
from urllib.parse import urlparse

def extract_domain(url):
    # Parse the URL
    parsed_url = urlparse(url)
    
    # Extract the domain (netloc) and return it
    return parsed_url.netloc

class CanFetchFilter(BaseFilter):
    name = "🚫 Can Fetch robots.txt"

    def __init__(
        self,
        robots_txt_path: str | None = None,
        exclusion_writer: DiskWriter = None,
    ):
        super().__init__(exclusion_writer)
        # Define an empty dictionary to store the data
        self.url_text_dict = {}

        # Open and read the JSONL file
        with open(robots_txt_path, "r", encoding="utf-8") as file:
            for line in file:
                data = json.loads(line.strip())  # Parse JSON
                url = data['metadata']['url']
                domain = extract_domain(url)
                self.url_text_dict[domain] = data["text"]  # Store in dictionary

    def filter(self, doc: Document) -> bool:
        # Initialize the robot parser
        url = doc.metadata['url']
        domain = extract_domain(url)
        # Find the robots.txt
        robots_txt = self.url_text_dict.get(domain, None)

        if robots_txt is None:
            return False, "no_robots_txt"
        
        rp = urllib.robotparser.RobotFileParser()
        
        # Feed the content to the parser
        rp.parse(robots_txt.splitlines())

        can_fetch = rp.can_fetch("CCBot", url)

        if not can_fetch:
            return False, 'cannot_fetch'
        else:
            return True