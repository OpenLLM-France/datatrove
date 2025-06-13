from datatrove.data import Document
from datatrove.pipeline.filters.base_filter import BaseFilter
from datatrove.pipeline.writers.disk_base import DiskWriter
import re

MATH_KEYWORDS = [
    'MathJax',
    'mathjax',
    '<math',
    'math-container',
    'katex.min.css',
    'latex.php',
    'codecogs',
    'tex.cgi',
    'class="tex"',
    "class='tex'",
]

LATEX_MATH_COMMANDS = [
    "\\end", "\\begin", "\\ref", "\\frac", "\\label", "\\bf", "\\right", "\\left",
    "\\rm", "\\alpha", "\\mu", "\\def", "\\it", "\\pi", "\\sigma", "\\sum", "\\lambda",
    "\\beta", "\\nu", "\\partial", "\\int", "\\delta", "\\rho", "\\phi", "\\gamma",
    "\\omega", "\\over", "\\nonumber", "\\bar", "\\sqrt", "\\theta", "\\tau", "\\em",
    "\\rangle", "\\hat", "\\tilde", "\\cal", "\\hline", "\\item", "\\psi", "\\vec",
    "\\langle", "\\epsilon", "\\eta", "\\cdot", "\\in", "\\xi", "\\infty", "\\quad",
    "\\mathcal", "\\times", "\\emph", "\\mathbf", "\\prime", "\\be", "\\mathrm", "\\ee",
    "\\vspace", "\\pm", "\\chi", "\\ell", "\\text", "\\qquad", "\\noindent", "\\to",
    "\\varphi", "\\hspace", "\\leq", "\\cos", "\\eqref", "\\overline", "\\sin", "\\kappa",
    "\\hbox", "\\rightarrow", "\\varepsilon", "\\textit", "\\dagger", "\\big", "\\otimes",
    "\\equiv", "\\zeta", "\\dot", "\\ln"
]

class OpenWebMathFilter(BaseFilter):
    name = "💡 Open Web Math Filter"

    def __init__(
        self,
        exclusion_writer: DiskWriter = None,  
    ):
        super().__init__(exclusion_writer)

        self.original_regex = re.compile('|'.join(MATH_KEYWORDS))
        self.latex_regex = re.compile('\\\\[a-z]{2,}')
        self.latex_math_commands = LATEX_MATH_COMMANDS

    def filter(self, doc: Document) -> bool | tuple[bool, str]:
        from resiliparse.parse.html import HTMLTree
        from resiliparse.extract.html2text import extract_plain_text
        data = doc.text
        if data is None or data == "":
            return False, "no_text"
        original_match = self.original_regex.search(data)
        doc.metadata["has_math"] = original_match is not None
        if original_match:
            return True
        latex_match = self.latex_regex.search(data)
        doc.metadata["has_latex"] = latex_match is not None
        doc.metadata["has_latex_math_commands"] = False
        text = ''
        if latex_match:
            data = data.replace('<template', '<div')
            data = data.replace('</template', '</div')
            tree = HTMLTree.parse(data)
            text = extract_plain_text(tree, 
                                    main_content=True, 
                                    alt_texts=False)
            for term in self.latex_math_commands:
                if term in text:
                    doc.metadata["has_latex_math_commands"] = True
                    return True
        return False, "no_math"