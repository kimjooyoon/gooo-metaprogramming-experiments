# Measurement method

Each `experiment_id` is a distinct pairing of one semantic intent and one code
assembly route. The ten intents are evaluated over the fixed 25-value domain
from -12 through 12. The reference evaluator is the ordered rule list in
`plan-v1.json`; the Laya decision request receives the task and route
descriptions but not that rule list or expected outputs.

## Completeness vector

- `behavioral_completeness`: matching outputs / all 25 domain points.
- `rule_clause_completeness`: complete reachable rule/default clauses /
  reachable clauses. This reports branch omissions without counting many
  neighboring points as independent requirements.
- `construct_coverage`: expected Go AST constructs present / expected
  constructs. Expected constructs depend on the selected route and task shape.
- `construct_precision`: expected constructs / recognized constructs emitted.
- `compiled` and `deterministic`: separate hard checks; neither is averaged
  into a quality percentage.

The input domain is deliberately bounded. Agreement here is not a proof over
all Go integers. In particular, `finite_domain_map` is only complete over the
declared domain and intentionally returns its fallback outside that range.

## Selection protocols

For each of the ten task descriptions, `gooo decide` returns top-1 and a
probability distribution over ten routes. The runner also makes a stable
probability-weighted sample from a seed bound to the task, request digest, and
model revision. Replaying the same snapshot chooses the same route. Every
candidate is compiled and scored before aggregate comparisons are reported;
the best candidate is an oracle ceiling, not an available online policy.

## Limits

There are 100 candidate treatments but ten Laya calls, one per intent. The
corpus is a small, hand-authored pilot and is not a model accuracy estimate.
Laya selects only a construction pattern. The deterministic lowering code
emits the executable helper functions; the current stable Gooo language does
not yet express those bodies.
