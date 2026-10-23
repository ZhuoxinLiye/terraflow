# Scientific report delivery

The paired-water, land-cover and reference-comparison workflow now has an
evidence-bound final report. The Agent selects local data, builds the graph
and requests its execution. The backend checks the resulting measurements
and renders the report from those results. It keeps the original model prose
in `raw_model_response`; it does not claim to verify arbitrary natural language.

Executed input paths are matched against local fixture metadata and STAC
assets. The native `run_result` event and final completion retain full
`report_evidence`, including file hashes, declared checksum checks, dates,
signal scale, source URLs, processing, and item/collection licenses. The
Agent tool receives a compact summary; hashes and class definitions remain
in the native evidence. No network lookup or data download is performed.

For the supported complete chain, the report checks successful execution,
shared thresholds, categorical nearest-neighbour alignment, required source
roles/dates/scale/URLs, declared checksums, area supports, class sums, class
fractions and reference area identities. An inconsistent or incomplete chain
is blocked from delivering statistical conclusions. Other graph families keep
their existing response path. This is a schema-specific arithmetic and source
gate, not proof of sensor comparability or segmentation accuracy.

The final table distinguishes new water divided by class area, new water
divided by all new water, and after-water divided by class area. It reports
exact metadata timestamps, input and threshold scales, nodata and grid details,
and reference support. It treats reference agreement as range differences.
No flood causation, damage, official benchmark score or release readiness is
inferred. Local metadata are declarations; source authenticity and physical
comparability still require separate validation.

Reusable-flow state comes from the actual `propose_after_run` result. A
successful scientific run alone does not imply a save card or published asset.
Scientific-flow wall time and graph tokens exclude planning/report generation;
the final completion separately includes request wall time and service-metered
Agent tokens. Independent inference traces remain necessary for external
accounting verification.

Tests use synthetic measurements and temporary metadata/files. They cover
incorrect denominators, blocked tools, missing dates/sources, checksum changes,
shared-threshold failure, action/timing separation, and live/trailing SSE
evidence propagation. They are not remote-sensing accuracy tests.
