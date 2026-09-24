# Calling the tools from a Kepler checkout

This applies only when you are working **inside a Kepler checkout** and the
tools are not reachable as tool calls. Every tool is then a plain Python
function in `tools.registry.TOOL_FUNCTIONS`, keyed by the same name its schema
carries, taking the same arguments as keywords.

Run from the checkout root:

```bash
uv run python - <<'EOF'
from tools.registry import TOOL_FUNCTIONS
result = TOOL_FUNCTIONS["compute_pulsar_periodogram"](path="artifacts/psr_b0329_54_lightcurve.ecsv")
print(result.model_dump_json(indent=2, exclude_none=True))
EOF
```

- Each call returns a Pydantic model; `model_dump_json` prints the whole of it,
  preview, artifact paths and warnings included. Read the warnings — they are
  where `peak_does_not_fold`, `listing_truncated` and the other signals
  arrive.
- A result's files are `ArtifactRef`s: usually `result.artifact.path`, or a
  list under `artifacts`. That path is the value to pass as `path=` to the
  next stage.
- A failure is an ordinary result whose `errors` list carries a code and a
  message, not a Python exception. Read it, then change the approach.
- One call is one tool call. Nothing is shared between calls, so pass artifact
  paths along exactly as a tool-calling model would.
- **The `null` rule of `SKILL.md` §5 reads differently here.** In Python the
  uncap value is `None` — the Python object, which is what JSON's `null`
  arrives as. The string `"None"` is still wrong, and omitting the argument
  still takes the capped default.
- Artifacts are written under `KEPLER_ARTIFACT_DIR`, or `artifacts/` relative
  to the directory Python was started in. Starting from the checkout root keeps
  them in one place.
- Remote tools open real connections to the real services. `ADS_DEV_KEY` must
  be set for the ADS tools.

This is how the skill is exercised before the tools are served over MCP; it is
not how a user with an installed Kepler reaches them.
