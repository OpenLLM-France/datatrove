from datatrove.data import Document
from datatrove.pipeline.filters.base_filter import BaseFilter
from datatrove.pipeline.writers.disk_base import DiskWriter
import urllib.robotparser
import tldextract
from datatrove.io import get_datafolder
import orjson
from concurrent.futures import ThreadPoolExecutor
from tqdm import tqdm

def read_robots_file(file):
    robots_dict = {}
    for line in file:
        data = orjson.loads(line)
        fqdn = tldextract.extract(data['metadata']["url"]).fqdn
        robots_dict[fqdn] = data["text"]
    return robots_dict

class RobotsTxtFilter(BaseFilter):
    name = "🤖🚫 Check robots.txt"

    def __init__(
        self,
        robots_txt_path: str | None = None,
        exclusion_writer: DiskWriter = None,
    ):
        super().__init__(exclusion_writer)
        self.robots_txt_dict = {}
        if robots_txt_path:
            self.robots_txt_dict = self.load_robots_txt(robots_txt_path)

    def load_robots_txt(self, robots_txt_path: str) -> dict[str, str]:
        """Load robots.txt rules from a folder into a dict keyed by FQDN."""
        data_folder = get_datafolder(robots_txt_path)
        files = data_folder.list_files(glob_pattern="*.jsonl.gz")
        with ThreadPoolExecutor() as pool:
            file_objs = data_folder.open_files(files, mode="rt", compression="gzip")
            results = list(
                tqdm(
                    pool.map(read_robots_file, file_objs),
                    total=len(files),
                    desc="Loading robots.txt",
                )
            )

        robots_dict = {}
        for d in results:
            for fqdn, text in d.items():
                if fqdn not in robots_dict:  # or simply: robots_dict[fqdn] = text for "last wins"
                    robots_dict[fqdn] = text
        return robots_dict

    def filter(self, doc: Document) -> bool:
        # Initialize the robot parser
        url = doc.metadata['url']
        fqdn = tldextract.extract(url).fqdn
        # Find the robots.txt
        robots_txt = self.robots_txt_dict.get(fqdn, None)

        if robots_txt is None:
            return False, "robots_txt_not_found"
        
        rp = urllib.robotparser.RobotFileParser()
        rp.parse(robots_txt.splitlines())
        can_fetch = rp.can_fetch("CCBot", url)

        if not can_fetch:
            return False, 'robots_txt_disallow'
        else:
            return True