"""Resolve the latest agent versions on the runner, where gh is authenticated.

The install scripts used to ask api.github.com for the latest release from the
EC2 host, unauthenticated. On 8 Nov 2026 a GitHub incident timed those calls
out and nine jobs died. Resolving here with the workflow's token and handing
the result to the host as an environment variable keeps the hosts off the
unauthenticated API; the scripts still fall back to it when nothing is passed.

Usage: python3 tools/agent_versions.py vector [otelcol ...]
Prints one NAME=value line per vendor for `eval` or an ssh command prefix.
"""
import json
import re
import sys

import gh_release

gh = gh_release.run

SEMVER = re.compile(r'^\d+\.\d+\.\d+$')
V_SEMVER = re.compile(r'^v\d+\.\d+\.\d+$')


def _latest_tag(endpoint, pattern, strip_v):
    def pick(data):
        tag = data['tag_name']
        if not pattern.fullmatch(tag):
            raise ValueError(f'{endpoint}: unexpected release tag {tag!r}')
        return tag[1:] if strip_v else tag
    return endpoint, pick


def _vector(data):
    stable = [r['tag_name'][1:] for r in data
              if not r['draft'] and not r['prerelease'] and V_SEMVER.fullmatch(r['tag_name'])]
    if not stable:
        raise ValueError('No stable Vector release found')
    return max(stable, key=lambda v: tuple(int(p) for p in v.split('.')))


VENDORS = {
    'vector': ('VECTOR_VERSION', 'repos/vectordotdev/vector/releases?per_page=100', _vector),
    'otelcol': ('OTELCOL_VERSION',
                *_latest_tag('repos/open-telemetry/opentelemetry-collector-releases/releases/latest', V_SEMVER, True)),
    # bindplane asset names carry the v prefix, so keep it.
    'bindplane': ('BINDPLANE_VERSION',
                  *_latest_tag('repos/observIQ/bindplane-otel-collector/releases/latest', V_SEMVER, False)),
    'fluentd': ('FLUENT_PACKAGE_VERSION',
                *_latest_tag('repos/fluent/fluent-package-builder/releases/latest', V_SEMVER, True)),
}


def resolve(vendor, gh=None):
    name, endpoint, pick = VENDORS[vendor]
    data = json.loads((gh or globals()['gh'])('api', endpoint))
    return name, pick(data)


def main(argv):
    lines = []
    for vendor in argv:
        try:
            name, value = resolve(vendor)
        except Exception as error:  # the host falls back to api.github.com itself
            print(f'agent_versions: could not resolve {vendor} on the runner: {error}', file=sys.stderr)
            return 1
        lines.append(f'{name}={value}')
    for line in lines:
        print(line)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
