import random
from lxml import html
from prettytable import PrettyTable
from .latex_parsing import extract_plain_text, improve_latex_content_parsing
from .base import BaseExtractor

def html_table_to_ascii(headers, rows):
    ascii_table = PrettyTable()
    if headers:
        ascii_table.field_names = headers
    else:
        raise ValueError("Headers cannot be empty when using PrettyTable.")

    for row in rows:
        # check if row is empty, and ensure the number of columns is consistent
        if row and len(row) != len(headers):
            raise ValueError(
                f"Row has incorrect number of values: {len(row)} != {len(headers)}"
            )
        ascii_table.add_row(row)

    return ascii_table.get_string()


def html_table_to_markdown(headers, rows):
    markdown_table = []
    if headers:
        markdown_table.append("| " + " | ".join(headers) + " |")
        markdown_table.append("| " + " | ".join(["---"] * len(headers)) + " |")
    for row in rows:
        if row and any(cell.strip() for cell in row):  # 确保行不是空的
            formatted_row = [cell.replace("\n", " ").strip() for cell in row]
            markdown_table.append("| " + " | ".join(formatted_row) + " |")
    return "\n".join(markdown_table)


def random_table_converter(table_element, format_choice=None):
    format_choice = format_choice or random.choice(["ascii", "markdown"])
    headers = [th.text_content().strip() for th in table_element.xpath(".//th")] or []
    rows = [
        [td.text_content().strip() for td in tr.xpath(".//td")]
        for tr in table_element.xpath(".//tr")
        if tr.xpath(".//td")
    ]
    if format_choice == "ascii":
        return html_table_to_ascii(headers, rows)
    else:
        return html_table_to_markdown(headers, rows)


def process_tables(tree, format_choice=None):
    if not isinstance(tree, html.HtmlElement):
        raise TypeError("Expected an lxml.html.HtmlElement object")
    for table in tree.xpath("//table"):
        table_text = random_table_converter(table, format_choice=format_choice)
        new_element = html.Element("pre", attrib={"class": "converted-table"})
        new_element.text = f"\n{table_text}\n"
        table.getparent().replace(table, new_element)
    return tree

class MegamathExtractor(BaseExtractor):
    name = "⛏ Megamath Extractor"

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
        # ⚠️⚠️⚠️ reformat the html text by improving latex content rendering
        reformatted_html_doc = improve_latex_content_parsing(text)
        try:
            tree = html.fromstring(reformatted_html_doc)
            tree = process_tables(tree)
            reformatted_html_doc = html.tostring(
                tree, encoding="unicode", pretty_print=True
            )
        except Exception as e:
            # print(f"Raise an exception {e} when dealing with tables")
            pass

        # ⚠️⚠️⚠️ extract texts from the html documents
        result = extract_plain_text(
            reformatted_html_doc,
            alt_texts=False,
            links=False,
            preserve_formatting=True,
        )
        return result