from app.matching import normalize, similarity, specs_compatible, spec_tokens, group_offers, relevance, is_accessory, same_product_family, model_codes
from app.stores.base import Offer
import pytest


def O(store, title, price):
    return Offer(store=store, title=title, price=price, url=f"https://{store}.example/x")


def test_normalize_fuses_specs_and_drops_filler():
    t = normalize("Apple iPhone 15 (Black, 128 GB) with free delivery")
    assert "128gb" in t and "apple" in t and "iphone" in t and "15" in t
    assert "with" not in t and "free" not in t and "gb" not in t


def test_specs_must_agree_when_both_present():
    a = spec_tokens(normalize("iPhone 15 128GB"))
    b = spec_tokens(normalize("iPhone 15 256 GB"))
    c = spec_tokens(normalize("iPhone 15 Black"))
    assert not specs_compatible(a, b)
    assert specs_compatible(a, c)


def test_similarity_bounds():
    assert similarity({"a", "b"}, {"a", "b"}) == 1.0
    assert similarity({"a"}, {"b"}) == 0.0
    assert similarity(set(), {"b"}) == 0.0


def test_groups_same_product_across_stores_and_separates_variants():
    offers = [
        O("amazon", "Apple iPhone 15 (128 GB) - Black", 69900),
        O("flipkart", "APPLE iPhone 15 (Black, 128 GB)", 66999),
        O("snapdeal", "Apple iPhone 15 128GB Black", 68490),
        O("amazon", "Apple iPhone 15 (256 GB) - Blue", 79900),
        O("flipkart", "APPLE iPhone 15 (Blue, 256 GB)", 76999),
        O("snapdeal", "iPhone 15 Back Cover Transparent", 199),
    ]
    groups = group_offers(offers)
    titles = {g.title: g for g in groups}
    # 128GB group has all three stores
    g128 = next(g for g in groups if "128" in g.title)
    assert g128.store_count == 3
    assert g128.cheapest.store == "flipkart" and g128.cheapest.price == 66999
    assert g128.savings == 69900 - 66999
    assert set(g128.by_store) == {"amazon", "flipkart", "snapdeal"}
    # 256GB group separate
    g256 = next(g for g in groups if "256" in g.title)
    assert g256.store_count == 2
    # cover is alone
    cover = next(g for g in groups if "Cover" in g.title)
    assert cover.store_count == 1
    # ordering: multi-store groups first
    assert groups[0].store_count >= groups[-1].store_count


def test_relevance_and_accessory_detection():
    q = normalize("iphone 15 128gb")
    assert relevance(normalize("Apple iPhone 15 (Black, 128 GB)"), q) == 1.0
    assert relevance(normalize("OnePlus Nord 8GB+128GB Black"), q) == pytest.approx(1 / 3)
    assert is_accessory(normalize("Sparkly Case Compatible with iPhone 15"), q)
    assert not is_accessory(normalize("Apple iPhone 15 (Black, 128 GB)"), q)
    assert not is_accessory(normalize("iPhone 15 Case Clear"), normalize("iphone 15 case"))  # user asked for a case


def test_query_filters_unrelated_and_demotes_accessories():
    offers = [
        O("snapdeal", "BIG WINGS Plain Case Compatible For Apple iPhone 15", 238),
        O("amazon", "OnePlus Nord CE6 | 8GB+128GB | Black", 37999),
        O("amazon", "Apple iPhone 15 (128 GB) - Black", 69900),
        O("flipkart", "Apple iPhone 15 (Black, 128 GB)", 67999),
    ]
    groups = group_offers(offers, query="iphone 15 128gb")
    titles = [g.title for g in groups]
    assert not any("OnePlus" in t for t in titles)          # 1/3 of query words: dropped
    assert "iPhone 15" in groups[0].title and groups[0].store_count == 2
    assert groups[-1].accessory and "Case" in groups[-1].title


def test_exact_match_outranks_partial_match_on_more_stores():
    offers = [
        O("amazon", "SONY WH-ULT900N Wireless Headphones", 16990),
        O("flipkart", "SONY WH-ULT900N Wireless Headphones", 16990),
        O("amazon", "Sony WH-1000XM5 Noise Cancelling Headphones", 28765),
    ]
    groups = group_offers(offers, query="sony wh-1000xm5")
    assert "1000XM5" in groups[0].title


def test_screen_size_does_not_leak_tokens_or_block_grouping():
    t = normalize("Apple iPhone 17e 256 GB: 15.40 cm (6.1″) Display")
    assert "15" not in t and "40" not in t and "1540cm" in t
    a = O("amazon", "Apple iPhone 15 (128 GB) 15.49 cm Display", 69900)
    b = O("flipkart", "Apple iPhone 15 (Black, 128 GB) 15.5 cm", 67999)
    assert group_offers([a, b])[0].store_count == 2


def test_savings_only_compare_across_stores():
    one_store = group_offers([O("amazon", "Sony WH-1000XM5", 26990), O("amazon", "Sony WH-1000XM5 Black", 24990)])[0]
    assert one_store.savings == 0
    two_stores = group_offers([O("amazon", "Sony WH-1000XM5", 26990), O("amazon", "Sony WH-1000XM5 Black", 24990),
                               O("flipkart", "SONY WH-1000XM5", 25990)])[0]
    assert two_stores.savings == 25990 - 24990


def test_by_store_picks_cheapest_per_store():
    offers = [O("amazon", "Sony WH-1000XM5 Headphones", 26990), O("amazon", "Sony WH-1000XM5 Headphones Black", 25990)]
    g = group_offers(offers)[0]
    assert g.by_store["amazon"].price == 25990


def test_empty_input():
    assert group_offers([]) == []


def test_short_query_requires_every_word_and_a_real_word():
    groups = group_offers([
        O("amazon", "Apple iPhone 15 (512 GB) - Black", 89900),
        O("amazon", "OnePlus 15 | 12GB+256GB | Sand Storm", 85999),   # only "15" matches
        O("amazon", "Apple iPhone 17 256 GB: 15.93 cm Display", 99900),  # "iphone" only
        O("vijaysales", "Sparkly Case Compatible with iPhone 15", 499),
    ], query="iphone 15")
    titles = [g.title for g in groups]
    assert any("iPhone 15 (512" in t for t in titles)
    assert not any("OnePlus" in t for t in titles)
    assert not any("iPhone 17" in t for t in titles)
    assert groups[-1].accessory


def test_pro_and_pro_max_and_storage_tiers_are_separate_rows():
    offers = [
        O("amazon", "iPhone 18 Pro (256 GB) - Silver", 164900),
        O("flipkart", "Apple iPhone 18 Pro (Black, 256 GB)", 164900),
        O("amazon", "iPhone 18 Pro Max (256 GB) - Burgundy", 179900),
        O("flipkart", "Apple iPhone 18 Pro max (Silver, 256 GB)", 179900),
        O("amazon", "iPhone 18 Pro (1 TB) - Burgundy", 239900),
        O("amazon", "iPhone 18 Pro Max (2 TB) - Glacier", 329900),
        O("vijaysales", "Apple iPhone 18 (256GB Storage, Black)", 89900),
    ]
    groups = group_offers(offers, query="iphone 18")
    rows = {g.title: g for g in groups}
    assert len(groups) == 5, [g.title for g in groups]
    pro = next(g for g in groups if "Pro (256" in g.title or "Pro (Black, 256" in g.title)
    assert pro.store_count == 2 and all("Max" not in o.title and "max" not in o.title for o in pro.offers)
    assert groups[0].title == "Apple iPhone 18 (256GB Storage, Black)"  # plain model outranks Pro variants


def test_model_suffix_separates_17e_from_17():
    assert not same_product_family(normalize("Apple iPhone 17e 256 GB"), normalize("Apple iPhone 17 256 GB"))
    assert same_product_family(normalize("Apple iPhone 15 (128 GB) A16 Bionic 6 Core"), normalize("APPLE iPhone 15 (Black, 128 GB)"))
    assert same_product_family(normalize("Samsung 139 cm (55 inch) QLED 4K TV"), normalize("Samsung 138 cm 55 inch QLED Ultra HD TV"))


def test_tb_and_gb_are_the_same_spec_family():
    assert not specs_compatible(spec_tokens(normalize("iPhone 18 Pro 1TB")), spec_tokens(normalize("iPhone 18 Pro 256GB")))
    assert specs_compatible(spec_tokens(normalize("Laptop 16GB RAM 1TB SSD")), spec_tokens(normalize("Laptop 16GB 1TB")))


def test_variant_relevance_penalty():
    q = normalize("iphone 18")
    assert relevance(normalize("Apple iPhone 18 (256GB)"), q) == 1.0
    assert relevance(normalize("Apple iPhone 18 Pro (256GB)"), q) == pytest.approx(0.9)
    assert relevance(normalize("Apple iPhone 18 Pro Max (256GB)"), q) == pytest.approx(0.81)
    assert relevance(normalize("Apple iPhone 18 Pro (256GB)"), normalize("iphone 18 pro")) == 1.0


def test_mini_led_is_not_a_mini_variant():
    a = normalize("Samsung 138 cm (55 inch) Ultra HD (4K) Mini LED Smart TV")
    b = normalize("Samsung 55 inch Mini LED 4K Smart TV")
    assert same_product_family(a, b) and "mini" not in a


def test_group_links_through_any_member():
    # C is close to B but not to A; all three are one product via B.
    offers = [
        O("amazon", "Sony WH-1000XM5 Headphones", 26990),
        O("flipkart", "Sony WH-1000XM5 Wireless Noise Cancelling Headphones Black", 25990),
        O("snapdeal", "Sony Wireless Noise Cancelling Headphones WH-1000XM5 Black Over Ear", 27990),
    ]
    assert group_offers(offers)[0].store_count == 3


def test_shared_model_code_links_dissimilar_titles():
    offers = [
        O("amazon", "Sony WH-1000XM5 Best Active Noise Cancelling Wireless Bluetooth Over Ear Headphones with Mic for Phone Calls, 30 Hours Battery", 28765),
        O("vijaysales", "Sony WH-1000XM5 Wireless Industry Leading Noise Canceling Headphones (Black)", 28990),
        O("flipkart", "SONY WH-1000XM6 Wireless Noise Cancellation Headphones", 39990),
    ]
    groups = group_offers(offers, query="sony wh-1000xm5")
    assert groups[0].store_count == 2 and "XM6" not in groups[0].title
    assert len(groups) == 1  # XM6 is a different code and the two-word query demands an exact one


def test_model_codes_ignore_specs_and_resolutions():
    assert model_codes(normalize("Sony WH-1000XM5 30 Hours 4K 256GB 55 inch")) == {"wh1000xm5"}
    assert "138cm" not in model_codes(normalize("Samsung 138 cm TV"))


def test_hyphenated_codes_keep_headphones_and_earbuds_apart():
    offers = [
        O("amazon", "Sony WH-1000XM5 Wireless Noise Cancelling Headphones", 28765),
        O("flipkart", "SONY WF-1000XM5 Noise Cancellation Earbuds", 14999),
        O("vijaysales", "Sony WH-1000XM5 Industry Leading Noise Canceling Headphones", 28990),
        O("amazon", "Sony WH-CH520 Wireless Bluetooth Headphones", 4125),
        O("flipkart", "SONY WH-ULT900N Wireless Noise Cancellation Headphones", 16990),
    ]
    groups = group_offers(offers, query="sony wh-1000xm5")
    assert groups[0].store_count == 2 and all("WH-1000XM5" in o.title for o in groups[0].offers)
    assert not any("WF-1000XM5" in o.title for g in groups for o in g.offers)  # 2-word query, earbuds do not match
    assert not any({"CH520", "ULT900N"} <= {w for o in g.offers for w in o.title.replace("-", " ").split()} for g in groups)


def test_compatible_with_mac_is_not_an_accessory():
    q = normalize("logitech mx master 3s")
    assert not is_accessory(normalize("Logitech MX Master 3S Wireless Mouse compatible with Mac and Windows"), q,
                            "Logitech MX Master 3S Wireless Mouse compatible with Mac and Windows")
    assert is_accessory(normalize("BIG WINGS Plain Cases Compatible For Apple iPhone 15"), normalize("iphone 15"),
                        "BIG WINGS Plain Cases Compatible For Apple iPhone 15")
    assert is_accessory(normalize("Tempered Glass Compatible with Samsung Galaxy S24"), normalize("galaxy s24"),
                        "Tempered Glass Compatible with Samsung Galaxy S24")


def test_same_model_number_merges_verbose_titles():
    offers = [
        O("flipkart", "Logitech MX Master 3s Ergonomic Optical Mouse with Quiet Clicks, 8K DPI, Bluetooth", 7995),
        O("vijaysales", "Logitech MX Master 3S Wireless Performance Mouse (Graphite)", 9999),
        O("flipkart", "Logitech MX Anywhere 2S Wireless Mouse", 2995),
    ]
    groups = group_offers(offers, query="logitech mx master 3s")
    assert groups[0].store_count == 2 and "Anywhere" not in groups[0].title
    assert not groups[0].accessory


def test_glass_is_only_an_accessory_in_a_phrase():
    q = normalize("logitech mx master 3s")
    t = "Logitech MX Master 3S Wireless Performance Mouse, Track on Glass, 8K DPI"
    assert not is_accessory(normalize(t), q, t)
    t2 = "Tempered Glass Screen Protector for iPhone 15"
    assert is_accessory(normalize(t2), normalize("iphone 15"), t2)
    assert not is_accessory(normalize(t2), normalize("iphone 15 tempered glass"), t2)
