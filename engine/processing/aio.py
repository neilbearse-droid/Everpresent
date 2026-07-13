"""GoogleAIOSignal and its rule-based classifier (§5.2, §6.3).

The AIO dimension stays orthogonal to web-search-likelihood — Google's
RAG-grounded surface is never collapsed into the Bing/ChatGPT retrieval
signal (§5.2).

CALIBRATION STATUS: the thresholds below are PROVISIONAL. §6.3 requires
calibration against Neil's 40 labeled seed queries (§12.1), which have not
been provided. tests/test_aio_calibration.py activates automatically when
seeds/aio_labels.yaml appears; until then tests pin the provisional rules as
a regression set (DECISIONS.md M6)."""

from enum import StrEnum

from pydantic import BaseModel, Field

from engine.retrievers.google_aio import AIOCaptureSummary

AIO_CLASSIFIER_VERSION = "v3.0.0-uncalibrated"

# An expanded-or-long AIO reads as the dominant answer surface.
DOMINANT_TEXT_LEN = 1200


class AIOSourceType(StrEnum):
    no_aio = "no_aio"
    aio_dominant = "aio_dominant"
    aio_plus_organic = "aio_plus_organic"
    organic_dominant = "organic_dominant"


class GoogleAIOSignal(BaseModel):
    """§5.2 exactly: defaults describe 'AIO retrieval did not run'."""

    triggered: bool = False
    confidence: float = 0.0
    source_type: AIOSourceType = AIOSourceType.no_aio
    cited_urls: list[str] = Field(default_factory=list)
    cited_domains: list[str] = Field(default_factory=list)
    classifier_version: str = ""


def _deduped_domains(urls: list[str]) -> list[str]:
    from urllib.parse import urlparse

    seen: set[str] = set()
    domains: list[str] = []
    for url in urls:
        domain = urlparse(url).netloc.removeprefix("www.")
        if domain and domain not in seen:
            seen.add(domain)
            domains.append(domain)
    return domains


def classify_aio_capture(summary: AIOCaptureSummary, cited_urls: list[str]) -> GoogleAIOSignal:
    if not summary.ran:
        return GoogleAIOSignal()  # §5.2 default: no_aio / 0.0

    if not summary.aio_present:
        return GoogleAIOSignal(
            triggered=False,
            confidence=0.9,  # we looked at the SERP and there was no AIO
            source_type=AIOSourceType.no_aio,
            classifier_version=AIO_CLASSIFIER_VERSION,
        )

    top = summary.aio_position_index == 0
    dominant_size = summary.expanded or summary.aio_text_len >= DOMINANT_TEXT_LEN
    if top and dominant_size:
        source_type, confidence = AIOSourceType.aio_dominant, 0.8
    elif top:
        source_type, confidence = AIOSourceType.aio_plus_organic, 0.7
    else:
        source_type, confidence = AIOSourceType.organic_dominant, 0.7

    return GoogleAIOSignal(
        triggered=True,
        confidence=confidence,
        source_type=source_type,
        cited_urls=list(cited_urls),
        cited_domains=_deduped_domains(cited_urls),
        classifier_version=AIO_CLASSIFIER_VERSION,
    )
