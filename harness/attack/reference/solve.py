"""Positive control for reachmini: BFS over the rules stated in the instruction."""
import re
import sys
from collections import deque
from pathlib import Path
from rdflib import Graph, Namespace, RDF, RDFS

RC = Namespace('http://example.org/reach#')
CURRENT = '2031-06-30'
env, out = Path(sys.argv[1]), Path(sys.argv[2])
g = Graph()
for p in [env / 'ontology.owl'] + sorted(x for x in env.glob('*.ttl')):
    g.parse(p, format='turtle')


def norm(name):
    return str(name).lower().split('.')[0]


# snapshots (noise 4): the one with the latest rc:takenOn is authoritative
snapshots = sorted(((str(g.value(sn, RC.takenOn)), sn) for sn in g.subjects(RDF.type, RC.Snapshot)))
latest = snapshots[-1][1] if snapshots else None


def current(node):
    return latest is None or (node, RC.inSnapshot, latest) in g


# names and aliases declared in the inventory map to the inventory name (noise 3)
alias_map = {}
for h in [x for x in g.subjects(RC.alias, None) if current(x)]:
    name = str(next(g.objects(h, RC.name)))
    alias_map[name] = name
    for a in g.objects(h, RC.alias):
        alias_map[str(a)] = name
for env_node in g.subjects(RC.assessmentDate, None):
    CURRENT = str(next(g.objects(env_node, RC.assessmentDate)))


def key(node):
    name = str(next(g.objects(node, RC.name)))
    return alias_map.get(name, norm(name))


def of_class(cls):
    classes = {cls} | set(g.transitive_subjects(RDFS.subClassOf, cls))
    return {s for c in classes for s in g.subjects(RDF.type, c)}


LIMIT = __K__  # the hop limit stated in the task instruction
edges = {}
def add(a, b): edges.setdefault(a, set()).add(b)
for a, b in g.subject_objects(RC.connectsTo): add(('h', key(a)), ('h', key(b)))
for a, b in g.subject_objects(RC.runsAs): add(('h', key(a)), ('r', key(b)))
for d in g.subjects(RDF.type, RC.Delegation):
    if str(next(g.objects(d, RC.validUntil))) >= CURRENT:
        add(('r', key(next(g.objects(d, RC.fromRole)))), ('r', key(next(g.objects(d, RC.toRole)))))
denied = {(key(a), key(b)) for a, b in g.subject_objects(RC.deniedRead)}
for a, b in g.subject_objects(RC.canRead):
    if (key(a), key(b)) not in denied:
        add(('r', key(a)), ('s', key(b)))
sensitive = {key(s) for s in of_class(RC.SensitiveDataStore)}
entries = sorted({key(h) for h in g.subjects(RDF.type, RC.ExposedHost) if current(h)})
out.mkdir(parents=True, exist_ok=True)
paths, blast = [], []
for e in entries:
    dist = {('h', e): 0}; q = deque([('h', e)])
    while q:
        n = q.popleft()
        for m in edges.get(n, ()):
            if m not in dist:
                dist[m] = dist[n] + 1; q.append(m)
    for (t, name), dd in sorted(dist.items()):
        if t == 's' and name in sensitive and dd <= LIMIT:
            paths.append((e, name, dd))
    blast.append((e, sum(t == 'h' for t, _ in dist), sum(t == 'r' for t, _ in dist), sum(t == 's' for t, _ in dist)))
(out / 'exposure_paths.tsv').write_text(''.join('\t'.join(map(str, r)) + '\n' for r in sorted(paths)))
(out / 'blast_radius.tsv').write_text(''.join('\t'.join(map(str, r)) + '\n' for r in blast))
