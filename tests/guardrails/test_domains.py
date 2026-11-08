import pytest
from harnessed.testing import ScriptedModel

from browserrig import Agent, AllowedDomains, DomainNotAllowed, browser_plugins


@pytest.mark.parametrize(
    "domains,url",
    [
        ("example.com", "https://example.com/path?q=1"),
        ("example.com", "http://example.com:8080/"),
        ("EXAMPLE.COM", "https://example.com./"),
        ("*.example.com", "https://a.b.example.com/"),
        ("bücher.de", "https://xn--bcher-kva.de/"),
        ("127.0.0.1", "http://127.0.0.1:8000/"),
        ("::1", "http://[::1]:8000/"),
        ((), "about:blank"),
    ],
)
def test_matching_domains_allow_navigation(domains, url):
    assert AllowedDomains(domains).check(url) is None


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com.evil.test/",
        "https://notexample.com/",
        "https://sub.example.com/",
        "https://example.com@evil.test/",
        "https://evil.test@example.com/",
        "https://example.com\\@evil.test/",
        "https://example.com:invalid/",
        "https://example.com\n.evil.test/",
        "file:///tmp/test.html",
        "data:text/html,hello",
        "javascript:void(0)",
        "about:config",
    ],
)
def test_unlisted_or_ambiguous_destinations_are_denied(url):
    with pytest.raises(DomainNotAllowed) as caught:
        AllowedDomains("example.com").check(url)
    assert caught.value.url == url


@pytest.mark.parametrize("domains", [(), ("*.example.com",)])
def test_empty_list_and_subdomain_pattern_do_not_allow_apex(domains):
    with pytest.raises(DomainNotAllowed):
        AllowedDomains(domains).check("https://example.com/")


@pytest.mark.parametrize(
    "domain",
    [
        "",
        "*",
        "https://example.com",
        "example.com/path",
        "example.com:80",
        "foo.*.com",
        "*.127.0.0.1",
        "a..com",
        "-host.test",
        "foo bar.test",
    ],
)
def test_invalid_configuration_fails_before_a_session_opens(domain):
    with pytest.raises(ValueError, match="Invalid allowed domain"):
        AllowedDomains(domain)


def test_optional_plugin_composes_without_changing_defaults():
    guard = AllowedDomains(["example.com", "*.example.com"])
    defaults = browser_plugins()
    assert not any(isinstance(plugin, AllowedDomains) for plugin in defaults)
    composed = browser_plugins(None, guard)
    assert composed[-1] is guard
    assert [type(plugin) for plugin in composed[:-1]] == [
        type(plugin) for plugin in defaults
    ]
    agent = Agent(model=ScriptedModel([]), plugins=[guard])
    assert guard in agent.plugins
