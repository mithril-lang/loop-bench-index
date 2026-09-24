# Terminal-Bench 4.0 full-transcript pilot v2

`html-js-filter` was attempted once with GPT-6 Luna at medium reasoning
through OpenRouter/Hermes, using the full-transcript Mithril BPMN runner at
commit `336dea2e79e0cc6f5644faa7e519b23535dd925d`.

| Field | Observed |
|---|---:|
| Terminal-Bench source commit | `452bf305c6daa62fc59061d22133a7cbc7c1572e` |
| Task checksum | `f2680acb8761fc0079d2e52b23c2d3a5619caf8d18a0fa6f9f230f355fded7b9` |
| Model calls / terminal actions | 10 / 10 |
| Provider-reported total tokens | 114,176 |
| Estimated model cost | $0.01581697 |
| Agent execution wall time | 249.735 s |
| Harbor reward file | 0.0 |
| Qualified task outcome | **UNMEASURED** |

The verifier exited before any task assertion because its Python environment
lacked `pytest` (`No module named pytest`). The reward file's zero therefore
cannot be interpreted as a task-solving failure. This pilot proves that the
model loop, isolated container command execution, Mithril BPMN transitions,
artifact creation, and resource accounting run end to end. It does not measure
task accuracy or efficiency against the baseline. The v2 action ontology was
compiled but no per-action OWL/SPARQL inference receipt was produced; that
admission path was added in v3.

Private task instructions, terminal transcript, produced artifact, and
verifier source/output remain in the local Harbor job archive. This public
report contains only task identifiers and aggregate metrics.
