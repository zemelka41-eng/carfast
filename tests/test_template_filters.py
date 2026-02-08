import pytest

from catalog.templatetags.catalog_format import options_to_items


@pytest.mark.parametrize(
    "options,expected",
    [
        (
            {"Двигатель": ["pair", "Двигатель", "Cummins ISD245 50"]},
            [{"type": "pair", "key": "Двигатель", "value": "Cummins ISD245 50"}],
        ),
    ],
)
def test_options_to_items_pair_value(options, expected):
    items = options_to_items(options)
    assert items == expected
    assert all(item.get("value") != "pair" for item in items)


def test_options_to_items_top_level_pair_list():
    """Test that top-level list starting with 'pair' is handled correctly."""
    options = ["pair", "Двигатель", "Cummins ISD245 50"]
    items = options_to_items(options)
    assert len(items) == 1
    assert items[0]["type"] == "pair"
    assert items[0]["key"] == "Двигатель"
    assert items[0]["value"] == "Cummins ISD245 50"
    assert items[0]["value"] != "pair"
    assert "pair" not in str(items[0]["value"])


def test_options_to_items_pair_triplet_list_becomes_pair_item():
    """Test that triplet list ["pair", key, value] becomes pair item with key."""
    options = [["pair", "Двигатель", "Cummins ISD245 50"]]
    items = options_to_items(options)
    assert len(items) == 1
    assert items[0]["type"] == "pair"
    assert items[0]["key"] == "Двигатель"
    assert items[0]["value"] == "Cummins ISD245 50"
    # Verify "pair" does not appear in any output values
    assert items[0]["key"] != "pair"
    assert items[0]["value"] != "pair"
    assert "pair" not in str(items[0]["key"])
    assert "pair" not in str(items[0]["value"])


def test_options_to_items_flat_pair_tokens_parsed():
    """Test that flat sequence with 'pair' markers is parsed correctly."""
    options = ["pair", "Двигатель", "Cummins", "pair", "КПП", "FAST"]
    items = options_to_items(options)
    assert len(items) == 2
    
    # First item
    assert items[0]["type"] == "pair"
    assert items[0]["key"] == "Двигатель"
    assert items[0]["value"] == "Cummins"
    
    # Second item
    assert items[1]["type"] == "pair"
    assert items[1]["key"] == "КПП"
    assert items[1]["value"] == "FAST"
    
    # Verify "pair" does not appear anywhere
    for item in items:
        assert item["key"] != "pair"
        assert item["value"] != "pair"
        assert "pair" not in str(item["key"])
        assert "pair" not in str(item["value"])


def test_options_to_items_incomplete_pair_triplet():
    """Test that incomplete triplet (e.g., ["pair", "key"]) is handled gracefully."""
    options = ["pair", "Двигатель"]
    items = options_to_items(options)
    # Should not crash and should not output "pair"
    for item in items:
        if item.get("type") == "text":
            assert item["value"] != "pair"
        elif item.get("type") == "pair":
            assert item["key"] != "pair"
            assert item.get("value") != "pair"


def test_options_to_items_mixed_pair_and_regular():
    """Test mixed content with pair markers and regular items."""
    options = ["pair", "Двигатель", "Cummins", "Some regular text", "pair", "КПП", "FAST"]
    items = options_to_items(options)
    # Should have 2 pair items and 1 text item
    pair_items = [item for item in items if item.get("type") == "pair"]
    text_items = [item for item in items if item.get("type") == "text"]
    assert len(pair_items) == 2
    assert len(text_items) == 1
    assert text_items[0]["value"] == "Some regular text"
    # Verify "pair" does not appear
    for item in items:
        if item.get("key"):
            assert item["key"] != "pair"
        if item.get("value"):
            assert item["value"] != "pair"
