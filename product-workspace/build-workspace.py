"""Build the one-file project workspace from its editable page sources.

Install the build-only dependency in requirements-documents.txt, then run:
    python3 product-workspace/build-workspace.py
The generated index.html opens and exports offline without a server.
"""
from pathlib import Path
import importlib.util
import json
import re

HERE = Path(__file__).resolve().parent
SRC = HERE / 'src'


def connect_standalone(html, route):
    """Keep existing page URLs useful while pointing to the complete workspace."""
    if 'id="workspace-link-style"' not in html:
        html = html.replace('</head>', '<style id="workspace-link-style">@media print{#workspace-links{display:none!important}}</style></head>', 1)
    navigation = '''<nav id="workspace-links" aria-label="Complete project workspace" style="display:flex;flex-wrap:wrap;gap:8px 20px;padding:12px 24px;border-bottom:1px solid #dedfd5;background:#eeeee7;font:12px/1.6 Avenir,'Segoe UI',sans-serif">
<a href="index.html#__ROUTE__" style="color:#a94029">← Open complete workspace</a><a href="index.html#brief">Product brief</a><a href="index.html#report/overview">Research</a><a href="index.html#strategy/overview">Strategy</a><a href="index.html#poc/overview">POC plan</a></nav>'''.replace('__ROUTE__', route)
    if 'id="workspace-links"' in html:
        return re.sub(r'<nav id="workspace-links".*?</nav>', lambda _: navigation, html, count=1, flags=re.S)
    return re.sub(r'<body([^>]*)>', lambda match: match[0] + navigation, html, count=1)


def run_builder(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), HERE / name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.build()


def build():
    run_builder('build-documents.py')
    run_builder('build-research.py')
    research = json.loads((HERE / 'research-data.json').read_text())
    sources = {
        'workspace': ('index.html', SRC / 'workspace.html', 'Product workspace', []),
        'report': ('research.html', HERE / 'research.html', 'Research report',
                   [('overview', 'Overview')] + [(s['id'], s.get('navTitle', s['title'])) for s in research['sections']] + [('confidence', 'Evidence & gaps'), ('gate', 'Research gate')]),
        'strategy': ('strategy.html', HERE / 'strategy.html', 'Strategy',
                     [('overview', 'Overview'), ('canvas', 'Lean Canvas'), ('positioning', 'Positioning'), ('model', 'Business model'), ('gtm', 'Go-to-market'), ('action', 'Learning plan')]),
        'poc': ('poc-plan.html', HERE / 'poc-plan.html', 'POC implementation',
                [('overview', 'Proposal'), ('scope', 'Scope & output'), ('pipeline', 'Collection'), ('technical', 'Tools & API'), ('storage', 'Storage & refresh'), ('quality', 'Confidence'), ('budget', 'Pricing'), ('delivery', 'Build & acceptance'), ('expansion', 'Expansion'), ('sources', 'Sources')]),
        'archive': ('archive-before-planning-2026-10-25.html', HERE / 'archive-before-planning-2026-10-25.html', 'Archived workspace',
                    [('overview', 'Overview'), ('brief', 'Previous brief'), ('research', 'Previous research'), ('experiments', 'Previous experiments'), ('decisions', 'Previous decisions')]),
    }
    pages = {}
    for key, (filename, path, title, sections) in sources.items():
        html = path.read_text()
        if key in {'report', 'strategy', 'poc'}:
            html = connect_standalone(html, key + '/overview')
            path.write_text(html)
        if key == 'workspace' and 'window.workspaceStateApi' not in html:
            raise RuntimeError('Editable workspace must expose its state API before building.')
        pages[key] = {'file': filename, 'title': title, 'html': html,
                      'sections': [{'id': sid, 'title': label} for sid, label in sections]}
    payload = json.dumps(pages, ensure_ascii=False, separators=(',', ':')).replace('<', '\\u003c')
    html = (SRC / 'shell.html').read_text()
    for token, content in {
        '__SHELL_CSS__': (SRC / 'shell.css').read_text(),
        '__WORKSPACE_PAGES__': payload,
        '__CHILD_BRIDGE_FACTORY__': (SRC / 'child-bridge.js').read_text(),
        '__SHELL_JS__': (SRC / 'shell.js').read_text(),
    }.items():
        html = html.replace(token, content)
    if re.search(r'__(?:SHELL|WORKSPACE|CHILD)_[A-Z_]+__', html):
        raise RuntimeError('Unresolved workspace template token.')
    (HERE / 'index.html').write_text(html)
    print(f'Built one connected index.html with {len(pages)} pages ({len(html.encode()):,} bytes).')


if __name__ == '__main__':
    build()
