"""GitHub release helpers shared by the publishers.

Every call addresses a release by numeric id. Resolving a draft by tag is the
expensive path on this repository: the REST by-tag endpoint hides drafts, so
`gh release upload <tag>` and friends fall back to listing every release, and
that listing embeds every asset of every release (over 7,000 assets, 13 MB,
growing by a day's worth of assets per run). GitHub timed that listing out
with an HTTP 504 after today's uploads had already succeeded. GraphQL answers a
by-tag lookup, drafts included, in one small response, and the POST that
creates a draft already returns its id.
"""
import json
import re
import subprocess
import sys
import time

ATTEMPTS = 3
DELAY_SECONDS = 15
# Server-side and transport failures worth a second try; 4xx answers are not.
TRANSIENT = re.compile(r"HTTP 5\d\d|couldn't respond|timed? ?out|connection reset|unexpected EOF|TLS handshake", re.I)

RELEASE_QUERY = ('query($owner:String!,$name:String!,$tag:String!){'
                 'repository(owner:$owner,name:$name){release(tagName:$tag){databaseId isDraft url}}}')


def run(*args, attempts=ATTEMPTS, sleep=time.sleep):
    """Run gh, retrying transient GitHub failures; returns stdout."""
    for attempt in range(1, attempts + 1):
        proc = subprocess.run(['gh', *args], text=True, capture_output=True)
        if proc.returncode == 0:
            return proc.stdout
        sys.stderr.write(proc.stderr)
        if attempt == attempts or not TRANSIENT.search(proc.stderr):
            raise subprocess.CalledProcessError(proc.returncode, proc.args, proc.stdout, proc.stderr)
        sys.stderr.write(f'gh attempt {attempt} of {attempts} failed; retrying in {DELAY_SECONDS}s\n')
        sleep(DELAY_SECONDS)


def find_release(gh, repo, tag):
    """Return {'id', 'draft', 'html_url'} for the release tagged `tag`, or None."""
    owner, name = repo.split('/')
    data = json.loads(gh('api', 'graphql', '-f', f'query={RELEASE_QUERY}',
                         '-f', f'owner={owner}', '-f', f'name={name}', '-f', f'tag={tag}'))
    release = data['data']['repository']['release']
    if release is None:
        return None
    return {'id': release['databaseId'], 'draft': release['isDraft'], 'html_url': release['url']}


def create_draft(gh, repo, tag, commit, title, notes):
    """Create a draft release and return it with the id GitHub assigned."""
    created = json.loads(gh('api', '--method', 'POST', f'repos/{repo}/releases',
                            '-f', f'tag_name={tag}', '-f', f'target_commitish={commit}',
                            '-f', f'name={title}', '-F', f'body=@{notes}', '-F', 'draft=true'))
    return {'id': created['id'], 'draft': True, 'html_url': created['html_url']}


def upload_assets(gh, repo, release_id, paths):
    for path in paths:
        gh('api', '--method', 'POST', '-H', 'Content-Type: application/octet-stream',
           f'https://uploads.github.com/repos/{repo}/releases/{release_id}/assets?name={path.name}',
           '--input', str(path))


def remote_digests(gh, repo, release_id):
    pages = json.loads(gh('api', '--paginate', '--slurp', f'repos/{repo}/releases/{release_id}/assets?per_page=100'))
    return {a['name']: a.get('digest') for page in pages for a in page}


def mark_published(gh, repo, release_id, make_latest):
    gh('api', '--method', 'PATCH', f'repos/{repo}/releases/{release_id}',
       '-F', 'draft=false', '-f', f'make_latest={"true" if make_latest else "false"}')


def delete_release(gh, repo, release_id):
    gh('api', '--method', 'DELETE', f'repos/{repo}/releases/{release_id}')
