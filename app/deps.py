"""Everything the endpoints need, built once. Tests swap in fakes for the internet parts."""
from dataclasses import dataclass
from typing import Callable

from app.data_loader import dropdown_concerns, load_all
from app.services import llm_client, obf_client
from app.services.normalizer import Normalizer, from_data
from app.services.rule_engine import RuleEngine


@dataclass
class Services:
    data: dict
    normalizer: Normalizer
    engine: RuleEngine
    dropdown: dict
    obf_lookup: Callable          # barcode -> dict
    obf_search: Callable          # text -> dict
    extract: object               # list of (name, function(image_bytes, mime) -> dict), or one function
    summarize: object             # list of (name, function(prompt) -> text), one function, or None


def build_services(data: dict | None = None, **overrides) -> Services:
    data = data or load_all()
    s = Services(data=data, normalizer=from_data(data), engine=RuleEngine(data), dropdown=dropdown_concerns(data),
                 obf_lookup=obf_client.get_product, obf_search=obf_client.search_products,
                 extract=llm_client.extract_providers(), summarize=llm_client.summary_providers())
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


_services: Services | None = None


def get_services() -> Services:
    global _services
    if _services is None:
        _services = build_services()
    return _services
