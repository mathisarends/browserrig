from browserrig.core.options import Options


class TabInfo(Options):
    id: str
    url: str
    title: str
    active: bool = False
