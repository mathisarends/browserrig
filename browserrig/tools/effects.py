from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Effect:
    text: str
    prepared_scroll: bool = False
    break_chain: bool = False
    # The input asked the browser to open a new tab, such as a Ctrl+click on a link.
    opens_tab: bool = False
