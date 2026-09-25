"""Read only the task's ontology and input bundle; emit a bounded schema inventory.

This script runs inside the benchmark container before the first model action.
It never reads verifier files or answer fixtures.
"""
import collections
import json
import sys
from pathlib import Path

from rdflib import Graph, URIRef
from rdflib.namespace import OWL, RDF, RDFS


def main(directory: Path) -> None:
    ontology = Graph()
    data = Graph()
    sources = sorted(directory.glob("ontology_*.owl"))
    submissions = sorted(directory.glob("*.ttl"))
    if not sources or not submissions:
        raise SystemExit("missing ontology or submission files")
    for path in sources:
        ontology.parse(path, format="turtle")
    for path in submissions:
        data.parse(path, format="turtle")

    prefixes = dict(ontology.namespaces())
    for prefix, iri in data.namespaces():
        prefixes.setdefault(prefix, iri)
    prefixes = {prefix: str(iri) for prefix, iri in prefixes.items() if prefix}

    def qname(term):
        value = str(term)
        matches = [(len(iri), prefix, value[len(iri):]) for prefix, iri in prefixes.items()
                   if value.startswith(iri) and value[len(iri):]]
        if not matches:
            return value
        _, prefix, local = max(matches)
        return f"{prefix}:{local}"

    classes = sorted(qname(s) for s in ontology.subjects(RDF.type, OWL.Class) if isinstance(s, URIRef))
    subclass = sorted([qname(s), qname(o)] for s, o in ontology.subject_objects(RDFS.subClassOf)
                      if isinstance(s, URIRef) and isinstance(o, URIRef))
    properties = sorted(qname(s) for kind in (OWL.ObjectProperty, OWL.DatatypeProperty)
                        for s in ontology.subjects(RDF.type, kind) if isinstance(s, URIRef))
    subproperty = sorted([qname(s), qname(o)] for s, o in ontology.subject_objects(RDFS.subPropertyOf)
                         if isinstance(s, URIRef) and isinstance(o, URIRef))
    replaced = sorted([qname(s), qname(o)] for s, p, o in ontology
                      if str(p).endswith("replacedBy") and isinstance(s, URIRef) and isinstance(o, URIRef))
    domains = sorted([qname(s), qname(o)] for s, o in ontology.subject_objects(RDFS.domain)
                     if isinstance(s, URIRef) and isinstance(o, URIRef))
    ranges = sorted([qname(s), qname(o)] for s, o in ontology.subject_objects(RDFS.range)
                    if isinstance(s, URIRef) and isinstance(o, URIRef))
    observed_properties = collections.Counter(qname(p) for _, p, _ in data)
    observed_types = collections.Counter(qname(o) for _, o in data.subject_objects(RDF.type))
    result = {
        "target_dir": str(directory),
        "ontology_files": [p.name for p in sources],
        "submission_count": len(submissions),
        "ontology_triples": len(ontology),
        "submission_triples": len(data),
        "prefixes": prefixes,
        "classes": classes,
        "subclass": subclass,
        "properties": properties,
        "subproperty": subproperty,
        "replaced_by": replaced,
        "domains": domains,
        "ranges": ranges,
        "observed_properties": sorted(observed_properties.items()),
        "observed_types": sorted(observed_types.items()),
    }
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main(Path(sys.argv[1]).resolve())
