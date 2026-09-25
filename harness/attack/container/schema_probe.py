"""schema_probe: deterministic profile of an RDF environment, placed at
/opt/harness/schema_probe.py. It describes the data; it computes no answer.

  python3 schema_probe.py card <env-dir>
      Per source file: classes and properties used. Ontology rdfs:comment
      text. Label properties (literal properties whose name contains name,
      alias, label or id). For every class that appears in more than one
      source: which source holds the most named nodes (the likely authority),
      and for each other source how many of its names equal an authority
      name, equal another label value of an authority node (e.g. an alias),
      or match nothing. Singleton-class literals (environment-level
      parameters such as a reference date) are listed.

  python3 schema_probe.py check-reach <env-dir> <output-dir>
      reachmini-specific necessary conditions on a solver's output, derived
      from the data without solving: every host name in the output is an
      authority host name; every entry host appears in blast_radius.tsv; an
      entry host that runs as a role in any source (after label resolution)
      reaches at least one role. Exit 1 with the violations, 0 when none.
"""

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

from rdflib import Graph, Literal, RDF, RDFS, URIRef

LABEL_HINTS = ('name', 'alias', 'label', 'id')


def local(term):
    s = str(term)
    return s.rsplit('#', 1)[-1].rsplit('/', 1)[-1]


def load_sources(env):
    env = Path(env)
    sources = {}
    for path in sorted(env.glob('*.owl')) + sorted(env.glob('*.ttl')):
        g = Graph()
        g.parse(path, format='turtle')
        sources[path.name] = g
    return sources


def label_props(g):
    return {p for s, p, o in g if isinstance(o, Literal) and any(h in local(p).lower() for h in LABEL_HINTS)}


def card(env):
    sources = load_sources(env)
    out = {'sources': {}, 'comments': {}, 'identity': {}, 'parameters': []}
    union = Graph()
    for g in sources.values():
        union += g
    for name, g in sources.items():
        out['sources'][name] = {
            'classes': dict(Counter(local(o) for o in g.objects(None, RDF.type))),
            'properties': dict(Counter(local(p) for p in g.predicates() if p != RDF.type))}
    for s, c in union.subject_objects(RDFS.comment):
        out['comments'][local(s)] = str(c)
    labels = label_props(union)
    # roll subclasses up to root classes declared in the ontology
    parent = {c: p for c, p in union.subject_objects(RDFS.subClassOf)}
    def root(cls):
        seen = set()
        while cls in parent and cls not in seen:
            seen.add(cls); cls = parent[cls]
        return cls
    named = defaultdict(lambda: defaultdict(dict))  # root class -> source -> node -> {prop: [values]}
    for src, g in sources.items():
        for node, cls in g.subject_objects(RDF.type):
            values = {local(p): [str(v) for v in g.objects(node, p)] for p in labels if (node, p, None) in g}
            if values:
                named[local(root(cls))][src][node] = values
    for cls, by_src in named.items():
        if len(by_src) < 2:
            continue
        def resolution(ref):
            names = {v for vals in by_src[ref].values() for p, vs in vals.items() if p.lower().endswith('name') for v in vs}
            other = {v for vals in by_src[ref].values() for p, vs in vals.items() if not p.lower().endswith('name') for v in vs}
            table = {}
            for src, nodes in by_src.items():
                if src == ref:
                    continue
                exact = alt = none = 0
                for values in nodes.values():
                    vs = [v for x in values.values() for v in x]
                    if any(v in names for v in vs): exact += 1
                    elif any(v in other for v in vs): alt += 1
                    else: none += 1
                table[src] = {'nodes': len(nodes), 'name_equals_reference_name': exact,
                              'name_equals_other_reference_label': alt, 'unmatched': none}
            return table
        tables = {ref: resolution(ref) for ref in by_src}
        best = max(tables, key=lambda r: (sum(t['name_equals_reference_name'] + t['name_equals_other_reference_label']
                                              for t in tables[r].values()), len(by_src[r])))
        out['identity'][cls] = {
            'nodes_per_source': {src: len(n) for src, n in by_src.items()},
            'label_properties_per_source': {src: sorted({p for v in n.values() for p in v}) for src, n in by_src.items()},
            'best_reference_source': best,
            'resolution_against_best_reference': tables[best],
            'note': 'best reference = the source whose names and other labels resolve the most names used elsewhere'}
    by_class = defaultdict(set)
    for node, cls in union.subject_objects(RDF.type):
        by_class[cls].add(node)
    for cls, nodes in sorted(by_class.items()):
        if len(nodes) == 1:
            node = next(iter(nodes))
            for p, v in sorted(union.predicate_objects(node)):
                if isinstance(v, Literal):
                    out['parameters'].append({'class': local(cls), 'property': local(p), 'value': str(v)})
    return out


def check_reach(env, outdir):
    sources = load_sources(env)
    union = Graph()
    for g in sources.values():
        union += g
    ns = 'http://example.org/reach#'
    name, alias = URIRef(ns + 'name'), URIRef(ns + 'alias')
    inv = [s for s, g in sources.items() if s.startswith('inventory')]
    # with several inventory snapshots, the latest rc:takenOn is authoritative (the ontology says so)
    def taken(src):
        dates = [str(d) for d in sources[src].objects(None, URIRef(ns + 'takenOn'))]
        return max(dates) if dates else ''
    inv.sort(key=taken, reverse=True)
    authority = {}
    if inv:
        g = sources[inv[0]]
        for node in set(g.subjects(name, None)):
            if (node, RDF.type, URIRef(ns + 'Host')) in g or (node, RDF.type, URIRef(ns + 'ExposedHost')) in g:
                n = str(g.value(node, name))
                authority[n] = n
                for a in g.objects(node, alias):
                    authority[str(a)] = n
    auth_graph = sources[inv[0]] if inv else union
    entries = {str(auth_graph.value(h, name)) for h in auth_graph.subjects(RDF.type, URIRef(ns + 'ExposedHost'))}
    runs = set()
    for h, _ in union.subject_objects(URIRef(ns + 'runsAs')):
        n = union.value(h, name)
        if n is not None and str(n) in authority:
            runs.add(authority[str(n)])
    violations = []
    out = Path(outdir)
    rows = {}
    for f in ('exposure_paths.tsv', 'blast_radius.tsv'):
        p = out / f
        rows[f] = [l.split('\t') for l in p.read_text().splitlines() if l.strip()] if p.exists() else None
        if rows[f] is None:
            violations.append(f'missing output {f}')
    names_out = {r[0] for f in rows if rows[f] for r in rows[f]}
    bad = sorted(n for n in names_out if n not in set(authority.values()))
    if bad:
        violations.append(f'{len(bad)} output host names are not authority names, e.g. {bad[:3]}')
    if rows['blast_radius.tsv'] is not None:
        listed = {r[0] for r in rows['blast_radius.tsv']}
        missing = sorted(entries - listed)
        if missing:
            violations.append(f'{len(missing)} entry hosts missing from blast_radius.tsv, e.g. {missing[:3]}')
        for r in rows['blast_radius.tsv']:
            if len(r) >= 3 and r[0] in runs and r[2].strip() in ('0', ''):
                violations.append(f'entry host {r[0]} runs as a role in the data but reports 0 reachable roles')
    return violations


if __name__ == '__main__':
    if len(sys.argv) >= 3 and sys.argv[1] == 'card':
        print(json.dumps(card(sys.argv[2]), indent=1, sort_keys=True))
    elif len(sys.argv) >= 4 and sys.argv[1] == 'check-reach':
        problems = check_reach(sys.argv[2], sys.argv[3])
        print('\n'.join(problems) if problems else 'no invariant violations')
        raise SystemExit(1 if problems else 0)
    else:
        print(__doc__, file=sys.stderr)
        raise SystemExit(2)
