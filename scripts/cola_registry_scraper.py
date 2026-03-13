#!/usr/bin/env python3
"""
COLA Registry scraper

Walks the public COLA search, collects TTB IDs from paginated results,
pulls public detail pages, extracts form fields and label images, builds
a simple on-the-fly taxonomy, and stores images with actual dimensions
encoded in the filename suffix.

Designed for the public TTB COLAs Online site:
- Search entry:
  https://ttbonline.gov/colasonline/publicSearchColasBasicProcess.do?action=search
- Detail form:
  https://ttbonline.gov/colasonline/viewColaDetails.do?action=publicFormDisplay&ttbid=<TTB_ID>

Notes:
- The public site may change markup. This scraper uses defensive parsing
  and stores raw HTML snapshots for troubleshooting.
- Be polite: keep concurrency low and use delays.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import sys
import time
from datetime import date
import urllib3
import certifi
import requests
from collections import Counter, defaultdict
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse, parse_qs
from requests.exceptions import SSLError, RequestException


BASE = "https://ttbonline.gov"
SEARCH_URL = (
    "https://ttbonline.gov/colasonline/publicSearchColasBasicProcess.do?action=search"
)
DETAIL_URL = (
    "https://ttbonline.gov/colasonline/viewColaDetails.do?action=publicFormDisplay&ttbid={ttbid}"
)

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

TTB_ID_RE = re.compile(r"\b(\d{14})\b")
WHITESPACE_RE = re.compile(r"\s+")
SAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")

# Lazy-loaded scrape dependencies.
BeautifulSoup = None
Tag = None
NavigableString = None


@dataclass
class ImageRecord:
    product_type: str
    image_type: str
    actual_dimensions: str
    src_url: str
    local_path: str


@dataclass
class ColaRecord:
    ttbid: str
    fields: Dict[str, str]
    detail_url: str
    html_path: Optional[str]
    text_path: Optional[str]
    images: List[ImageRecord]


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def normalize_space(s: str) -> str:
    return WHITESPACE_RE.sub(" ", s or "").strip()


def slugify(s: str, max_len: int = 120) -> str:
    s = normalize_space(s)
    s = s.replace("/", "-").replace("\\", "-")
    s = SAFE_RE.sub("_", s)
    s = s.strip("._-")
    if not s:
        return "unknown"
    return s[:max_len]


def safe_dimension_suffix(s: str) -> str:
    """
    Turn '4.25 IN x 6.75 IN' into '4p25INx6p75IN'
    """
    s = normalize_space(s).upper()
    s = s.replace("ACTUAL DIMENSIONS", "")
    s = s.replace(" ", "")
    s = s.replace('"', "IN")
    s = s.replace("×", "x").replace("*", "x").replace("X", "x")
    s = s.replace(".", "p")
    s = SAFE_RE.sub("_", s)
    s = s.strip("_")
    return s or "unknown_dims"


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def sha1_text(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()


def _require_scraper_deps() -> None:
    global BeautifulSoup, Tag, NavigableString
    if BeautifulSoup is not None and Tag is not None and NavigableString is not None:
        return
    try:
        from bs4 import BeautifulSoup as _BeautifulSoup, Tag as _Tag, NavigableString as _NavigableString
    except ImportError as exc:
        raise RuntimeError(
            "Missing scrape dependency 'beautifulsoup4'. Install requirements and rerun the scraper."
        ) from exc
    BeautifulSoup = _BeautifulSoup
    Tag = _Tag
    NavigableString = _NavigableString


class ColaScraper:
    def __init__(
        self,
        out_dir: Path,
        date_from: str,
        date_to: str,
        max_pages: int = 10,
        delay_min: float = 0.8,
        delay_max: float = 1.7,
        timeout: int = 45,
        max_retries: int = 4,
        verify: str | bool = certifi.where(),
        session: Optional[requests.Session] = None,
    ) -> None:
        _require_scraper_deps()
        self.out_dir = out_dir
        self.date_from = date_from
        self.date_to = date_to
        self.max_pages = max_pages
        self.delay_min = delay_min
        self.delay_max = delay_max
        self.timeout = timeout
        self.max_retries = max_retries
        self.verify = verify

        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "User-Agent": USER_AGENT,
                "Accept": (
                    "text/html,application/xhtml+xml,application/xml;"
                    "q=0.9,image/avif,image/webp,*/*;q=0.8"
                ),
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": SEARCH_URL,
            }
        )

        if self.verify is False:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        ensure_dir(self.out_dir)
        ensure_dir(self.out_dir / "html")
        ensure_dir(self.out_dir / "text")
        ensure_dir(self.out_dir / "json")
        ensure_dir(self.out_dir / "images")

        self.taxonomy_counter = Counter()
        self.taxonomy_values = defaultdict(Counter)
        self.image_type_counter = Counter()

    def sleep(self) -> None:
        time.sleep(random.uniform(self.delay_min, self.delay_max))

    def fetch(
        self,
        url: str,
        method: str = "GET",
        *,
        params: Optional[dict] = None,
        data: Optional[dict] = None,
        stream: bool = False,
    ) -> requests.Response:
        last_err = None
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = self.session.request(
                    method,
                    url,
                    params=params,
                    data=data,
                    timeout=self.timeout,
                    stream=stream,
                    verify=self.verify,
                )
                if resp.status_code >= 500:
                    raise requests.HTTPError(f"Server error {resp.status_code}")
                return resp
            except SSLError as e:
                raise RuntimeError(
                    f"TLS verification failed for {url}: {e}\n"
                    f"This server appears to have an incomplete certificate chain. "
                    f"Try --ca-bundle with the missing intermediate, or --insecure."
                ) from e
            except Exception as e:
                last_err = e
                wait = min(2**attempt, 10) + random.random()
                log(f"[retry {attempt}/{self.max_retries}] {url} -> {e}; sleeping {wait:.1f}s")
                time.sleep(wait)
        raise RuntimeError(f"Failed to fetch {url}: {last_err}")

    def run(self) -> None:
        ttbids = self.collect_ttbids()
        log(f"Collected {len(ttbids)} TTB IDs")

        records: List[ColaRecord] = []
        for i, ttbid in enumerate(ttbids, 1):
            log(f"[{i}/{len(ttbids)}] Processing {ttbid}")
            try:
                rec = self.process_ttbid(ttbid)
                records.append(rec)
            except Exception as e:
                log(f"ERROR processing {ttbid}: {e}")
            self.sleep()

        self.write_outputs(records)

    def collect_ttbids(self) -> List[str]:
        """
        Tries:
        1) GET search page, inspect form
        2) POST a few likely field combinations for Completed Date range
        3) Walk up to max_pages via next links or page params
        """
        first = self.fetch(SEARCH_URL)
        first.raise_for_status()
        soup = BeautifulSoup(first.text, "html.parser")

        form = self.find_search_form(soup)
        if form is None:
            raise RuntimeError("Could not find public search form")

        action = form.get("action") or SEARCH_URL
        search_endpoint = urljoin(SEARCH_URL, action)

        base_payload = self.build_search_payload(form)
        candidate_payloads = self.completed_date_payload_candidates(base_payload)

        seen_ids: List[str] = []
        seen_set = set()
        page_htmls: List[str] = []
        current_resp: Optional[requests.Response] = None
        current_soup: Optional[BeautifulSoup] = None

        success = False
        for payload in candidate_payloads:
            log(f"Trying search payload keys: {sorted(payload.keys())}")
            resp = self.fetch(search_endpoint, method="POST", data=payload)
            if resp.status_code != 200:
                continue
            page_ids = self.extract_ttbids_from_search_html(resp.text)
            if page_ids:
                success = True
                current_resp = resp
                current_soup = BeautifulSoup(resp.text, "html.parser")
                page_htmls.append(resp.text)
                for x in page_ids:
                    if x not in seen_set:
                        seen_set.add(x)
                        seen_ids.append(x)
                break

        if not success or current_resp is None or current_soup is None:
            raise RuntimeError(
                "Could not submit search successfully. The public search form may have changed."
            )

        # Walk additional pages.
        page_count = 1
        while page_count < self.max_pages:
            next_url, next_method, next_payload = self.find_next_page_request(current_soup, current_resp.url)
            if not next_url:
                break

            if next_method == "POST":
                resp = self.fetch(next_url, method="POST", data=next_payload)
            else:
                resp = self.fetch(next_url, method="GET", params=next_payload)

            if resp.status_code != 200:
                break

            html = resp.text
            page_ids = self.extract_ttbids_from_search_html(html)
            if not page_ids:
                break

            added = 0
            for x in page_ids:
                if x not in seen_set:
                    seen_set.add(x)
                    seen_ids.append(x)
                    added += 1

            if added == 0:
                break

            current_resp = resp
            current_soup = BeautifulSoup(html, "html.parser")
            page_htmls.append(html)
            page_count += 1
            log(f"Collected page {page_count}: +{added} new IDs")
            self.sleep()

        search_dump = self.out_dir / "json" / "search_pages_debug.json"
        with search_dump.open("w", encoding="utf-8") as f:
            json.dump(
                {
                    "search_url": SEARCH_URL,
                    "date_from": self.date_from,
                    "date_to": self.date_to,
                    "pages_collected": page_count,
                    "ttbid_count": len(seen_ids),
                },
                f,
                indent=2,
            )

        return seen_ids

    def find_search_form(self, soup: BeautifulSoup) -> Optional[Tag]:
        forms = soup.find_all("form")
        if not forms:
            return None
        for form in forms:
            text = normalize_space(form.get_text(" ", strip=True)).lower()
            action = (form.get("action") or "").lower()
            if "search" in action or "completed" in text or "cola" in text:
                return form
        return forms[0]

    def build_search_payload(self, form: Tag) -> Dict[str, str]:
        payload: Dict[str, str] = {}
        for inp in form.find_all(["input", "select", "textarea"]):
            name = inp.get("name")
            if not name:
                continue
            tag = inp.name.lower()
            if tag == "input":
                itype = (inp.get("type") or "text").lower()
                if itype in ("submit", "button", "image", "file", "reset"):
                    continue
                if itype in ("checkbox", "radio") and not inp.has_attr("checked"):
                    continue
                payload[name] = inp.get("value", "")
            elif tag == "textarea":
                payload[name] = inp.text or ""
            elif tag == "select":
                selected = inp.find("option", selected=True)
                if selected is not None:
                    payload[name] = selected.get("value", "")
                else:
                    first = inp.find("option")
                    payload[name] = first.get("value", "") if first else ""
        return payload

    def completed_date_payload_candidates(self, base_payload: Dict[str, str]) -> List[Dict[str, str]]:
        """
        The public form names may drift. We generate a few likely variants.
        """
        candidates = []

        key_sets = [
            ("completedDateFrom", "completedDateTo"),
            ("dateFrom", "dateTo"),
            ("approvalDateFrom", "approvalDateTo"),
            ("dateReceivedFrom", "dateReceivedTo"),
            ("completedDtFrom", "completedDtTo"),
        ]

        extra_variants = [
            {"action": "search"},
            {"methodToCall": "search"},
            {"search": "Search"},
            {"submit": "Search"},
        ]

        for from_key, to_key in key_sets:
            payload = dict(base_payload)
            payload[from_key] = self.date_from
            payload[to_key] = self.date_to
            candidates.append(payload)
            for extra in extra_variants:
                p2 = dict(payload)
                p2.update(extra)
                candidates.append(p2)

        # Heuristic mutation: fill any existing fields that look like date-from/date-to
        payload = dict(base_payload)
        changed = False
        for k in list(payload.keys()):
            lk = k.lower()
            if ("from" in lk or lk.endswith("start")) and "date" in lk:
                payload[k] = self.date_from
                changed = True
            elif ("to" in lk or lk.endswith("end")) and "date" in lk:
                payload[k] = self.date_to
                changed = True
        if changed:
            candidates.append(payload)

        # Deduplicate payloads
        unique = []
        seen = set()
        for p in candidates:
            key = tuple(sorted(p.items()))
            if key not in seen:
                seen.add(key)
                unique.append(p)
        return unique

    def extract_ttbids_from_search_html(self, html: str) -> List[str]:
        soup = BeautifulSoup(html, "html.parser")
        ids: List[str] = []

        # Strongest: links to detail pages with ttbid=
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "viewColaDetails" in href and "ttbid=" in href:
                parsed = urlparse(urljoin(BASE, href))
                qs = parse_qs(parsed.query)
                for val in qs.get("ttbid", []):
                    if TTB_ID_RE.fullmatch(val):
                        ids.append(val)

        # Fallback: any 14-digit numbers in text
        if not ids:
            for m in TTB_ID_RE.finditer(soup.get_text(" ", strip=True)):
                ids.append(m.group(1))

        # Preserve order, dedupe
        out = []
        seen = set()
        for x in ids:
            if x not in seen:
                seen.add(x)
                out.append(x)
        return out

    def find_next_page_request(
        self, soup: BeautifulSoup, current_url: str
    ) -> Tuple[Optional[str], str, Optional[dict]]:
        """
        Try to follow:
        - explicit 'Next >' anchor
        - page index links
        - forms with hidden inputs
        """
        next_anchor = None
        for a in soup.find_all("a", href=True):
            txt = normalize_space(a.get_text(" ", strip=True)).lower()
            href = a["href"]
            if txt in {"next >", "next", ">"} or "next" in href.lower():
                next_anchor = a
                break

        if next_anchor is not None:
            href = next_anchor["href"]
            if href.lower().startswith("javascript:"):
                # Try hidden form fallback instead
                pass
            else:
                return urljoin(current_url, href), "GET", None

        # Generic page param increment attempt
        parsed = urlparse(current_url)
        qs = parse_qs(parsed.query)
        for key in ("page", "pageNumber", "pager.offset", "offset"):
            if key in qs:
                try:
                    cur = int(qs[key][0])
                    next_qs = {k: v[0] for k, v in qs.items()}
                    if key == "offset":
                        next_qs[key] = str(cur + 20)
                    else:
                        next_qs[key] = str(cur + 1)
                    path = parsed.path
                    return urljoin(BASE, path), "GET", next_qs
                except Exception:
                    pass

        # Hidden form approach
        for form in soup.find_all("form"):
            text = normalize_space(form.get_text(" ", strip=True)).lower()
            if "next" not in text and "page" not in text:
                continue
            action = urljoin(current_url, form.get("action") or current_url)
            payload = {}
            has_pageish = False
            for inp in form.find_all("input"):
                name = inp.get("name")
                if not name:
                    continue
                value = inp.get("value", "")
                lname = name.lower()
                if "page" in lname or "offset" in lname:
                    has_pageish = True
                    try:
                        if value.isdigit():
                            value = str(int(value) + 1)
                    except Exception:
                        pass
                payload[name] = value
            if has_pageish:
                return action, "POST", payload

        return None, "GET", None

    def process_ttbid(self, ttbid: str) -> ColaRecord:
        detail_url = DETAIL_URL.format(ttbid=ttbid)
        resp = self.fetch(detail_url)
        resp.raise_for_status()
        html = resp.text

        html_path = self.out_dir / "html" / f"{ttbid}.html"
        html_path.write_text(html, encoding="utf-8")

        soup = BeautifulSoup(html, "html.parser")
        fields = self.parse_fields(soup)
        fields["TTB ID"] = ttbid

        product_type = self.extract_product_type(soup, fields)
        fields["TYPE OF PRODUCT"] = product_type

        text_path = self.out_dir / "text" / f"{ttbid}.txt"
        text_path.write_text(
            "\n".join(f"{k}: {v}" for k, v in sorted(fields.items())),
            encoding="utf-8",
        )

        images = self.extract_and_download_images(ttbid, soup, html, product_type)

        for k, v in fields.items():
            self.taxonomy_counter[k] += 1
            if v:
                self.taxonomy_values[k][v] += 1

        return ColaRecord(
            ttbid=ttbid,
            fields=fields,
            detail_url=detail_url,
            html_path=str(html_path.relative_to(self.out_dir)),
            text_path=str(text_path.relative_to(self.out_dir)),
            images=images,
        )

    def parse_fields(self, soup: BeautifulSoup) -> Dict[str, str]:
        """
        Defensive parser:
        - dt/dd pairs
        - table rows with label/value
        - generic adjacent .label/.data patterns
        """
        fields: Dict[str, str] = {}

        # dt/dd
        for dl in soup.find_all("dl"):
            dts = dl.find_all("dt")
            for dt in dts:
                dd = dt.find_next_sibling("dd")
                if dd:
                    key = normalize_space(dt.get_text(" ", strip=True)).rstrip(":")
                    val = normalize_space(dd.get_text(" ", strip=True))
                    if key and val and key not in fields:
                        fields[key] = val

        # Tables
        for tr in soup.find_all("tr"):
            cells = tr.find_all(["th", "td"])
            if len(cells) >= 2:
                key = normalize_space(cells[0].get_text(" ", strip=True)).rstrip(":")
                val = normalize_space(cells[1].get_text(" ", strip=True))
                if key and val and len(key) < 120:
                    if key not in fields:
                        fields[key] = val

        # p/div/span label -> next .data or sibling
        candidates = soup.find_all(
            lambda tag: isinstance(tag, Tag)
            and tag.name in {"p", "div", "span", "td", "th"}
            and ("label" in (tag.get("class") or []) or self.looks_like_label(tag))
        )
        for tag in candidates:
            key = normalize_space(tag.get_text(" ", strip=True)).rstrip(":")
            if not key or len(key) > 120:
                continue

            # first try sibling with class data
            val = None
            sib = tag.find_next_sibling()
            if sib is not None:
                if "data" in (sib.get("class") or []):
                    val = normalize_space(sib.get_text(" ", strip=True))
                elif sib.name in {"td", "div", "span", "p"}:
                    txt = normalize_space(sib.get_text(" ", strip=True))
                    if txt and txt != key:
                        val = txt

            # fallback: nearby next element with class data
            if not val:
                nxt = tag.find_next(
                    lambda x: isinstance(x, Tag)
                    and x is not tag
                    and "data" in (x.get("class") or [])
                )
                if nxt is not None:
                    txt = normalize_space(nxt.get_text(" ", strip=True))
                    if txt and txt != key:
                        val = txt

            if val and key not in fields:
                fields[key] = val

        return fields

    def looks_like_label(self, tag: Tag) -> bool:
        txt = normalize_space(tag.get_text(" ", strip=True))
        if not txt or len(txt) > 80:
            return False
        if txt.endswith(":"):
            return True
        common = {
            "brand name",
            "fanciful name",
            "class/type",
            "appellation",
            "alcohol content",
            "net contents",
            "serial number",
            "city",
            "state",
            "country",
            "image type",
            "actual dimensions",
        }
        return txt.lower() in common

    def extract_and_download_images(
        self, ttbid: str, soup: BeautifulSoup, html: str, product_type: str
    ) -> List[ImageRecord]:
        """
        Routing rules:
        - Any image whose src URL contains 'Signature' goes to images/Signatures/
        - Label images are taken only from the section beginning at:
              <p class="data">AFFIX COMPLETE SET OF LABELS BELOW</p>
        - The text after that marker determines Brand / Back / Other
        - Actual Dimensions near that block are used in the filename suffix
        """
        records: List[ImageRecord] = []
        seen_srcs: set[str] = set()
        save_idx = 0

        # 1) Save signatures anywhere in the document.
        for img in soup.find_all("img", src=True):
            abs_src = urljoin(BASE, img["src"])
            if abs_src in seen_srcs:
                continue
            if "signature" in abs_src.lower():
                save_idx += 1
                rec = self.save_image_record(
                    ttbid=ttbid,
                    product_type=product_type,
                    bucket="Signatures",
                    actual_dimensions="unknown",
                    abs_src=abs_src,
                    idx=save_idx,
                )
                if rec is not None:
                    records.append(rec)
                    seen_srcs.add(abs_src)

        # 2) Find the label section marker.
        marker = soup.find(
            lambda tag: isinstance(tag, Tag)
            and tag.name == "p"
            and "data" in (tag.get("class") or [])
            and "AFFIX COMPLETE SET OF LABELS BELOW" in tag.get_text(" ", strip=True).upper()
        )
        if marker is None:
            return records

        # Prefer the local table/container holding the label blocks.
        label_container = marker.find_parent("table") or marker.parent or soup

        started = False
        expect_image_type_value = False
        current_bucket: Optional[str] = None
        current_dimensions = "unknown"

        for node in label_container.descendants:
            if node is marker:
                started = True
                continue
            if not started:
                continue

            if isinstance(node, NavigableString):
                txt = normalize_space(str(node))
                if not txt:
                    continue

                if expect_image_type_value:
                    bucket = self.canonical_image_bucket(txt)
                    if bucket in {"Brand", "Back", "Other"}:
                        current_bucket = bucket
                        expect_image_type_value = False

                dims = self.parse_actual_dimensions_text(txt)
                if dims:
                    current_dimensions = dims

                continue

            if not isinstance(node, Tag):
                continue

            if node.name == "p" and "data" in (node.get("class") or []):
                txt = normalize_space(node.get_text(" ", strip=True))
                low = txt.lower()

                if low.startswith("image type"):
                    # Sometimes the value is in the same node, sometimes just after it.
                    remainder = normalize_space(txt.split(":", 1)[1]) if ":" in txt else ""
                    bucket = self.canonical_image_bucket(remainder) if remainder else None
                    if bucket in {"Brand", "Back", "Other"}:
                        current_bucket = bucket
                        expect_image_type_value = False
                    else:
                        expect_image_type_value = True
                    continue

                dims = self.parse_actual_dimensions_text(txt)
                if dims:
                    current_dimensions = dims
                    continue

                # Fallback: some pages may put the type in a plain data paragraph.
                bucket = self.canonical_image_bucket(txt)
                if bucket in {"Brand", "Back", "Other"}:
                    current_bucket = bucket
                    expect_image_type_value = False
                    continue

            if node.name == "img" and node.get("src"):
                abs_src = urljoin(BASE, node["src"])
                if abs_src in seen_srcs:
                    continue

                # Signatures already handled globally above.
                if "signature" in abs_src.lower():
                    continue

                if current_bucket not in {"Brand", "Back", "Other"}:
                    continue

                save_idx += 1
                rec = self.save_image_record(
                    ttbid=ttbid,
                    product_type=product_type,
                    bucket=current_bucket,
                    actual_dimensions=current_dimensions,
                    abs_src=abs_src,
                    idx=save_idx,
                )
                if rec is not None:
                    records.append(rec)
                    seen_srcs.add(abs_src)

        return records

    def extract_image_context(self, img: Tag) -> Dict[str, str]:
        """
        Look near the image for 'Image Type' and 'Actual Dimensions' labels.
        """
        context = {}

        # Check parent containers up the tree
        ancestors: List[Tag] = []
        cur = img
        for _ in range(5):
            parent = cur.parent
            if not isinstance(parent, Tag):
                break
            ancestors.append(parent)
            cur = parent

        for node in [img] + ancestors:
            text = normalize_space(node.get_text(" ", strip=True))
            if not text:
                continue

            m1 = re.search(r"Image Type\s*:?\s*([^:]+?)(?:Actual Dimensions|$)", text, flags=re.I)
            if m1 and "Image Type" not in context:
                context["Image Type"] = normalize_space(m1.group(1))

            m2 = re.search(
                r"Actual Dimensions\s*:?\s*([0-9A-Za-z.\"' x×*.-]+)",
                text,
                flags=re.I,
            )
            if m2 and "Actual Dimensions" not in context:
                context["Actual Dimensions"] = normalize_space(m2.group(1))

        # Sibling scan
        if "Image Type" not in context or "Actual Dimensions" not in context:
            sib_texts = []
            sib = img.parent if isinstance(img.parent, Tag) else img
            for _ in range(8):
                sib = sib.find_previous_sibling() if isinstance(sib, Tag) else None
                if sib is None:
                    break
                sib_texts.append(normalize_space(sib.get_text(" ", strip=True)))
            joined = " ".join(reversed(sib_texts))
            if "Image Type" not in context:
                m1 = re.search(r"Image Type\s*:?\s*([^:]+?)(?:Actual Dimensions|$)", joined, flags=re.I)
                if m1:
                    context["Image Type"] = normalize_space(m1.group(1))
            if "Actual Dimensions" not in context:
                m2 = re.search(
                    r"Actual Dimensions\s*:?\s*([0-9A-Za-z.\"' x×*.-]+)",
                    joined,
                    flags=re.I,
                )
                if m2:
                    context["Actual Dimensions"] = normalize_space(m2.group(1))

        return context

    def guess_ext_from_url(self, url: str) -> str:
        path = urlparse(url).path.lower()
        for ext in (".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tif", ".tiff", ".webp"):
            if path.endswith(ext):
                return ext
        return ".bin"

    def download_binary(self, url: str, out_path: Path) -> Path:
        resp = self.fetch(url, stream=True)
        resp.raise_for_status()

        iterator = resp.iter_content(chunk_size=65536)

        first_chunk = b""
        for chunk in iterator:
            if chunk:
                first_chunk = chunk
                break

        actual_ext = self.detect_image_ext(resp, first_chunk, url)
        final_path = out_path.with_suffix(actual_ext)

        with final_path.open("wb") as f:
            if first_chunk:
                f.write(first_chunk)
            for chunk in iterator:
                if chunk:
                    f.write(chunk)

        return final_path

    def write_outputs(self, records: List[ColaRecord]) -> None:
        records_json = self.out_dir / "json" / "records.jsonl"
        with records_json.open("w", encoding="utf-8") as f:
            for rec in records:
                payload = asdict(rec)
                f.write(json.dumps(payload, ensure_ascii=False) + "\n")

        taxonomy = {
            "field_counts": dict(self.taxonomy_counter),
            "top_values": {
                field: dict(counter.most_common(50))
                for field, counter in self.taxonomy_values.items()
            },
            "image_type_counts": dict(self.image_type_counter),
        }
        with (self.out_dir / "json" / "taxonomy.json").open("w", encoding="utf-8") as f:
            json.dump(taxonomy, f, indent=2, ensure_ascii=False)

        summary = {
            "date_from": self.date_from,
            "date_to": self.date_to,
            "record_count": len(records),
            "image_count": sum(len(r.images) for r in records),
            "output_dir": str(self.out_dir),
        }
        with (self.out_dir / "json" / "summary.json").open("w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)

    def canonical_product_type(self, text: str) -> Optional[str]:
        t = normalize_space(text).upper()
        if not t:
            return None
        if re.search(r"\bDISTILLED\s+SPIRITS?\b", t):
            return "Distilled"
        if re.search(r"\bMALT\s+BEVERAGE\b", t):
            return "Beer"
        if re.search(r"\bWINE\b", t):
            return "Wine"
        return None

    def extract_product_type(self, soup: BeautifulSoup, fields: Dict[str, str]) -> str:
        # Do not trust parse_fields() for this unless it maps cleanly.
        for key, val in fields.items():
            if "TYPE OF PRODUCT" in key.upper():
                product_type = self.canonical_product_type(val)
                if product_type is not None:
                    return product_type

        marker = soup.find(
            lambda tag: isinstance(tag, Tag)
            and tag.name == "div"
            and "TYPE OF PRODUCT" in tag.get_text(" ", strip=True).upper()
        )

        if marker is not None:
            product_table = marker.find_next("table")

            if product_table is not None:
                for tr in product_table.find_all("tr", recursive=False):
                    checkbox = tr.find("input", attrs={"type": "checkbox"})
                    if checkbox is None:
                        continue

                    is_checked = checkbox.has_attr("checked") or str(
                        checkbox.get("checked", "")
                    ).lower() in {"checked", "true", "1"}
                    if not is_checked:
                        continue

                    candidates: List[str] = []

                    for attr in ("alt", "title", "aria-label", "value", "name", "id"):
                        val = checkbox.get(attr)
                        if val:
                            candidates.append(val)

                    for td in tr.find_all("td"):
                        txt = normalize_space(td.get_text(" ", strip=True))
                        if txt:
                            candidates.append(txt)

                    row_text = normalize_space(tr.get_text(" ", strip=True))
                    if row_text:
                        candidates.append(row_text)

                    for candidate in candidates:
                        product_type = self.canonical_product_type(candidate)
                        if product_type is not None:
                            return product_type

            scope = marker.find_parent("td") or marker.parent or soup
            for inp in scope.find_all("input", attrs={"type": "checkbox"}):
                is_checked = inp.has_attr("checked") or str(
                    inp.get("checked", "")
                ).lower() in {"checked", "true", "1"}
                if not is_checked:
                    continue

                candidates: List[str] = []

                for attr in ("alt", "title", "aria-label", "value", "name", "id"):
                    val = inp.get(attr)
                    if val:
                        candidates.append(val)

                if isinstance(inp.parent, Tag):
                    txt = normalize_space(inp.parent.get_text(" ", strip=True))
                    if txt:
                        candidates.append(txt)

                next_td = inp.find_next("td")
                if isinstance(next_td, Tag):
                    txt = normalize_space(next_td.get_text(" ", strip=True))
                    if txt:
                        candidates.append(txt)

                for candidate in candidates:
                    product_type = self.canonical_product_type(candidate)
                    if product_type is not None:
                        return product_type

        return "Unknown"

    def canonical_image_bucket(self, text: str) -> Optional[str]:
        t = normalize_space(text).lower()
        if not t:
            return None

        if "signature" in t:
            return "Signatures"
        if "back" in t:
            return "Back"
        if "other" in t:
            return "Other"
        if "brand" in t or "front" in t or "keg collar" in t:
            return "Brand"

        return None

    def parse_actual_dimensions_text(self, text: str) -> Optional[str]:
        t = normalize_space(text)
        if not t:
            return None

        m = re.search(r"Actual Dimensions\s*:?\s*(.+)$", t, flags=re.I)
        if m:
            val = normalize_space(m.group(1))
            if val:
                return val

        # Fallback for bare dimension text near the label image.
        m = re.search(
            r"([0-9]+(?:\.[0-9]+)?\s*(?:IN|\"|')?\s*[x×]\s*[0-9]+(?:\.[0-9]+)?\s*(?:IN|\"|')?)",
            t,
            flags=re.I,
        )
        if m:
            return normalize_space(m.group(1))

        return None

    def save_image_record(
        self,
        ttbid: str,
        product_type: str,
        bucket: str,
        actual_dimensions: str,
        abs_src: str,
        idx: int,
    ) -> Optional[ImageRecord]:
        dim_suffix = safe_dimension_suffix(actual_dimensions)

        if bucket == "Signatures":
            image_dir = self.out_dir / "images" / "Signatures"
            filename = f"{ttbid}__{product_type}__Signatures__{dim_suffix}__{idx}.bin"
        else:
            image_dir = self.out_dir / "images" / product_type / bucket
            filename = f"{ttbid}__{product_type}__{bucket}__{dim_suffix}__{idx}.bin"

        ensure_dir(image_dir)
        local_path = image_dir / filename

        try:
            saved_path = self.download_binary(abs_src, local_path)
        except Exception as e:
            log(f"Failed image download for {ttbid}: {abs_src} -> {e}")
            return None

        counter_key = "Signatures" if bucket == "Signatures" else f"{product_type}/{bucket}"
        self.image_type_counter[counter_key] += 1

        return ImageRecord(
            product_type=product_type,
            image_type=bucket,
            actual_dimensions=actual_dimensions,
            src_url=abs_src,
            local_path=str(saved_path.relative_to(self.out_dir)),
        )

    def detect_image_ext(self, resp: requests.Response, first_chunk: bytes, url: str) -> str:
        # 1) Try HTTP Content-Type
        ct = (resp.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
        content_type_map = {
            "image/jpeg": ".jpg",
            "image/jpg": ".jpg",
            "image/png": ".png",
            "image/webp": ".webp",
            "image/gif": ".gif",
            "image/tiff": ".tif",
            "image/bmp": ".bmp",
        }
        if ct in content_type_map:
            return content_type_map[ct]

        # 2) Try magic bytes
        if first_chunk.startswith(b"\xff\xd8\xff"):
            return ".jpg"
        if first_chunk.startswith(b"\x89PNG\r\n\x1a\n"):
            return ".png"
        if first_chunk[:4] == b"RIFF" and first_chunk[8:12] == b"WEBP":
            return ".webp"
        if first_chunk.startswith((b"GIF87a", b"GIF89a")):
            return ".gif"
        if first_chunk.startswith((b"II*\x00", b"MM\x00*")):
            return ".tif"
        if first_chunk.startswith(b"BM"):
            return ".bmp"

        # 3) Fallback to URL-based guess
        return self.guess_ext_from_url(url)


def build_arg_parser() -> argparse.ArgumentParser:
    default_out_dir = _default_out_dir()
    p = argparse.ArgumentParser(description="Scrape public TTB COLA Registry")
    p.add_argument("--date-from", default="03/01/2025", help="MM/DD/YYYY")
    p.add_argument("--date-to", default="03/10/2026", help="MM/DD/YYYY")
    p.add_argument("--max-pages", type=int, default=10, help="Maximum result pages to walk")
    p.add_argument("--out-dir", default=default_out_dir, help="Output directory")
    p.add_argument("--delay-min", type=float, default=0.8)
    p.add_argument("--delay-max", type=float, default=1.7)
    p.add_argument("--timeout", type=int, default=45)
    p.add_argument("--max-retries", type=int, default=4)
    p.add_argument("--ca-bundle", default=certifi.where(), help="Path to CA bundle file to use for TLS verification")
    p.add_argument("--insecure", action="store_true", help="Disable TLS certificate verification (debugging only)")
    return p


def _default_out_dir(today: date | None = None) -> Path:
    if today is None:
        today = date.today()
    repo_root = Path(__file__).resolve().parents[1]
    return repo_root / "data" / "cola_raw" / f"{today.strftime('%Y%m%d')}_run"


def main() -> int:
    args = build_arg_parser().parse_args()
    
    verify: str | bool
    if args.insecure:
        verify = False
    else:
        verify = args.ca_bundle

    out_dir = Path(args.out_dir).resolve()
    scraper = ColaScraper(
        out_dir=out_dir,
        date_from=args.date_from,
        date_to=args.date_to,
        max_pages=args.max_pages,
        delay_min=args.delay_min,
        delay_max=args.delay_max,
        timeout=args.timeout,
        max_retries=args.max_retries,
        verify=verify,
    )
    scraper.run()
    print(f"Done. Output written to: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
