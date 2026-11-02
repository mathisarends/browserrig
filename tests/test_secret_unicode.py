import pytest

from browserrig.secrets.redaction import Redactor


@pytest.mark.parametrize("value", ["Straße-2026", "ofﬁce-PIN", "İstanbul-1234"])
def test_unicode_secrets_are_hidden_in_original_and_transformed_text(value):
    redactor = Redactor()
    redactor.add("pw", value)
    for shown in (value, value.upper(), value.lower(), value.casefold()):
        assert redactor.contains(shown)
        assert redactor.text(f"before {shown} after") == "before {{secret:pw}} after"


def test_casefold_collision_still_registers_each_original_spelling():
    redactor = Redactor()
    redactor.add("first", "STRASSE-2026")
    redactor.add("second", "Straße-2026")
    assert redactor.text("STRASSE-2026 Straße-2026") == (
        "{{secret:first}} {{secret:first}}"
    )


def test_unicode_secrets_preserve_longest_match_and_encoded_redaction():
    redactor = Redactor()
    redactor.add("short", "Straße")
    redactor.add("long", "Straße-2026")
    assert redactor.text("Straße-2026 Straße") == "{{secret:long}} {{secret:short}}"
    assert redactor.text("Stra%C3%9Fe-2026") == "{{secret:long}}"
