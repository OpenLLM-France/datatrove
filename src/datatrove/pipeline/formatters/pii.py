import ipaddress
import re
from functools import partial
from typing import Callable

from datatrove.pipeline.formatters.base import BaseFormatter

import re
from typing import Callable

class PIIReplacer:
    def __init__(
        self,
        regex: str,
        replacements: tuple[str, ...] | str,
        validator: Callable[[str], bool] | None = None
    ):
        self.regex: re.Pattern = re.compile(regex)
        self.replacements = (
            replacements
            if isinstance(replacements, tuple)
            else (tuple(replacements) if not isinstance(replacements, str) else (replacements,))
        )
        self.validator = validator
        self._replace_i = 0

    def replace(self, text: str):
        matches = []

        def get_replacement(matchobj):
            match_text = matchobj.group(0)
            if self.validator and not self.validator(match_text):
                return match_text
            matches.append(match_text)
            replacement = self.replacements[self._replace_i]
            self._replace_i = (self._replace_i + 1) % len(self.replacements)
            return replacement

        new_text = self.regex.sub(get_replacement, text)
        return new_text, matches

def public_ip_validator(ip, public_only: bool = True) -> bool:
    pattern = r'^\d\.\d\.\d\.\d$'
    if re.match(pattern, ip):
        return False
    try:
        ip = ipaddress.ip_address(ip)
        return not public_only or ip.is_global
    except ValueError:
        return False


class PIIFormatter(BaseFormatter):
    """
    Replaces email addresses and ip addresses in the document text.
    Args:
        remove_emails: Replace email addresses
        remove_ips: Replace IP addresses
        only_remove_public_ips: by default we only replace public (and thus PII) IPs
        email_replacement: tuple of strings to use as replacement. They will be used in a circular way
        ip_replacement same as email_replacement but for IP addresses
    """

    name = "🥸  PII"

    def __init__(
        self,
        remove_emails: bool = True,
        remove_ips: bool = True,
        only_remove_public_ips: bool = True,
        # example.com/org are actually maintained as an example
        email_replacement: tuple[str, ...] | str = ("email@example.com", "firstname.lastname@example.org"),
        # randomly generated list of ips. they did not respond to ping requests at the time the list was created
        ip_replacement: tuple[str, ...] | str = (
            "22.214.171.124",
            "126.96.36.199",
            "188.8.131.52",
            "184.108.40.206",
            "220.127.116.11",
            "18.104.22.168",
        ),
    ):
        super().__init__()
        self.remove_emails = remove_emails
        self.remove_ips = remove_ips

        self.emails_replacer = PIIReplacer(
            r"\b[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+)*@(?:(?:[A-Za-z0-9](?:["
            r"A-Za-z0-9-]*[A-Za-z0-9])?\.)+[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?|\[(?:(?:25[0-5]|2[0-4][0-9]|["
            r"01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?|[A-Za-z0-9-]*[A-Za-z0-9]:)])",
            email_replacement,
        )

        self.ip_replacer = PIIReplacer(
            r"(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)",
            validator=partial(public_ip_validator, public_only=only_remove_public_ips),
            replacements=ip_replacement,
        )

    def format(self, text: str) -> str:
        metadata = {}
        if self.remove_emails:
            text, removed = self.emails_replacer.replace(text)
            if removed:
                metadata["pii_email"] = removed
            self.stat_update("pii_stats_email", value=len(removed))
        if self.remove_ips:
            text, removed = self.ip_replacer.replace(text)      
            if removed:
                metadata["pii_ip"] = removed   
            self.stat_update("pii_stats_ip", value=len(removed))
        return text, metadata

# Default per-country phone replacements, format-preserving: a number written
# in international form (leading "+" or IDD "00") is masked with the matching
class PhoneNumberPII(BaseFormatter):

    name = "🥸  Phone Number PII"

    """"
    This filter uses the phonenumbers library to find and replace phone numbers in the text.
    It also stores the original phone numbers in the metadata of the document.

    Example of country codes: "US", "GB", "FR", "DE", "IT", "ES", "PT", "NL"

    countries -- The country/countries to assume for phone numbers not written
      in international format (with a leading plus, or with the international
      dialing prefix of the specified region). May be None or "ZZ" if only
      numbers with a leading plus should be considered.

    mask_digits -- if True (default), mask each match in place: keep the
      international country-code prefix ("+33" / "0033") if the number was
      written internationally, replace every other digit with "x", and keep the
      original separators (spaces / dots / dashes / parentheses). A national
      number (no written country code) has all its digits masked. So
      "+33 6 11 22 33 44" -> "+33 x xx xx xx xx" and "06.12.34.56.78" ->
      "xx.xx.xx.xx.xx". When True, `replacement` is ignored.

    replacement -- used when mask_digits is False:
        - a str -> used verbatim for every match (e.g. "<PHONE_NUMBER>").
        - a list/tuple of str -> cycled through round-robin (like PIIFormatter's
          PIIReplacer), across all matches regardless of country.
    """

    def __init__(
        self,
        countries: str | list[str] = "US",
        replacement: str | tuple[str, ...] | list = "<PHONE_NUMBER>",
        mask_digits: bool = True,
    ):
        super().__init__()
        if isinstance(countries, str):
            countries = [countries]
        self.countries = countries
        self.mask_digits = mask_digits
        self.replacements = (replacement,) if isinstance(replacement, str) else tuple(replacement)
        self._replace_i = 0

    @staticmethod
    def _mask_digits(raw: str, country_code: int) -> str:
        """Keep a leading "+cc"/"00cc" prefix, x-out every other digit, keep separators."""
        prefix_match = re.match(r"(\+|00)\s*" + re.escape(str(country_code)), raw)
        cut = prefix_match.end() if prefix_match else 0
        return raw[:cut] + re.sub(r"\d", "x", raw[cut:])

    def format(self, text: str) -> str:
        import phonenumbers
        pii_phones = []
        for country in self.countries:
            matches = list(phonenumbers.PhoneNumberMatcher(text, country))
            for m in reversed(matches):
                pii_phones.append(m.raw_string)
                if self.mask_digits:
                    replacement = self._mask_digits(m.raw_string, m.number.country_code)
                else:
                    replacement = self.replacements[self._replace_i]
                    self._replace_i = (self._replace_i + 1) % len(self.replacements)
                text = text[:m.start] + replacement + text[m.end:]
        metadata = {}
        if pii_phones:
            metadata["pii_phone"] = pii_phones
            self.stat_update("pii_stats_phone", value=len(pii_phones))
        return text, metadata

class MorePIIFormatter(BaseFormatter):
    """
    Replaces NIR in the document text.
    Args:
    """

    name = "🥸  More PII"

    def __init__(
        self,
        remove_nir: bool = True,
        remove_url: bool = False,
        nir_replacement: str = "<<pii_nir>>",
        url_replacement: str = "<<url_link>>",
    ):
        super().__init__()
        self.remove_nir = remove_nir
        self.remove_url = remove_url

        BASE_URL_REGEX = r"((www\d{0,3}[.])?[a-z0-9.\-]+[.](?:(?:com)|(?:edu)|(?:gov)|(?:int)|(?:mil)|(?:net)|(?:onl)|(?:org)|(?:pro)|(?:red)|(?:tel)|(?:uno)|(?:xxx)|(?:academy)|(?:accountant)|(?:accountants)|(?:actor)|(?:adult)|(?:africa)|(?:agency)|(?:airforce)|(?:apartments)|(?:app)|(?:archi)|(?:army)|(?:art)|(?:asia)|(?:associates)|(?:attorney)|(?:auction)|(?:audio)|(?:auto)|(?:autos)|(?:baby)|(?:band)|(?:bar)|(?:bargains)|(?:beer)|(?:berlin)|(?:best)|(?:bet)|(?:bid)|(?:bike)|(?:bio)|(?:black)|(?:blackfriday)|(?:blog)|(?:blue)|(?:boats)|(?:bond)|(?:boo)|(?:boston)|(?:bot)|(?:boutique)|(?:build)|(?:builders)|(?:business)|(?:buzz)|(?:cab)|(?:cafe)|(?:cam)|(?:camera)|(?:camp)|(?:capital)|(?:car)|(?:cards)|(?:care)|(?:careers)|(?:cars)|(?:casa)|(?:cash)|(?:casino)|(?:catering)|(?:center)|(?:ceo)|(?:cfd)|(?:charity)|(?:chat)|(?:cheap)|(?:christmas)|(?:church)|(?:city)|(?:claims)|(?:cleaning)|(?:click)|(?:clinic)|(?:clothing)|(?:cloud)|(?:club)|(?:codes)|(?:coffee)|(?:college)|(?:com)|(?:community)|(?:company)|(?:computer)|(?:condos)|(?:construction)|(?:consulting)|(?:contact)|(?:contractors)|(?:cooking)|(?:cool)|(?:coupons)|(?:courses)|(?:credit)|(?:creditcard)|(?:cricket)|(?:cruises)|(?:cyou)|(?:dad)|(?:dance)|(?:date)|(?:dating)|(?:day)|(?:degree)|(?:delivery)|(?:democrat)|(?:dental)|(?:dentist)|(?:desi)|(?:design)|(?:dev)|(?:diamonds)|(?:diet)|(?:digital)|(?:direct)|(?:directory)|(?:discount)|(?:doctor)|(?:dog)|(?:domains)|(?:download)|(?:earth)|(?:eco)|(?:education)|(?:email)|(?:energy)|(?:engineer)|(?:engineering)|(?:enterprises)|(?:equipment)|(?:esq)|(?:estate)|(?:events)|(?:exchange)|(?:expert)|(?:exposed)|(?:express)|(?:fail)|(?:faith)|(?:family)|(?:fans)|(?:farm)|(?:fashion)|(?:feedback)|(?:film)|(?:finance)|(?:financial)|(?:fish)|(?:fishing)|(?:fit)|(?:fitness)|(?:flights)|(?:florist)|(?:flowers)|(?:football)|(?:forsale)|(?:foundation)|(?:fun)|(?:fund)|(?:furniture)|(?:futbol)|(?:fyi)|(?:gallery)|(?:game)|(?:games)|(?:garden)|(?:gay)|(?:gdn)|(?:gifts)|(?:gives)|(?:giving)|(?:glass)|(?:global)|(?:gmbh)|(?:gold)|(?:golf)|(?:graphics)|(?:gratis)|(?:green)|(?:gripe)|(?:group)|(?:guide)|(?:guitars)|(?:guru)|(?:hair)|(?:hamburg)|(?:haus)|(?:health)|(?:healthcare)|(?:help)|(?:hiphop)|(?:hockey)|(?:holdings)|(?:holiday)|(?:homes)|(?:horse)|(?:hospital)|(?:host)|(?:hosting)|(?:house)|(?:how)|(?:icu)|(?:info)|(?:ink)|(?:institute)|(?:insure)|(?:international)|(?:investments)|(?:irish)|(?:jewelry)|(?:jetzt)|(?:juegos)|(?:kaufen)|(?:kids)|(?:kitchen)|(?:kiwi)|(?:krd)|(?:kyoto)|(?:land)|(?:lat)|(?:law)|(?:lawyer)|(?:lease)|(?:legal)|(?:lgbt)|(?:life)|(?:lighting)|(?:limited)|(?:limo)|(?:link)|(?:live)|(?:loan)|(?:loans)|(?:lol)|(?:london)|(?:love)|(?:ltd)|(?:ltda)|(?:luxury)|(?:maison)|(?:management)|(?:market)|(?:marketing)|(?:markets)|(?:mba)|(?:media)|(?:melbourne)|(?:meme)|(?:memorial)|(?:men)|(?:miami)|(?:mobi)|(?:moda)|(?:moe)|(?:mom)|(?:money)|(?:monster)|(?:mortgage)|(?:motorcycles)|(?:mov)|(?:movie)|(?:nagoya)|(?:name)|(?:navy)|(?:network)|(?:new)|(?:news)|(?:ngo)|(?:ninja)|(?:now)|(?:nyc)|(?:observer)|(?:okinawa)|(?:one)|(?:ong)|(?:onl)|(?:online)|(?:organic)|(?:osaka)|(?:page)|(?:paris)|(?:partners)|(?:parts)|(?:party)|(?:pet)|(?:phd)|(?:photo)|(?:photography)|(?:photos)|(?:pics)|(?:pictures)|(?:pink)|(?:pizza)|(?:place)|(?:plumbing)|(?:plus)|(?:poker)|(?:porn)|(?:press)|(?:pro)|(?:productions)|(?:prof)|(?:promo)|(?:properties)|(?:property)|(?:protection)|(?:pub)|(?:quest)|(?:racing)|(?:recipes)|(?:red)|(?:rehab)|(?:reise)|(?:reisen)|(?:rent)|(?:rentals)|(?:repair)|(?:report)|(?:republican)|(?:rest)|(?:restaurant)|(?:review)|(?:reviews)|(?:rip)|(?:rocks)|(?:rodeo)|(?:rsvp)|(?:run)|(?:saarland)|(?:sale)|(?:salon)|(?:sarl)|(?:sbs)|(?:school)|(?:schule)|(?:science)|(?:services)|(?:sex)|(?:sexy)|(?:sh)|(?:shoes)|(?:shop)|(?:shopping)|(?:show)|(?:singles)|(?:site)|(?:skin)|(?:soccer)|(?:social)|(?:software)|(?:solar)|(?:solutions)|(?:soy)|(?:space)|(?:spiegel)|(?:study)|(?:style)|(?:sucks)|(?:supply)|(?:support)|(?:surf)|(?:surgery)|(?:systems)|(?:tax)|(?:taxi)|(?:team)|(?:tech)|(?:technology)|(?:tel)|(?:theater)|(?:tips)|(?:tires)|(?:today)|(?:tools)|(?:top)|(?:tours)|(?:town)|(?:toys)|(?:trade)|(?:training)|(?:tube)|(?:uk)|(?:university)|(?:uno)|(?:vacations)|(?:ventures)|(?:vet)|(?:video)|(?:villas)|(?:vin)|(?:vip)|(?:vision)|(?:vlaanderen)|(?:vodka)|(?:vote)|(?:voting)|(?:voyage)|(?:wales)|(?:wang)|(?:watch)|(?:webcam)|(?:website)|(?:wedding)|(?:wiki)|(?:wine)|(?:work)|(?:works)|(?:world)|(?:wtf)|(?:xyz)|(?:yoga)|(?:yokohama)|(?:you)|(?:zone)|(?:ac)|(?:ad)|(?:ae)|(?:af)|(?:ag)|(?:ai)|(?:al)|(?:am)|(?:an)|(?:ao)|(?:aq)|(?:ar)|(?:as)|(?:at)|(?:au)|(?:aw)|(?:ax)|(?:az)|(?:ba)|(?:bb)|(?:bd)|(?:be)|(?:bf)|(?:bg)|(?:bh)|(?:bi)|(?:bj)|(?:bm)|(?:bn)|(?:bo)|(?:br)|(?:bs)|(?:bt)|(?:bv)|(?:bw)|(?:by)|(?:bz)|(?:ca)|(?:cc)|(?:cd)|(?:cf)|(?:cg)|(?:ch)|(?:ci)|(?:ck)|(?:cl)|(?:cm)|(?:cn)|(?:co)|(?:cr)|(?:cu)|(?:cv)|(?:cw)|(?:cx)|(?:cy)|(?:cz)|(?:de)|(?:dj)|(?:dk)|(?:dm)|(?:do)|(?:dz)|(?:ec)|(?:ee)|(?:eg)|(?:er)|(?:es)|(?:et)|(?:eu)|(?:fi)|(?:fj)|(?:fk)|(?:fm)|(?:fo)|(?:fr)|(?:ga)|(?:gb)|(?:gd)|(?:ge)|(?:gf)|(?:gg)|(?:gh)|(?:gi)|(?:gl)|(?:gm)|(?:gn)|(?:gp)|(?:gq)|(?:gr)|(?:gs)|(?:gt)|(?:gu)|(?:gw)|(?:gy)|(?:hk)|(?:hm)|(?:hn)|(?:hr)|(?:ht)|(?:hu)|(?:id)|(?:ie)|(?:il)|(?:im)|(?:in)|(?:io)|(?:iq)|(?:ir)|(?:is)|(?:it)|(?:je)|(?:jm)|(?:jo)|(?:jp)|(?:ke)|(?:kg)|(?:kh)|(?:ki)|(?:km)|(?:kn)|(?:kp)|(?:kr)|(?:kw)|(?:ky)|(?:kz)|(?:la)|(?:lb)|(?:lc)|(?:li)|(?:lk)|(?:lr)|(?:ls)|(?:lt)|(?:lu)|(?:lv)|(?:ly)|(?:ma)|(?:mc)|(?:md)|(?:me)|(?:mg)|(?:mh)|(?:mk)|(?:ml)|(?:mm)|(?:mn)|(?:mo)|(?:mp)|(?:mq)|(?:mr)|(?:ms)|(?:mt)|(?:mu)|(?:mv)|(?:mw)|(?:mx)|(?:my)|(?:mz)|(?:na)|(?:nc)|(?:ne)|(?:nf)|(?:ng)|(?:ni)|(?:nl)|(?:no)|(?:np)|(?:nr)|(?:nu)|(?:nz)|(?:om)|(?:pa)|(?:pe)|(?:pf)|(?:pg)|(?:ph)|(?:pk)|(?:pl)|(?:pm)|(?:pn)|(?:pr)|(?:ps)|(?:pt)|(?:pw)|(?:py)|(?:qa)|(?:re)|(?:ro)|(?:rs)|(?:ru)|(?:rw)|(?:sa)|(?:sb)|(?:sc)|(?:sd)|(?:se)|(?:sg)|(?:sh)|(?:si)|(?:sj)|(?:sk)|(?:sl)|(?:sm)|(?:sn)|(?:so)|(?:sr)|(?:st)|(?:su)|(?:sv)|(?:sx)|(?:sy)|(?:sz)|(?:tc)|(?:td)|(?:tf)|(?:tg)|(?:th)|(?:tj)|(?:tk)|(?:tl)|(?:tm)|(?:tn)|(?:to)|(?:tp)|(?:tr)|(?:tt)|(?:tv)|(?:tw)|(?:tz)|(?:ua)|(?:ug)|(?:uk)|(?:us)|(?:uy)|(?:uz)|(?:va)|(?:vc)|(?:ve)|(?:vg)|(?:vi)|(?:vn)|(?:vu)|(?:wf)|(?:ws)|(?:ye)|(?:yt)|(?:za)|(?:zm)|(?:zw))(?:/[^\s()<>\"']*)?)"  # noqa: E501
        combined_regex = (
            r'(?i)(?:https?://' + BASE_URL_REGEX + r'|'
            + BASE_URL_REGEX + r'|'
            r'["\']https?://' + BASE_URL_REGEX + r'["\']|'
            r'["\']' + BASE_URL_REGEX + r'["\'])'
        )
        self.url_replacer = PIIReplacer(
            combined_regex,
            replacements=url_replacement,
        )
        self.nir_replacer = PIIReplacer(
            r"[12]\s?\d{2}\s?(0[1-9]|1[0-2]|[2-9][0-9])\s?([0-9]{2}|2A|2B)\s?\d{3}\s?\d{3}\s?\d{2}",
            replacements=nir_replacement,
        )

    def format(self, text: str) -> str:
        if self.remove_nir:
            text, removed = self.nir_replacer.replace(text)
            self.stat_update("pii_nir", value=len(removed))
        if self.remove_url:
            text, removed = self.url_replacer.replace(text)
            self.stat_update("pii_url", value=len(removed))
        return text