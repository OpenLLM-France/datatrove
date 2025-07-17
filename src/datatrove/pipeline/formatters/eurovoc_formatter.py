from .base import BaseFormatter

import re

_cid_correction_double = {
    5: "ti",
    133: "fi",
    309: "tz",
    415: "ti",
    427: "tt",
}

_cid_correction = {
    106: None,
    107: None,
    108: ord("m"),
    109: None,
    116: ord("q"),
    113: None,
    121: None,
    128: None,
    133: None,
    149: None,
    159: None,
    160: None,
    173: None,
    #
    21: ord("ā"),
    23: ord("z"),
    25: ord("ţ"),
    127: 232,  # è
    129: 252,  # ü
    130: 233,  # é
    131: 226,  # â
    132: 228,  # ä
    134: 229,  # å
    135: 231,  # ç
    136: 234,  # ê
    137: 101,  # e
    138: 232,  # è
    139: 239,  # ï
    140: 238,  # î
    144: 233,  # é
    145: 225,  # á
    146: 237,  # í
    147: 244,  # ô
    148: 246,  # ö
    141: ord("-"),
    150: ord("-"),
    151: ord("-"),
    152: ord("~"),
    155: 243,  # ó
    156: 250,  # ú
    157: 241,  # ñ
    #
    142: 196,  # Ä
    143: 197,  # Å
    153: 214,  # Ö
    154: 220,  # Ü
    158: 209,  # Ñ
    190: ord("ü"),
    217: ord(" "),
    296: ord("ź"),
    298: ord("t"),
    321: ord("o"),
    367: ord("l"),
    371: ord("ł"),
    373: ord("m"),
    374: ord("n"),
    375: ord("n"),
    378: ord("o"),
    381: ord("o"),
    383: ord("o"),
    393: ord("p"),
    395: ord("q"),
    396: ord("r"),
    400: ord("s"),
    404: ord("s"),
    407: ord("a"),
    410: ord("t"),
    417: ord("i"),  # u?
    425: ord("t"),
    431: ord("i"),
    437: ord("u"),
    448: ord("v"),
}

def _repair_cid_character(match):
    i = int(match.group(2))

    if i in _cid_correction_double:
        replacement = _cid_correction_double[i]
        if (
            not match.group(1)
            or not match.group(1)[-1].islower()
            or not match.group(3)
            or not match.group(3)[0].islower()
        ):
            replacement = " "
        j = None
    else:
        j = _cid_correction.get(i, i)
        if j is not None and (i <= 100 or i > 300):
            j = None
        if j is None:
            replacement = " "
        else:
            replacement = chr(j)
    if replacement.islower():
        if not match.group(1):
            if match.group(3) and match.group(3)[0].isupper():
                replacement = " "
            elif replacement not in ["-"] and match.group(3) and match.group(3)[0].isdigit():
                replacement = " "
        elif match.group(1).isupper() and match.group(3).isupper():
            if i in [144]:
                replacement = replacement.upper()
            else:
                replacement = " "
    elif replacement.isupper():
        if not match.group(1):
            if match.group(3) and match.group(3)[0].islower():
                replacement = " "
            elif replacement not in ["-"] and match.group(3) and match.group(3)[0].isdigit():
                replacement = " "
        elif match.group(1).islower() and match.group(3).islower():
            replacement = " "
    converted = match.group(1) + replacement + match.group(3)
    if j and j < 176 and j not in _cid_correction.values():
        if not match.group(1) or not match.group(3):
            return match.group(1) + match.group(3)
    if i in [152]:
        converted = (
            converted.replace("a~", "ã")
            .replace("n~", "ñ")
            .replace("o~", "õ")
            .replace("A~", "Ã")
            .replace("N~", "Ñ")
            .replace("O~", "Õ")
        )
    return converted

class EurovocFormatter(BaseFormatter):
    """
    General approach: fixing unreadable/wrong encoding text is good. Enforcing a specific/strict formatting isn't.
    We want models to be able to recognize a wide variety of characters and formats, and not have a bunch of
    unseen tokens because of strict normalization.
    """

    name = "Eurovoc"

    def __init__(
        self,
    ):
        super().__init__()

    def format(self, text: str) -> str:
        text = re.sub(r" \(cid:1\)", "", text)
        text = re.sub(r"(\w*)\(cid:(\d+)\)(\w*)", _repair_cid_character, text)
        # text = re.sub(r"\f", "", text) # should we remove those control characters?
        return re.sub(r" +", " ", text)