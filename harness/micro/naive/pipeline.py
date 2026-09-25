"""Negative control: concatenate sources only; no identity, recency or subclass handling."""
import sys
from pathlib import Path
from rdflib import Graph
d = Path(sys.argv[1]); g = Graph()
for p in sorted(d.glob('*.owl')) + sorted(x for x in d.glob('*.ttl') if x.name != 'unified.ttl'):
    g.parse(p, format='turtle')
g.serialize(d / 'unified.ttl', format='turtle')
