from __future__ import annotations

import re
from dataclasses import dataclass


POLICY_VERSION = "vertical-policy-v2"

# Exact source-category rules are deliberately conservative. Unknown categories
# stay reviewable; only unambiguous non-target categories are auto-quarantined.
TARGET_CATEGORY_MAP: dict[str, str] = {
    "restaurant": "hospitality_alcohol_events",
    "bar": "hospitality_alcohol_events",
    "brewery": "hospitality_alcohol_events",
    "winery": "hospitality_alcohol_events",
    "distillery": "hospitality_alcohol_events",
    "hotel": "hospitality_alcohol_events",
    "event_venue": "hospitality_alcohol_events",
    "caterer": "hospitality_alcohol_events",
    "golf_course": "hospitality_alcohol_events",
    "fitness_center": "fitness_recreation",
    "gym": "fitness_recreation",
    "yoga_studio": "fitness_recreation",
    "dance_studio": "fitness_recreation",
    "martial_arts_school": "fitness_recreation",
    "sports_club": "fitness_recreation",
    "general_contractor": "contractors_trades",
    "construction_company": "contractors_trades",
    "plumber": "contractors_trades",
    "electrician": "contractors_trades",
    "hvac_contractor": "contractors_trades",
    "roofing_contractor": "contractors_trades",
    "landscaper": "contractors_trades",
    "fire_protection_service": "contractors_trades",
    "auto_repair": "auto_services",
    "auto_body_shop": "auto_services",
    "car_dealer": "auto_services",
    "tire_shop": "auto_services",
    "car_wash": "auto_services",
    "automotive_service": "auto_services",
    "automotive_repair": "auto_services",
    "used_car_dealer": "auto_services",
    "tire_dealer_and_repair": "auto_services",
    "auto_glass_service": "auto_services",
    "auto_detailing": "auto_services",
    "automotive": "auto_services",
    "automotive_dealer": "auto_services",
    "automotive_services_and_repair": "auto_services",
    "auto_customization": "auto_services",
    "truck_dealer": "auto_services",
    "truck_repair": "auto_services",
    "auto_company": "auto_services",
    "wheel_and_rim_repair": "auto_services",
    "windshield_installation_and_repair": "auto_services",
    "motorcycle_repair": "auto_services",
    "contractor": "contractors_trades",
    "construction_services": "contractors_trades",
    "hvac_services": "contractors_trades",
    "plumbing": "contractors_trades",
    "roofing": "contractors_trades",
    "landscaping": "contractors_trades",
    "masonry_concrete": "contractors_trades",
    "garage_door_service": "contractors_trades",
    "key_and_locksmith": "contractors_trades",
    "pilates_studio": "fitness_recreation",
    "sports_and_recreation_venue": "fitness_recreation",
    "martial_arts_club": "fitness_recreation",
    "fitness_trainer": "fitness_recreation",
    "dance_school": "fitness_recreation",
    "kids_recreation_and_party": "fitness_recreation",
    "sports_and_fitness_instruction": "fitness_recreation",
    "boot_camp": "fitness_recreation",
    "health_and_wellness_club": "fitness_recreation",
    "gymnastics_center": "fitness_recreation",
    "bowling_alley": "fitness_recreation",
    "equestrian_facility": "fitness_recreation",
    "sports_club_and_league": "fitness_recreation",
    "horse_riding": "fitness_recreation",
    "coffee_shop": "hospitality_alcohol_events",
    "smoothie_juice_bar": "hospitality_alcohol_events",
    "cocktail_bar": "hospitality_alcohol_events",
    "wine_bar": "hospitality_alcohol_events",
    "hookah_bar": "hospitality_alcohol_events",
    "salad_bar": "hospitality_alcohol_events",
    "tapas_bar": "hospitality_alcohol_events",
    "sandwich_shop": "hospitality_alcohol_events",
    "sports_bar": "hospitality_alcohol_events",
    "resort": "hospitality_alcohol_events",
    "gastropub": "hospitality_alcohol_events",
    "lounge": "hospitality_alcohol_events",
}

CATEGORY_SUFFIX_MAP = {
    "_restaurant": "hospitality_alcohol_events",
    "_contractor": "contractors_trades",
}

DENY_CATEGORY_REASONS: dict[str, str] = {
    "insurance_agency": "insurance_business",
    "auto_insurance": "insurance_business",
    "insurance_broker": "insurance_business",
    "financial_service": "financial_services",
    "bank": "financial_services",
    "credit_union": "financial_services",
    "mortgage_lender": "financial_services",
    "investment_service": "financial_services",
    "accountant": "financial_services",
    "tax_preparation": "financial_services",
    "real_estate_agency": "real_estate",
    "law_firm": "legal_services",
    "government_office": "government",
    "school": "education",
    "university": "education",
    "hospital": "healthcare",
    "medical_clinic": "healthcare",
    "retirement_home": "healthcare",
    "nursing_home": "healthcare",
    "beauty_salon": "personal_care",
    "barber_shop": "personal_care",
    "barber": "personal_care",
    "spa": "personal_care",
    "self_storage": "storage",
    "storage_facility": "storage",
    "religious_organization": "religious_organization",
    "church": "religious_organization",
    "hair_salon": "personal_care",
    "nail_salon": "personal_care",
    "public_and_government_association": "government",
    "park": "government_or_public_space",
    "it_service_and_computer_repair": "technology_services",
    "automotive_parts_and_accessories": "retail",
    "auto_parts_and_supply_store": "retail",
    "party_supply": "retail",
    "truck_rentals": "vehicle_rental",
    "golf_cart_dealer": "retail",
    "bartender": "individual_service",
    "public_service_and_government": "government",
    "post_office": "government",
    "beauty_and_spa": "personal_care",
    "hair_removal": "personal_care",
    "naturopathic_holistic": "healthcare",
    "nurse_practitioner": "healthcare",
    "personal_injury_law": "legal_services",
    "lawyer": "legal_services",
    "pet_sitting": "pet_services",
    "pet_boarding": "pet_services",
    "animal_shelter": "pet_services",
    "electronics": "retail",
    "mobile_phone_repair": "technology_services",
    "jewelry_store": "retail",
    "furniture_store": "retail",
    "auto_loan_provider": "financial_services",
    "cannabis_dispensary": "regulated_retail",
    "farm": "agriculture",
    "livestock_breeder": "agriculture",
}

NAICS_PREFIX_MAP = {
    "722": "hospitality_alcohol_events",
    "721": "hospitality_alcohol_events",
    "7139": "fitness_recreation",
    "236": "contractors_trades",
    "237": "contractors_trades",
    "238": "contractors_trades",
    "441": "auto_services",
    "8111": "auto_services",
}

NAME_FALLBACKS: dict[str, tuple[str, ...]] = {
    "hospitality_alcohol_events": ("restaurant", "brewery", "distillery", "winery", "event venue", "catering", "nightclub"),
    "fitness_recreation": ("fitness", "gym", "yoga", "pilates", "dance studio", "martial arts", "golf club", "movement club"),
    "contractors_trades": ("contractor", "construction", "plumbing", "electric", "electrician", "electricians", "hvac", "heating and air", "roofing", "landscaping"),
    "auto_services": ("auto repair", "auto care", "automotive", "collision", "body shop", "tire", "car wash", "auto glass", "windshield repair"),
}

WRONG_NAME_PATTERNS: dict[str, tuple[str, ...]] = {
    "insurance_business": ("insurance", "allstate", "state farm", "farm bureau insurance", "nationwide insurance"),
    "financial_services": ("bank", "credit union", "financial services", "wealth management", "mortgage"),
    "religious_organization": ("orthodox church", "baptist church", "methodist church", "church of", "ministries"),
    "storage": ("self storage", "storage units"),
    "personal_care": ("beauty salon", "hair salon", "barber shop", "nail salon"),
}

CONFIRMED_CHAIN_NAMES = {
    "bojangles", "burger king", "chili s", "domino s", "dunkin", "five guys",
    "jiffy lube", "kfc", "mcdonald s", "meineke", "midas", "olive garden",
    "orangetheory fitness", "panera bread", "pizza hut", "planet fitness",
    "popeyes", "starbucks", "subway", "taco bell", "the ups store", "valvoline",
    "wendy s", "anytime fitness",
}


@dataclass(frozen=True)
class ClassificationDecision:
    vertical: str
    status: str
    reason: str
    confidence: float
    policy_version: str = POLICY_VERSION


def normalize_category(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (value or "").strip().lower()).strip("_")


def _contains_phrase(text: str, phrase: str) -> bool:
    pattern = r"(?<![a-z0-9])" + re.escape(phrase).replace(r"\ ", r"\s+") + r"(?![a-z0-9])"
    return bool(re.search(pattern, text))


def classify_business(category: str | None, name: str | None = None, naics: str | None = None) -> ClassificationDecision:
    normalized_category = normalize_category(category)
    if normalized_category in DENY_CATEGORY_REASONS:
        return ClassificationDecision("unknown", "excluded", f"wrong_vertical:{DENY_CATEGORY_REASONS[normalized_category]}", 0.99)
    normalized_name = re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).strip()
    for reason, phrases in WRONG_NAME_PATTERNS.items():
        if any(_contains_phrase(normalized_name, phrase) for phrase in phrases):
            return ClassificationDecision("unknown", "excluded", f"wrong_vertical:{reason}", 0.92)
    if normalized_category in TARGET_CATEGORY_MAP:
        return ClassificationDecision(TARGET_CATEGORY_MAP[normalized_category], "target", f"exact_category:{normalized_category}", 0.98)
    for suffix, vertical in CATEGORY_SUFFIX_MAP.items():
        if normalized_category.endswith(suffix):
            return ClassificationDecision(vertical, "target", f"category_suffix:{suffix}", 0.94)

    digits = re.sub(r"\D", "", naics or "")
    for prefix, vertical in sorted(NAICS_PREFIX_MAP.items(), key=lambda item: len(item[0]), reverse=True):
        if digits.startswith(prefix):
            return ClassificationDecision(vertical, "target", f"naics:{prefix}", 0.95)

    for vertical, phrases in NAME_FALLBACKS.items():
        if any(_contains_phrase(normalized_name, phrase) for phrase in phrases):
            return ClassificationDecision(vertical, "target", f"name_token:{vertical}", 0.75)
    return ClassificationDecision("unknown", "review_required", "unknown_vertical", 0.3)


def is_confirmed_chain(name: str | None) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).strip()
    return normalized in CONFIRMED_CHAIN_NAMES
