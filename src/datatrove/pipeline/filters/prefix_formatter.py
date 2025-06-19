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
        date_format: str = "%Y-%m-%dT%H:%M:%SZ",
        infer_date_format = False,
        additionnal_formatting = None, 
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
        self.additionnal_formatting = additionnal_formatting
        self.add_prefix = add_prefix

    def process_metadata(self, doc):
        def find_key(doc, keys):
            value = None
            for key in keys:
                value = doc.metadata.get(key)
                if value:
                    break
            return value
        infos = []
        # Domain
        if self.url_keys:
            url = find_key(doc, self.url_keys)
            if url:
                try:
                    import tldextract
                    fqdn = tldextract.extract(url).fqdn
                    infos.append(f"Domain: {fqdn}")
                except Exception as e:
                    pass
        # Date
        if self.date_keys:
            raw_date = find_key(doc, self.date_keys)
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
                    infos.append(f"Date: {formatted_date}")
                except (ValueError, TypeError) as e:
                    pass
        return infos

    def filter(self, doc: Document) -> bool:
        infos = self.process_metadata(doc)
        if self.additionnal_formatting:
            add_infos = self.additionnal_formatting(doc)
            infos += add_infos
        prefix = "\n".join(infos)
        if prefix != "":
            prefix += "\n---\n\n"
            doc.metadata["prefix"] = prefix
            if self.add_prefix:
                doc.text = prefix + doc.text.strip()
        return True