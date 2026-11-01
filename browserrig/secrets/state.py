from dataclasses import dataclass


@dataclass
class SecretsState:
    # Set once a secret reached a page; the page may keep it beyond its field.
    entered: bool = False
    listed: bool = False
