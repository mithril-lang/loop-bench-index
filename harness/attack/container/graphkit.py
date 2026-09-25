"""graphkit: small, task-agnostic helpers placed at /opt/harness/graphkit.py.

    import sys; sys.path.insert(0, '/opt/harness'); import graphkit as gk

    g = gk.load_turtle(['/app/env/ontology.owl', *gk.files('/app/env', '*.ttl')])
    gk.instances(g, cls_iri)            # subjects typed cls or any rdfs:subClassOf descendant
    gk.pairs(g, prop_iri)               # (subject, object) for a property
    gk.literal(g, node, prop_iri)       # first literal value as str, or None
    dist = gk.bfs(adjacency, start)     # {node: hops}, start at 0; adjacency: {node: iterable}
    gk.within(dist, k)                  # nodes with 1 <= hops <= k

It knows nothing about any task's rules: it does not normalize names, apply
policies or pick edge types. Those remain the solver's decisions.
"""
from collections import deque
from pathlib import Path


def files(directory, pattern):
    return sorted(str(p) for p in Path(directory).glob(pattern))


def load_turtle(paths):
    from rdflib import Graph
    g = Graph()
    for p in paths:
        g.parse(p, format='turtle')
    return g


def instances(g, cls_iri):
    from rdflib import RDF, RDFS, URIRef
    root = URIRef(cls_iri)
    classes = {root} | set(g.transitive_subjects(RDFS.subClassOf, root))
    return {s for c in classes for s in g.subjects(RDF.type, c)}


def pairs(g, prop_iri):
    from rdflib import URIRef
    return list(g.subject_objects(URIRef(prop_iri)))


def literal(g, node, prop_iri):
    from rdflib import URIRef
    for value in g.objects(node, URIRef(prop_iri)):
        return str(value)
    return None


def bfs(adjacency, start):
    dist = {start: 0}
    queue = deque([start])
    while queue:
        node = queue.popleft()
        for nxt in adjacency.get(node, ()):
            if nxt not in dist:
                dist[nxt] = dist[node] + 1
                queue.append(nxt)
    return dist


def within(dist, k):
    return {n for n, d in dist.items() if 1 <= d <= k}
