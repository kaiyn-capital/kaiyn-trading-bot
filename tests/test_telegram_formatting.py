from decimal import Decimal

from app.telegram_formatting import html_bold, html_code, html_escape, html_link, html_pre


def test_html_escape_handles_reserved_characters_and_values():
    assert html_escape('A&B <tag> "quote"') == "A&amp;B &lt;tag&gt; &quot;quote&quot;"
    assert html_escape(None) == ""
    assert html_escape(Decimal("1.2300")) == "1.2300"
    assert html_escape(123) == "123"


def test_html_formatting_helpers_escape_dynamic_content():
    assert html_code("<BTC&USDT>") == "<code>&lt;BTC&amp;USDT&gt;</code>"
    assert html_bold("<b>x</b>") == "<b>&lt;b&gt;x&lt;/b&gt;</b>"
    assert html_pre("line <one>") == "<pre>line &lt;one&gt;</pre>"
    assert (
        html_link('A&B "label"', 'https://example.test/?q="x"&a=1')
        == '<a href="https://example.test/?q=&quot;x&quot;&amp;a=1">A&amp;B &quot;label&quot;</a>'
    )
