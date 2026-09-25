"""reachmini: seeded exposure-reachability micro tasks (defensive graph analysis).

A synthetic environment of hosts, roles and data stores is split across
several RDF sources. The question is structural: from which exposed entry
hosts can a sensitive data store be reached, and in how few hops. Three knobs
separate the regime where graph computation should decide the answer from
the regime where interpretation does:

- depth: planted reachability chains of 2..depth hops, with a stated hop
  limit K so some chains end exactly at K and some one hop beyond;
- size: number of hosts (with distractor edges);
- noise 0/1/2: 1 adds policy rules (an explicit deny overrides an allow;
  expired delegations do not count), 2 also spells host and role names
  differently across sources (identity must be normalized).

Expected rows come from the generator's own model, never from parsing its
RDF. A hidden environment (different seed stream) is never shown to the agent.

  python3 harness/attack/reachmini.py --seed 7 --out <dir> [--depth 6] [--size 30] [--noise 1]
"""

import argparse
import json
import random
from collections import deque
from pathlib import Path

NS = 'http://example.org/reach#'
CURRENT_DATE = '2031-06-30'
ONTOLOGY = f"""@prefix rc: <{NS}> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
rc:Host a owl:Class .
rc:ExposedHost a owl:Class ; rdfs:subClassOf rc:Host .
rc:Role a owl:Class .
rc:DataStore a owl:Class .
rc:SensitiveDataStore a owl:Class ; rdfs:subClassOf rc:DataStore .
rc:Delegation a owl:Class .
rc:name a owl:DatatypeProperty .
rc:connectsTo a owl:ObjectProperty ; rdfs:domain rc:Host ; rdfs:range rc:Host .
rc:runsAs a owl:ObjectProperty ; rdfs:domain rc:Host ; rdfs:range rc:Role .
rc:canRead a owl:ObjectProperty ; rdfs:domain rc:Role ; rdfs:range rc:DataStore .
rc:deniedRead a owl:ObjectProperty ; rdfs:domain rc:Role ; rdfs:range rc:DataStore .
rc:fromRole a owl:ObjectProperty ; rdfs:domain rc:Delegation ; rdfs:range rc:Role .
rc:toRole a owl:ObjectProperty ; rdfs:domain rc:Delegation ; rdfs:range rc:Role .
rc:validUntil a owl:DatatypeProperty ; rdfs:domain rc:Delegation ; rdfs:range xsd:date .
"""
COLUMNS = {'exposure_paths.tsv': ['entryHost', 'dataStore', 'minHops'],
           'blast_radius.tsv': ['entryHost', 'reachableHosts', 'reachableRoles', 'reachableDataStores']}

INSTRUCTION = """You are analysing the exposure of a synthetic environment described in RDF/Turtle. `/app/{target}/` is the environment your solution must process; `/app/{example}/` is another environment with the same structure, for reference only.

Create `/app/solve.py`. It takes exactly two arguments, an environment directory and an output directory (for example `python3 /app/solve.py /app/{target} /app/out`), reads `ontology.owl` and every other `.ttl` file in the environment directory, and writes two tab-separated files without headers into the output directory: `exposure_paths.tsv` and `blast_radius.tsv`. Also create `/app/requirements.txt` listing any third-party packages (leave it empty if none). `rdflib` is installed.

Reachability rules. A host typed `rc:ExposedHost` (a subclass of `rc:Host`) is an entry host and counts as reached with 0 hops. Each of these moves costs one hop: from a reached host to a host it `rc:connectsTo`; from a reached host to the role it `rc:runsAs`; from a reached role to another role through a `rc:Delegation` (`rc:fromRole` to `rc:toRole`); from a reached role to a data store it `rc:canRead`.{rules}

`exposure_paths.tsv`: one row `entryHost dataStore minHops` for every entry host and every `rc:SensitiveDataStore` reachable from it within at most {k} hops, where `minHops` is the fewest hops. Use the `rc:name` values of the host and the data store. Sort by entryHost, then dataStore.

`blast_radius.tsv`: one row `entryHost reachableHosts reachableRoles reachableDataStores` for every entry host, counting distinct hosts (including the entry host), roles and data stores (sensitive or not) reachable from it with no hop limit. Sort by entryHost.
"""
RULES_NOISE1 = (" A role never reads a data store it has an `rc:deniedRead` for, even if it also has `rc:canRead` "
                "(an explicit deny overrides an allow). A delegation counts only if its `rc:validUntil` is on or "
                "after `" + CURRENT_DATE + "`.")
RULES_NOISE2 = (" Sources may spell the same name differently: two resources are the same host or role when their "
                "`rc:name` values are equal after lowercasing and removing any domain suffix after the first `.` "
                "(`WEB-01.corp.example` and `web-01` are the same host). Report names in that normalized form.")


def variant(rng, name, noise):
    if noise < 2:
        return name
    return rng.choice([name, name.upper(), f'{name}.corp.example', f'{name.upper()}.internal'])


def build(rng, n_hosts, depth, noise):
    hosts = [f'h-{i:02d}' for i in range(n_hosts)]
    roles = [f'role-{i:02d}' for i in range(max(4, n_hosts // 2))]
    stores = [f'store-{i:02d}' for i in range(max(3, n_hosts // 3))]
    sensitive = set(rng.sample(stores, max(2, len(stores) // 2)))
    exposed = set(rng.sample(hosts, max(2, n_hosts // 6)))
    connects, runs_as, reads, denies, delegations = set(), {}, set(), set(), []
    # planted chains of chosen lengths: exposed host -> hosts -> role -> roles -> sensitive store
    for length in range(2, depth + 1):
        entry = rng.choice(sorted(exposed))
        path_hosts = [entry] + rng.sample([h for h in hosts if h not in exposed], min(len(hosts) - len(exposed), rng.randint(0, max(0, length - 2))))
        for a, b in zip(path_hosts, path_hosts[1:]):
            connects.add((a, b))
        remaining = length - (len(path_hosts) - 1) - 1  # hops left after host hops, minus the final read
        role = runs_as.setdefault(path_hosts[-1], rng.choice(roles))
        remaining -= 1
        chain = [role]
        while remaining > 0:
            nxt = rng.choice(roles)
            delegations.append((chain[-1], nxt, f'2031-{rng.randint(7, 12):02d}-{rng.randint(1, 28):02d}'))
            chain.append(nxt)
            remaining -= 1
        reads.add((chain[-1], rng.choice(sorted(sensitive))))
    # distractors
    for _ in range(n_hosts):
        a, b = rng.sample(hosts, 2)
        connects.add((a, b))
    for h in hosts:
        if h not in runs_as and rng.random() < 0.5:
            runs_as[h] = rng.choice(roles)
    for _ in range(len(roles)):
        reads.add((rng.choice(roles), rng.choice(stores)))
    if noise >= 1:
        for role, store in rng.sample(sorted(reads), max(1, len(reads) // 5)):
            denies.add((role, store))
        for _ in range(len(roles) // 2):
            a, b = rng.sample(roles, 2)
            valid = rng.random() < 0.5
            until = (CURRENT_DATE if rng.random() < 0.3 else f'2031-{rng.randint(7, 12):02d}-{rng.randint(1, 28):02d}') \
                if valid else f'2031-{rng.randint(1, 6):02d}-{rng.randint(1, 28):02d}'
            delegations.append((a, b, until))
    else:
        for _ in range(len(roles) // 2):
            a, b = rng.sample(roles, 2)
            delegations.append((a, b, '2031-12-31'))
    return {'hosts': hosts, 'roles': roles, 'stores': stores, 'sensitive': sensitive, 'exposed': exposed,
            'connects': connects, 'runs_as': runs_as, 'reads': reads, 'denies': denies,
            'delegations': delegations}


def expected(env, k):
    g = {}
    for a, b in env['connects']:
        g.setdefault(('h', a), set()).add(('h', b))
    for h, r in env['runs_as'].items():
        g.setdefault(('h', h), set()).add(('r', r))
    for a, b, until in env['delegations']:
        if until >= CURRENT_DATE:
            g.setdefault(('r', a), set()).add(('r', b))
    for r, s in env['reads']:
        if (r, s) not in env['denies']:
            g.setdefault(('r', r), set()).add(('s', s))
    paths, blast = [], []
    for entry in sorted(env['exposed']):
        dist = {('h', entry): 0}
        queue = deque([('h', entry)])
        while queue:
            node = queue.popleft()
            for nxt in g.get(node, ()):
                if nxt not in dist:
                    dist[nxt] = dist[node] + 1
                    queue.append(nxt)
        for (kind, name), d in sorted(dist.items()):
            if kind == 's' and name in env['sensitive'] and d <= k:
                paths.append([entry, name, d])
        blast.append([entry, sum(1 for t, _ in dist if t == 'h'), sum(1 for t, _ in dist if t == 'r'),
                      sum(1 for t, _ in dist if t == 's')])
    paths.sort(key=lambda r: (r[0], r[1]))
    return {'exposure_paths.tsv': paths, 'blast_radius.tsv': blast}


def write_env(rng, env, d, noise):
    d.mkdir(parents=True, exist_ok=True)
    (d / 'ontology.owl').write_text(ONTOLOGY)
    prefix = f'@prefix rc: <{NS}> .\n@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .\n'
    iri = lambda kind, name, src: f'<http://env.example.org/{src}/{kind}/{name}>'
    # inventory: hosts and stores; network: connections; iam: roles, runsAs, reads, delegations
    inv = [prefix]
    for h in env['hosts']:
        kind = 'rc:ExposedHost' if h in env['exposed'] else 'rc:Host'
        inv.append(f'{iri("host", h, "inv")} a {kind} ; rc:name "{h}" .')
    for s in env['stores']:
        kind = 'rc:SensitiveDataStore' if s in env['sensitive'] else 'rc:DataStore'
        inv.append(f'{iri("store", s, "inv")} a {kind} ; rc:name "{s}" .')
    net = [prefix]
    # with noise 2 the network source names hosts with its own IRIs and spellings
    net_src = 'net' if noise >= 2 else 'inv'
    if noise >= 2:
        for h in env['hosts']:
            net.append(f'{iri("host", h, "net")} a rc:Host ; rc:name "{variant(rng, h, noise)}" .')
    for a, b in sorted(env['connects']):
        net.append(f'{iri("host", a, net_src)} rc:connectsTo {iri("host", b, net_src)} .')
    iam = [prefix]
    iam_src = 'iam' if noise >= 2 else 'inv'
    for r in env['roles']:
        iam.append(f'{iri("role", r, "iam")} a rc:Role ; rc:name "{variant(rng, r, noise)}" .')
    if noise >= 2:
        for h in sorted(env['runs_as']):
            iam.append(f'{iri("host", h, "iam")} a rc:Host ; rc:name "{variant(rng, h, noise)}" .')
    for h, r in sorted(env['runs_as'].items()):
        iam.append(f'{iri("host", h, iam_src)} rc:runsAs {iri("role", r, "iam")} .')
    for r, s in sorted(env['reads']):
        iam.append(f'{iri("role", r, "iam")} rc:canRead {iri("store", s, "inv")} .')
    for r, s in sorted(env['denies']):
        iam.append(f'{iri("role", r, "iam")} rc:deniedRead {iri("store", s, "inv")} .')
    for n, (a, b, until) in enumerate(env['delegations']):
        iam.append(f'<http://env.example.org/iam/delegation/{n}> a rc:Delegation ; rc:fromRole {iri("role", a, "iam")} ; '
                   f'rc:toRole {iri("role", b, "iam")} ; rc:validUntil "{until}"^^xsd:date .')
    (d / f'inventory_{rng.randint(100, 999)}.ttl').write_text('\n'.join(inv) + '\n')
    (d / f'network_{rng.randint(100, 999)}.ttl').write_text('\n'.join(net) + '\n')
    (d / f'iam_{rng.randint(100, 999)}.ttl').write_text('\n'.join(iam) + '\n')


def generate(seed, out, depth=6, size=30, noise=1):
    rng = random.Random(seed)
    out = Path(out)
    k = max(2, depth - 1)  # some planted chains end one hop beyond the limit
    spec = {'seed': seed, 'depth': depth, 'size': size, 'noise': noise, 'k': k, 'columns': COLUMNS, 'rows': {}}
    for rel, n in (('app/env-t', size), ('app/env-e', max(8, size // 2)), ('hidden/env-h', size + size // 2)):
        env = build(rng, n, depth, noise)
        write_env(rng, env, out / rel, noise)
        spec['rows'][rel.split('/')[-1]] = expected(env, k)
    rules = (RULES_NOISE1 if noise >= 1 else '') + (RULES_NOISE2 if noise >= 2 else '')
    (out / 'instruction.md').write_text(INSTRUCTION.format(target='env-t', example='env-e', rules=rules, k=k))
    (out / 'expected.json').write_text(json.dumps(spec, indent=1))
    return out


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--seed', type=int, required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--depth', type=int, default=6)
    parser.add_argument('--size', type=int, default=30)
    parser.add_argument('--noise', type=int, default=1, choices=(0, 1, 2))
    args = parser.parse_args()
    print(generate(args.seed, args.out, args.depth, args.size, args.noise))
