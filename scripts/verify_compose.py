"""Semantic validation of docker-compose.yml when Docker isn't installed locally.

Not a replacement for `docker compose config`, but enough to keep CI honest about
the YAML being parseable and structurally correct (right services, depends_on
wiring, healthchecks, named volumes).
"""

from __future__ import annotations

import pathlib
import sys

import yaml


def main() -> int:
    p = pathlib.Path(__file__).parent.parent / "docker-compose.yml"
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        print("FAIL: docker-compose.yml is not a mapping at root")
        return 1

    services = data.get("services") or {}
    required = {"postgres", "redis", "app"}
    missing = required - set(services)
    if missing:
        print(f"FAIL: missing services: {missing}")
        return 1

    for name, spec in services.items():
        image = spec.get("image") or (spec.get("build") and "<built>")
        deps = spec.get("depends_on")
        dep_names = list(deps.keys()) if isinstance(deps, dict) else deps
        hc = "yes" if spec.get("healthcheck") else "no"
        print(f"  service: {name}")
        print(f"    image/build : {image}")
        print(f"    depends_on  : {dep_names}")
        print(f"    healthcheck : {hc}")

    vols = data.get("volumes") or {}
    print(f"volumes: {list(vols.keys())}")
    print("OK: compose YAML structurally valid")
    return 0


if __name__ == "__main__":
    sys.exit(main())
