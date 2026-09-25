"""Positive control for railmini (all difficulties): one canonical resource per
physical point, latest coordinates by record or submission date, WKT
coordinates parsed, and a decimal kV value added to each section."""
import re
import sys
from pathlib import Path
from rdflib import Graph, Literal, Namespace, RDF, RDFS, URIRef, XSD

RL = Namespace('http://example.org/rail#')
d = Path(sys.argv[1])
g = Graph()
for p in sorted(d.glob('*.owl')) + sorted(x for x in d.glob('*.ttl') if x.name != 'unified.ttl'):
    g.parse(p, format='turtle')
point_classes = {RL.OperationalPoint} | set(g.transitive_subjects(RDFS.subClassOf, RL.OperationalPoint))
records = {s for c in point_classes for s in g.subjects(RDF.type, c)}


def date_of(r):
    for v in g.objects(r, RL.reportedOn):
        return str(v)
    for sub in g.objects(r, RL.submittedIn):
        for v in g.objects(sub, RL.issued):
            return str(v)
    return ''


def coords(r):
    lat, lon = next(g.objects(r, RL.lat), None), next(g.objects(r, RL.long), None)
    if lat is not None and lon is not None:
        return lat, lon
    for text in g.objects(r, RL.coordinateText):
        m = re.match(r'\s*POINT\(\s*(\S+)\s+(\S+)\s*\)', str(text))
        if m:
            return Literal(m.group(2), datatype=XSD.decimal), Literal(m.group(1), datatype=XSD.decimal)
    return None


groups = {}
for r in records:
    for op in g.objects(r, RL.opId):
        groups.setdefault(re.sub(r'[\s-]', '', str(op)).upper(), set()).add(r)
for pid, recs in groups.items():
    c = URIRef('urn:physical:' + pid)
    g.add((c, RDF.type, RL.OperationalPoint))
    g.add((c, RL.opId, Literal(pid)))
    for r in recs:
        for country in g.objects(r, RL.inCountry):
            g.add((c, RL.inCountry, country))
    dated = [(date_of(r), r) for r in recs if coords(r)]
    if dated:
        lat, lon = coords(max(dated, key=lambda x: x[0])[1])
        g.add((c, RL.lat, lat))
        g.add((c, RL.long, lon))
    for prop in (RL.startsAt, RL.endsAt):
        for r in recs:
            for s in g.subjects(prop, r):
                g.add((s, prop, c))
for s, v in list(g.subject_objects(RL.nominalVoltage)):
    m = re.match(r'\s*([\d.]+)\s*(kV|V)\b', str(v))
    if m and v.datatype is None:
        kv = float(m.group(1)) / (1000 if m.group(2) == 'V' else 1)
        g.add((s, RL.nominalVoltage, Literal(f'{kv:.4f}', datatype=XSD.decimal)))
g.serialize(d / 'unified.ttl', format='turtle')
