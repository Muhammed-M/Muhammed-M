"""Builds the profile card (output/dark_mode.svg and output/light_mode.svg) shown in README.md.

Card layout inspired by Andrew6rant's profile: https://github.com/Andrew6rant

A GitHub Action (.github/workflows/profile-card.yml) runs this daily to refresh
the age and GitHub stats. Edit ABOUT / CONTACT below to change the text.

Environment variables:
    ACCESS_TOKEN  GitHub token that can read your repositories.
                  Leave it unset to preview the card locally with zeroed stats.
    USER_NAME     GitHub username (defaults to Muhammed-M).
"""
import datetime
import hashlib
import html
import json
import os
import time
from pathlib import Path

import requests
from dateutil.relativedelta import relativedelta

USER_NAME = os.environ.get('USER_NAME', 'Muhammed-M')
BIRTHDAY = datetime.date(1999, 11, 1)
HANDLE = 'muhammed@bassiouni'

# (key, value) rows at the top of the card. None draws an empty "." row.
# Dots in a key ("Languages.Real") are drawn like object properties.
# '{age}' is replaced with your current age.
ABOUT = [
    ('OS', 'macOS, Windows, Linux'),
    ('Uptime', '{age}'),
    ('Host', 'TJM Labs Inc.'),
    ('Kernel', 'Software Engineer I'),
    ('IDE', 'VSCode, Jupyter Notebook'),
    None,
    ('Languages.Programming', 'Python, C++, SQL'),
    ('Languages.Computer', 'JSON, YAML, Markdown, LaTeX'),
    ('Languages.Real', 'Arabic, English, German'),
    None,
    ('Stack.AI', 'LLMs, RAG, LangGraph, PyTorch'),
    ('Stack.Backend', 'FastAPI, Docker, AWS, Postgres'),
    None,
    ('Hobbies.Software', 'Automating Boring Daily Tasks'),
    ('Hobbies.Hardware', 'Optimizing Anything With a Queue'),
]

CONTACT = [
    ('Email.Personal', 'mohamed.mahmoud9935@gmail.com'),
    ('LinkedIn', 'muhammed-bassiouni-314469247'),
    ('LeetCode', 'muhammed-m'),
]

THEMES = {
    'dark_mode.svg': {'bg': '#161b22', 'text': '#c9d1d9', 'key': '#ffa657', 'value': '#a5d6ff',
                      'add': '#3fb950', 'del': '#f85149', 'dots': '#616e7f'},
    'light_mode.svg': {'bg': '#f6f8fa', 'text': '#24292f', 'key': '#953800', 'value': '#0a3069',
                       'add': '#1a7f37', 'del': '#cf222e', 'dots': '#c2cfde'},
}

# Paths are relative to this file, so the script works from any directory.
CARD_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = CARD_DIR / 'output'
CACHE_FILE = CARD_DIR / 'cache' / 'loc.json'

LINE_WIDTH = 86     # every row of the card is exactly this many characters (~ README column width)
LEFT_WIDTH = 48     # width of the left column in the two-column stats rows
CHAR_WIDTH = 9.6    # px per character at 16px monospace
LINE_HEIGHT = 20
FIRST_BASELINE = 30
PADDING = 15


# ---------------------------------------------------------------- GitHub API

def graphql(query, **variables):
    for attempt in range(3):
        response = requests.post('https://api.github.com/graphql',
                                 json={'query': query, 'variables': variables},
                                 headers={'Authorization': f"bearer {os.environ['ACCESS_TOKEN']}"},
                                 timeout=60)
        if response.status_code < 500:  # GitHub sometimes 502s on large commit pages; retry those
            break
        time.sleep(5 * (attempt + 1))
    response.raise_for_status()
    body = response.json()
    if body.get('errors'):
        raise RuntimeError(body['errors'])
    return body['data']


REPOS_QUERY = '''
query($login: String!, $affiliations: [RepositoryAffiliation], $cursor: String) {
  user(login: $login) {
    repositories(first: 50, after: $cursor, ownerAffiliations: $affiliations) {
      pageInfo { hasNextPage endCursor }
      nodes {
        nameWithOwner
        stargazerCount
        defaultBranchRef { target { ... on Commit { history { totalCount } } } }
      }
    }
  }
}'''

HISTORY_QUERY = '''
query($owner: String!, $name: String!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    defaultBranchRef { target { ... on Commit {
      history(first: 100, after: $cursor) {
        pageInfo { hasNextPage endCursor }
        nodes { additions deletions author { user { id } } }
      }
    } } }
  }
}'''


def list_repos(affiliations):
    repos, cursor = [], None
    while True:
        page = graphql(REPOS_QUERY, login=USER_NAME, affiliations=affiliations, cursor=cursor)['user']['repositories']
        repos += page['nodes']
        if not page['pageInfo']['hasNextPage']:
            return repos
        cursor = page['pageInfo']['endCursor']


def walk_commits(user_id, name_with_owner):
    """Commits, lines added and lines deleted by you on a repo's default branch."""
    owner, name = name_with_owner.split('/')
    totals = {'commits': 0, 'added': 0, 'deleted': 0}
    cursor = None
    while True:
        history = graphql(HISTORY_QUERY, owner=owner, name=name, cursor=cursor)[
            'repository']['defaultBranchRef']['target']['history']
        for commit in history['nodes']:
            author = commit['author']['user']
            if author and author['id'] == user_id:
                totals['commits'] += 1
                totals['added'] += commit['additions']
                totals['deleted'] += commit['deletions']
        if not history['pageInfo']['hasNextPage']:
            return totals
        cursor = history['pageInfo']['endCursor']


def count_loc(user_id, repos):
    """Walking every commit is slow, so results are cached per repo and only
    recounted when that repo's commit count changes."""
    try:
        cache = json.loads(CACHE_FILE.read_text())
    except FileNotFoundError:
        cache = {}

    fresh = {}
    for repo in repos:
        # Hashed so private repo names never appear in this public file.
        key = hashlib.sha256(repo['nameWithOwner'].encode()).hexdigest()
        branch = repo['defaultBranchRef']
        total = branch['target']['history']['totalCount'] if branch else 0
        if key in cache and cache[key]['total'] == total:
            fresh[key] = cache[key]
        elif total:
            fresh[key] = {'total': total, **walk_commits(user_id, repo['nameWithOwner'])}
        else:
            fresh[key] = {'total': 0, 'commits': 0, 'added': 0, 'deleted': 0}

    CACHE_FILE.parent.mkdir(exist_ok=True)
    CACHE_FILE.write_text(json.dumps(fresh, indent=1))
    return {field: sum(repo[field] for repo in fresh.values()) for field in ('commits', 'added', 'deleted')}


def fetch_stats():
    user = graphql('query($login: String!) { user(login: $login) { id followers { totalCount } } }',
                   login=USER_NAME)['user']
    owned = list_repos(['OWNER'])
    contributed = list_repos(['OWNER', 'COLLABORATOR', 'ORGANIZATION_MEMBER'])
    loc = count_loc(user['id'], contributed)
    return {
        'repos': len(owned),
        'contributed': len(contributed),
        'stars': sum(repo['stargazerCount'] for repo in owned),
        'followers': user['followers']['totalCount'],
        **loc,
        'loc': loc['added'] - loc['deleted'],
    }


# ---------------------------------------------------------------- card layout
# A row is a list of (text, css_class) segments; css_class None uses the default text colour.

def uptime(today):
    diff = relativedelta(today, BIRTHDAY)
    return ', '.join(f"{n} {unit}{'' if n == 1 else 's'}"
                     for n, unit in ((diff.years, 'year'), (diff.months, 'month'), (diff.days, 'day')))


def text_len(row):
    return sum(len(text) for text, _ in row)


def field(key, value, width=LINE_WIDTH, bullet='. '):
    """'. Key.Sub: ....... value', padded with dots to exactly `width` characters."""
    row = [(bullet, 'dots' if bullet == '. ' else None)]
    for i, part in enumerate(key.split('.')):
        if i:
            row.append(('.', None))
        row.append((part, 'key'))
    row.append((':', None))
    dot_count = max(width - len(bullet) - len(key) - len(':') - 2 - len(value), 0)
    row.append((' ' + '.' * dot_count + ' ', 'dots'))
    row.append((value, 'value'))
    return row


def header(title):
    return [(title, None), (' ' + '—' * (LINE_WIDTH - len(title) - 1), None)]


def build_rows(age, stats):
    s = {name: f'{value:,}' for name, value in stats.items()}
    rows = [header(HANDLE)]
    for item in ABOUT:
        rows.append([('. ', 'dots')] if item is None else field(item[0], item[1].replace('{age}', age)))
    rows += [[], header('- Contact')]
    rows += [field(key, value) for key, value in CONTACT]
    rows += [[], header('- GitHub Stats')]

    contributed = [(' {', None), ('Contributed', 'key'), (': ', None), (s['contributed'], 'value'), ('}', None)]
    rows.append(field('Repos', s['repos'], LEFT_WIDTH - text_len(contributed)) + contributed
                + field('Stars', s['stars'], LINE_WIDTH - LEFT_WIDTH, bullet=' | '))
    rows.append(field('Commits', s['commits'], LEFT_WIDTH)
                + field('Followers', s['followers'], LINE_WIDTH - LEFT_WIDTH, bullet=' | '))
    loc = [(' ( ', None), (s['added'] + '++', 'add'), (', ', None), (s['deleted'] + '--', 'del'), (' )', None)]
    rows.append(field('Lines of Code on GitHub', s['loc'], LINE_WIDTH - text_len(loc)) + loc)
    return rows


def render_svg(rows, colors):
    width = round(PADDING + LINE_WIDTH * CHAR_WIDTH + PADDING)
    height = FIRST_BASELINE + len(rows) * LINE_HEIGHT

    lines = []
    for i, row in enumerate(rows):
        if not row:
            continue
        segments = ''.join(f'<tspan class="{css}">{html.escape(text)}</tspan>' if css else html.escape(text)
                           for text, css in row)
        lines.append(f'<tspan x="{PADDING}" y="{FIRST_BASELINE + i * LINE_HEIGHT}">{segments}</tspan>')
    body = '\n'.join(lines)

    c = colors
    return f'''<?xml version='1.0' encoding='UTF-8'?>
<!-- Generated by card/generate.py - edit that file, not this one. -->
<svg xmlns="http://www.w3.org/2000/svg" font-family="ConsolasFallback,Consolas,monospace" width="{width}px" height="{height}px" viewBox="0 0 {width} {height}" font-size="16px">
<style>
@font-face {{
src: local('Consolas'), local('Consolas Bold');
font-family: 'ConsolasFallback';
font-display: swap;
-webkit-size-adjust: 109%;
size-adjust: 109%;
}}
.key {{fill: {c['key']};}}
.value {{fill: {c['value']};}}
.add {{fill: {c['add']};}}
.del {{fill: {c['del']};}}
.dots {{fill: {c['dots']};}}
text, tspan {{white-space: pre;}}
</style>
<rect width="{width}px" height="{height}px" fill="{c['bg']}" rx="15"/>
<text fill="{c['text']}">
{body}
</text>
</svg>
'''


def main():
    if os.environ.get('ACCESS_TOKEN'):
        stats = fetch_stats()
    else:
        print('ACCESS_TOKEN not set: previewing with zeroed stats')
        stats = dict.fromkeys(('repos', 'contributed', 'stars', 'followers',
                               'commits', 'added', 'deleted', 'loc'), 0)

    rows = build_rows(uptime(datetime.date.today()), stats)
    OUTPUT_DIR.mkdir(exist_ok=True)
    for filename, colors in THEMES.items():
        (OUTPUT_DIR / filename).write_text(render_svg(rows, colors), encoding='utf-8')
    print('Updated', ', '.join(f'card/output/{name}' for name in THEMES), 'with', stats)


if __name__ == '__main__':
    main()
