import requests
import sys
import re
from typing import Tuple, Optional
from packaging import version, specifiers
import re
import traceback


import re
from typing import Tuple, Optional


def parse_pip_spec(spec: str) -> Tuple[str, Optional[str], Optional[str]]:
    match = re.match(r'([A-Za-z0-9_-]+)(\[[^\]]+\])?(.*)', spec)
    if match:
        package_name = match.group(1).strip()
        extras = match.group(2)[1:-1] if match.group(2) else None

        version_spec = None
        if match.group(3):
            version_match = re.match(r'\(?([^\)]+)\)?', match.group(3).strip())
            if version_match:
                version_spec = version_match.group(1).strip()

        return package_name, extras, version_spec
    else:
        raise ValueError(f"Invalid package spec: {spec}")


def fetch_package_versions(package_name):
    url = f"https://pypi.org/pypi/{package_name}/json"
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        versions = data["releases"].keys()
        print(f"Available versions of '{package_name}':")
        return list(versions)
    except requests.RequestException as e:
        print(f"Error fetching package versions: {e}")
        return []


def fetch_required_dist(package_name, ver):
    url = f"https://pypi.org/pypi/{package_name}/{ver}/json"
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()

        requires_dist = data.get('info', {}).get('requires_dist', [])
        
        if not requires_dist:
            print(f"No dependencies found for {package_name} version {ver}.")
            return []

        dependencies = []
        for dist in requires_dist:
            dist = dist.split(";")

            dist_extra = None
            if len(dist) > 1:
                match = re.match(r'extra\s*==\s*"([^"]*)"', dist[1].strip())
                if match:
                    dist_extra = match.group(1).strip()

            match = re.match(r'([^=<>!~]+)(.*)', dist[0].strip())

            if match:
                pkg_name = match.group(1).strip()
                ver_spec = match.group(2).strip() or None

                if ver_spec is not None and ver_spec.endswith(')'):
                    pass

                dependencies.append((pkg_name, dist_extra, ver_spec))

        # print(f"Processed dependencies for {package_name} version {ver}: {dependencies}")
        return dependencies
    except requests.RequestException as e:
        print(f"Error fetching required distribution info: {e}")
        return []


def filter_versions(versions, spec):
    try:
        specifier = specifiers.SpecifierSet(spec) if spec else specifiers.SpecifierSet()

        res = []
        for v in versions:
            match = re.match(r'^([0-9.]+[0-9])', v)
            if match:
                if match.group(1) in specifier:
                    res.append(v)

        return res
    except Exception as e:
        print(f"ERROR: {e}")
        traceback.print_exc()


def filter_extras(required_dist, extras):
    return [x for x in required_dist if x[1] is None or x[1] == extras]


resolved = {}


def resolve_pip_spec(pkg_name, extras, ver):
    global resolved
    required_dist = fetch_required_dist(pkg_name, ver)
    resolved[(pkg_name, extras, ver)] = required_dist
    return filter_extras(required_dist, extras)


def best_match(pkg_name, version_spec):
    global resolved
    candidate_versions = fetch_package_versions(pkg_name)

    if version_spec:
        candidate_versions = filter_versions(candidate_versions, version_spec)

    if candidate_versions:
        return max(candidate_versions, key=version.parse)
    else:
        print("No matching versions found.")
        return None


def resolve_recursively(items):
    worklist = items

    while worklist:
        pkg_name, extras, version_spec = worklist[0]
        worklist = worklist[1:]
        ver = best_match(pkg_name, version_spec)

        if (pkg_name, extras, ver) in resolved:
            continue

        if ver is not None:
            nexts = resolve_pip_spec(pkg_name, extras, ver)
            worklist += nexts


def main():
    global resolved
    if len(sys.argv) < 2:
        print("Usage: python script.py <package_name>")
        sys.exit(1)

    pkg_name, extras, version_spec = parse_pip_spec(sys.argv[1])
    ver = best_match(pkg_name, version_spec)
    required_dist = resolve_pip_spec(pkg_name, extras, ver)
    resolve_recursively(required_dist)

    print(f"Requirements: {resolved}")


if __name__ == "__main__":
    main()