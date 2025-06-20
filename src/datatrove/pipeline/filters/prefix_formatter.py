from datatrove.pipeline.filters.base_filter import BaseFilter
from datatrove.pipeline.writers.disk_base import DiskWriter
from datatrove.data import Document

class PrefixFormatter(BaseFilter):
    name = "🕰️ Add Prefix"

    def __init__(
        self,
        exclusion_writer: DiskWriter | None = None,
        language: str = "en",
        url_keys: str | list[str] = "url",
        date_keys: str | list[str] = "date",
        infer_date_format = False,
        date_format: str = "%Y-%m-%dT%H:%M:%SZ",
        additionnal_formatting = None, 
        prefix_pipeline: dict = {"fqdn": "Full domain", "date": "Date"}, 
        add_prefix = True,
    ):
        super().__init__(exclusion_writer)
        self.language = language
        if isinstance(url_keys, str):
            url_keys = [url_keys]
        self.url_keys = url_keys
        if isinstance(date_keys, str):
            date_keys = [date_keys]
        self.date_keys = date_keys
        self.date_format = date_format
        self.infer_date_format = infer_date_format
        self.additionnal_formatting = additionnal_formatting # function that return a dict like extract_url
        self.prefix_pipeline = prefix_pipeline
        self.add_prefix = add_prefix

    @staticmethod
    def find_key(doc, keys): # Iterate along keys and return the first non-empty value
        value = None
        for key in keys:
            value = doc.metadata.get(key)
            if value:
                break
        return value

    def extract_url(self, doc):
        url = self.find_key(doc, self.url_keys)
        if url:
            try:
                import tldextract
                extracted = tldextract.extract(url)
                return {"fqdn": extracted.fqdn, "domain": extracted.domain, "subdomain": extracted.subdomain, "suffix": extracted.suffix}
            except Exception as e:
                pass
        return {}
    
    def extract_date(self, doc):
        raw_date = self.find_key(doc, self.date_keys)
        if raw_date:
            try:
                from datetime import datetime
                from dateutil import parser
                raw_date = str(raw_date)
                if self.infer_date_format:
                    dt = parser.parse(raw_date)
                else:
                    dt = datetime.strptime(raw_date, self.date_format)
                formatted_date = dt.strftime("%Y-%m-%d")
                return {"date": formatted_date}
            except (ValueError, TypeError) as e:
                pass
        return {}

    def filter(self, doc: Document) -> bool:
        # Process all infos
        infos = self.extract_date(doc) | self.extract_url(doc)
        if self.additionnal_formatting:
            add_infos = self.additionnal_formatting(doc)
            infos = infos | add_infos
        
        # Construct prefix
        prefix = []
        for step_key, step_str in self.prefix_pipeline.items():
            value = infos.get(step_key)
            if value:
                prefix.append(f"{step_str}: {value}  ")
        prefix = "\n".join(prefix)

        # Add prefix
        if prefix != "":
            prefix += "\n\n---\n\n"
            doc.metadata["prefix"] = prefix
            if self.add_prefix:
                doc.text = prefix + doc.text.strip()
        return True