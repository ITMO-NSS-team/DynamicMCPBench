# T14 - Real Planning Statistics

## Objective

Upgrade pre-run statistics from rough heuristics into a statistical workbench
that users can trust and learn from.

## Dependencies

- T04
- T11
- T12

## Scope

- Add explicit power curves and "what budget buys you" alternatives.
- Add minimum detectable effect calculations by design type.
- Surface paired vs unpaired assumptions and repeated-attempt dependence caveats.
- Add stratification, coverage, rank-stability planning, and sensitivity
  diagnostics.
- Include multiplicity and missingness policy in planning outputs.
- Keep all assumptions explicit and guide/RAG-cited.

## Out Of Scope

- Post-run inference from actual outcome tensors.
- Changing scoring or generation.

## Allowed Files/Directories

- advisor statistics modules
- v2 statistical fixtures
- tests for statistical calculations

## Required Tests

- Power/MDE curves are monotonic and reproducible.
- Paired and unpaired planning assumptions are distinguishable.
- Rank-stability and slice-coverage diagnostics are deterministic.
- Sensitivity outputs include assumptions and do not overclaim.

## Acceptance Criteria

- Users can inspect why a design is underpowered, what budget would repair it,
  and which claim remains allowed.
- Outputs are strong enough to be the central advisor feature, not decorative
  numbers.
