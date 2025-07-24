from datatrove.pipeline.base import PipelineStep
from datatrove.data import DocumentsPipeline
from tldextract import TLDExtract
from collections import Counter
import json
import os

class CountDomain(PipelineStep):
    def __init__(self, output_path):
        super().__init__()
        self.output_path = output_path
        self.tld_extractor = TLDExtract()

    def run(
        self, data: DocumentsPipeline, rank: int = 0, world_size: int = 1
    ) -> DocumentsPipeline:
        fqdn_counter = Counter()

        for doc in data:
            with self.track_time():
                fqdn = self.tld_extractor.extract_str(doc.metadata["url"]).fqdn
                fqdn_counter[fqdn] += 1
            yield doc

        os.makedirs(self.output_path, exist_ok=True)
        out_path = os.path.join(self.output_path, f"{rank:05d}.jsonl")

        with open(out_path, "w") as f:
            for fqdn, count in fqdn_counter.items():
                f.write(json.dumps({"fqdn": fqdn, "count": count}) + "\n")
