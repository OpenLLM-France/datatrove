from datatrove.data import Document
from datatrove.pipeline.filters.base_filter import BaseFilter
from datatrove.pipeline.writers.disk_base import DiskWriter
import urllib.robotparser
import tldextract
from glob import glob
import gzip
import json
from typing import List, Dict, Any
from tqdm import tqdm
import os

class RobotsTxtFilter(BaseFilter):
    name = "🤖🚫 Check robots.txt"

    def __init__(
        self,
        robots_txt_path: str | None = None,
        exclusion_writer: DiskWriter = None,
    ):
        super().__init__(exclusion_writer)
        self.robots_txt_path = robots_txt_path
        assert self.robots_txt_path.endswith('.jsonl'), "robots_txt_path should be a .jsonl"
        self.robots_txt_dict = None

    def load_robots_txt(self) -> dict[str, str]:
        data = {}
        with open(self.robots_txt_path, 'r', encoding='utf-8') as f:
            for line in f:
                info = json.loads(line)
                data[info["fqdn"]] = info["text"]
        return data

    def get_robots_txt_dict(self):
        if self.robots_txt_dict is None:
            self.robots_txt_dict = self.load_robots_txt()
        return self.robots_txt_dict 

    def filter(self, doc: Document) -> bool:
        # Initialize the robot parser
        url = doc.metadata['url']
        fqdn = tldextract.extract(url).fqdn
        # Find the robots.txt
        robots_txt = self.get_robots_txt_dict().get(fqdn, None)

        if robots_txt is None:
            return False, "robots_txt_not_found"
        
        rp = urllib.robotparser.RobotFileParser()
        rp.parse(robots_txt.splitlines())
        can_fetch = rp.can_fetch("CCBot", url)

        if not can_fetch:
            return False, 'robots_txt_disallow'
        else:
            return True