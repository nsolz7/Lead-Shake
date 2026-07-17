from app.services.normalization import (
    hmac_policy_id, normalize_address, normalize_domain, normalize_email, normalize_name,
    normalize_phone,
)
from app.services.classification import classify_business, is_confirmed_chain


def test_normalizers_produce_stable_matching_keys():
    assert normalize_name("The Oak & Ember Hospitality, LLC") == "the oak ember hospitality"
    assert normalize_domain("https://www.Example.com/locations") == "example.com"
    assert normalize_email("  Owner@Example.COM ") == "owner@example.com"
    assert normalize_phone("(919) 555-0142") == "+19195550142"
    assert normalize_address("10 Main St.", "Raleigh", "NC", "27601-1234") == "10mainst|raleigh|nc|27601"


def test_policy_identifier_is_hmacd_and_masked():
    digest, masked = hmac_policy_id("WC 1234 5678")
    assert digest and len(digest) == 64
    assert masked == "****5678"
    assert "1234" not in masked


def test_vertical_policy_uses_exact_categories_and_token_boundaries():
    assert classify_business("auto_insurance", "NC Farm Bureau").status == "excluded"
    assert classify_business("retirement_home", "Autumn Care").status == "excluded"
    assert classify_business("barber", "Brow Bar").status == "excluded"
    assert classify_business("auto_repair", "Oak City Auto").vertical == "auto_services"
    assert classify_business(None, "Apex Auto Insurance Agency").status == "excluded"


def test_vertical_policy_covers_observed_overture_categories():
    assert classify_business("automotive_repair", "Oak City Auto").vertical == "auto_services"
    assert classify_business("seafood_restaurant", "Cape Fear Seafood").vertical == "hospitality_alcohol_events"
    assert classify_business("contractor", "Triangle Builders").vertical == "contractors_trades"
    assert classify_business("hair_salon", "Downtown Hair").status == "excluded"
    assert classify_business("it_service_and_computer_repair", "PC Help").status == "excluded"
    assert classify_business("truck_rentals", "Rental Fleet").status == "excluded"
    assert classify_business("cocktail_bar", "The Argonaut").vertical == "hospitality_alcohol_events"
    assert classify_business("wheel_and_rim_repair", "Accurate Wheel Repair").vertical == "auto_services"
    assert classify_business("public_service_and_government", "County Office").status == "excluded"
    assert classify_business(None, "Licensed Electricians of Raleigh").vertical == "contractors_trades"
    assert is_confirmed_chain("Pizza Hut") is True
    assert is_confirmed_chain("Pizza Hutters Local Cafe") is False
