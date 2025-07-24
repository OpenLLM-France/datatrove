from datatrove.data import Document
from datatrove.pipeline.filters.base_filter import BaseFilter
from datatrove.pipeline.writers.disk_base import DiskWriter
from datatrove.pipeline.base import PipelineStep
from datatrove.data import DocumentsPipeline
import urllib.robotparser
import tldextract
import json
import os
from collections import Counter

class RobotsTxtReducer(PipelineStep):
    def __init__(self, robots_txt_path: str, output_path: str):
        super().__init__()
        self.robots_txt_path = robots_txt_path
        self.output_path = output_path
        self.tld_extractor = tldextract.TLDExtract()

    def run(self, data: DocumentsPipeline, rank: int = 0, world_size: int = 1) -> DocumentsPipeline:
        fqdn_counter = Counter()
        for doc in data:
            with self.track_time():
                url = doc.metadata['url']
                fqdn = self.tld_extractor(url).fqdn
                fqdn_counter[fqdn] += 1
            yield doc

        os.makedirs(self.output_path, exist_ok=True)
        with open(os.path.join(self.robots_txt_path, "robotstxt_dict.jsonl"), "r", encoding="utf-8") as fin, \
             open(os.path.join(self.output_path, "robotstxt_dict.jsonl"), "w", encoding="utf-8") as fout:
            for line in fin:
                entry = json.loads(line)
                if entry["fqdn"] in fqdn_counter:
                    fout.write(json.dumps(entry) + "\n")

class RobotsTxtFilter(BaseFilter):
    name = "🤖🚫 Check robots.txt"

    def __init__(
        self,
        robots_txt_path: str | None = None,
        exclusion_writer: DiskWriter = None,
    ):
        super().__init__(exclusion_writer)
        self.robots_txt_path = robots_txt_path
        self.robots_txt_dict = None
        self.tld_extractor = tldextract.TLDExtract()

    def load_robots_txt(self) -> dict[str, str]:
        data = {}
        with open(os.path.join(self.robots_txt_path, "robotstxt_dict.jsonl"), 'r', encoding='utf-8') as f:
            for line in f:
                info = json.loads(line)
                data[info["fqdn"]] = info["text"]
        return data

    def get_robots_txt_dict(self):
        if self.robots_txt_dict is None:
            self.robots_txt_dict = self.load_robots_txt()
        return self.robots_txt_dict 

    def filter(self, doc: Document) -> bool:
        # Extract fdn
        url = doc.metadata['url']
        fqdn = self.tld_extractor(url).fqdn
        # Find the robots.txt
        robots_txt = self.get_robots_txt_dict().get(fqdn, None)

        if robots_txt is None:
            return False, "robots_txt_not_found"
        
        # Initialize the robot parser
        rp = urllib.robotparser.RobotFileParser()
        rp.parse(robots_txt.splitlines())
        can_fetch = rp.can_fetch("CCBot", url)

        if not can_fetch:
            return False, 'robots_txt_disallow'
        else:
            return True