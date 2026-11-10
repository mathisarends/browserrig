"""Prepare and reset the dedicated upstream Docker sites between attempts."""

import argparse
import asyncio
import copy
import json
import re
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, SecretStr

from . import upstream
from .task import load_tasks

DEFAULT_CONFIG = Path(__file__).with_name("environments.json")
DEFAULT_DATA = Path(__file__).resolve().parents[1] / ".browserrig/webarena-data"


class Site(BaseModel):
    url: str
    control_port: int = Field(gt=0, le=65535)
    image: str
    username: str = ""
    password: SecretStr = SecretStr("")


class Environments:
    def __init__(
        self, config: Path = DEFAULT_CONFIG, data_dir: Path = DEFAULT_DATA
    ) -> None:
        self.sites = {
            name: Site.model_validate(value)
            for name, value in json.loads(config.read_bytes()).items()
        }
        self.data_dir = data_dir.resolve()
        for name, site in self.sites.items():
            if site.image != f"am1n3e/webarena-verified-{name}":
                raise ValueError(
                    f"The official reset command requires its default image for {name}"
                )
            url = urlsplit(site.url)
            local = url.hostname == "localhost" or (url.hostname or "").endswith(
                ".localhost"
            )
            if url.scheme != "http" or not local or url.port is None:
                raise ValueError(
                    f"The official local containers require http://localhost:PORT for {name}"
                )

    def for_task(self, sites: tuple[str, ...]) -> "Environments":
        """Cookies ignore ports: give cross-site apps distinct local hostnames."""
        hosts = Counter(urlsplit(self.sites[name].url).hostname for name in sites)
        if len(hosts) == len(sites):
            return self
        isolated = copy.deepcopy(self)
        for name in sites:
            # Preserve GitLab's tested canonical origin; isolate the peer apps.
            if name == "gitlab":
                continue
            parsed = urlsplit(self.sites[name].url)
            if hosts[parsed.hostname] < 2:
                continue
            host = name.replace("_", "-") + ".localhost"
            url = parsed._replace(netloc=f"{host}:{parsed.port}").geturl()
            isolated.sites[name] = self.sites[name].model_copy(update={"url": url})
        return isolated

    def render(self, text: str) -> str:
        for name, site in self.sites.items():
            text = text.replace(f"__{name.upper()}__", site.url.rstrip("/"))
        if re.search(r"__[A-Z_]+__", text):
            raise ValueError(f"Unresolved WebArena URL placeholder: {text}")
        return text

    def evaluator_config(self) -> dict:
        return {
            "environments": {
                f"__{name.upper()}__": {"urls": [site.url]}
                for name, site in self.sites.items()
            },
        }

    async def check(self, sites: set[str], log: Path) -> None:
        """No pulls, resets, model calls or judge calls in preflight."""
        await upstream.command(
            "docker", "info", "--format", "{{.OSType}}", log=log, timeout=20
        )
        await upstream.invoke("--version", log=log, timeout=60)
        for name in sorted(sites):
            await upstream.command(
                "docker",
                "image",
                "inspect",
                self.sites[name].image,
                log=log,
                timeout=20,
            )
        if "map" in sites:
            for suffix in (
                "tile_db",
                "routing_car",
                "routing_bike",
                "routing_foot",
                "nominatim_db",
                "nominatim_flatnode",
                "website_db",
                "tiles",
                "style",
            ):
                await upstream.command(
                    "docker",
                    "volume",
                    "inspect",
                    f"webarena_verified_map_{suffix}",
                    log=log,
                    timeout=20,
                )
        zim = self.data_dir / "wikipedia_en_all_maxi_2022-05.zim"
        if "wikipedia" in sites and (not zim.is_file() or zim.stat().st_size == 0):
            raise ValueError(f"Prepare Wikipedia data in {self.data_dir}")

    async def reset(self, sites: tuple[str, ...], log: Path) -> None:
        """Upstream start recreates each site's container from its baseline image."""
        for name in sorted(sites):
            site = self.sites[name]
            parsed = urlsplit(site.url)
            port = parsed.port
            if port is None:
                raise ValueError(f"An explicit local port is required for {name}")
            arguments = [
                "env",
                "start",
                "--site",
                name,
                "--port",
                str(port),
                "--env-ctrl-port",
                str(site.control_port),
                "--timeout",
                "180",
            ]
            if name == "wikipedia":
                arguments.extend(("--data-dir", str(self.data_dir)))
            await upstream.invoke(*arguments, log=log, timeout=240)
            # Current official images require --base-url; the pinned host CLI only
            # sets the older WA_ENV_CTRL_EXTERNAL_SITE_URL variable on startup.
            await upstream.command(
                "docker",
                "exec",
                f"webarena_verified_{name}",
                "env-ctrl",
                "init",
                "--base-url",
                parsed._replace(path="", query="", fragment="").geturl(),
                log=log,
                timeout=180,
            )

    async def prepare(self, sites: set[str], log: Path) -> None:
        """Explicit setup command: may download large images and map/wiki data."""
        for name in sorted(sites):
            print(f"Preparing {name}: {self.sites[name].image}", flush=True)
            await upstream.command(
                "docker", "pull", self.sites[name].image, log=log, timeout=7200
            )
            if name in {"map", "wikipedia"}:
                await upstream.invoke(
                    "env",
                    "setup",
                    "init",
                    "--site",
                    name,
                    "--data-dir",
                    str(self.data_dir),
                    log=log,
                    timeout=14400,
                )


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check", "prepare"))
    parser.add_argument(
        "--sites", help="Comma-separated sites; default: frozen subset's sites"
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA)
    args = parser.parse_args()
    environments = Environments(args.config, args.data_dir)
    _, tasks = load_tasks()
    sites = (
        set(args.sites.split(","))
        if args.sites
        else {site for task in tasks for site in task.sites}
    )
    unknown = sites - environments.sites.keys()
    if unknown:
        parser.error(f"Unknown sites: {sorted(unknown)}")
    log = DEFAULT_DATA.parent / "webarena-setup.log"
    if args.command == "prepare":
        await environments.prepare(sites, log)
    else:
        await environments.check(sites, log)
    print(f"Ready: {', '.join(sorted(sites))}; log: {log}")


if __name__ == "__main__":
    asyncio.run(main())
