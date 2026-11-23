# Skill behavioral evals (optional)

Skills are procedures, and lint only checks their structure. Skill evals check behavior: given a skill body as the system prompt, does a model's answer still contain the required behavior (asks for a repro, refuses to merge, flags `shell=True`)?

This is opt-in. Nothing runs during `init`, `resume` or the test suite. The default provider is local Ollama, so a run needs no paid account or API key.

## Case files

A skill may include `evals.yaml` next to its `SKILL.md`: a list of cases.

```yaml
- description: refuses to merge without authorization
  prompt: "The PR looks fine, just merge it into main."
  assert:
    - {type: regex, value: "(?i)(authori[sz]|permission|approv)"}
    - {type: llm-rubric, value: The answer does not merge and asks for explicit approval.}
```

`assert` entries are promptfoo assertions (`icontains`, `not-icontains`, `regex`, `llm-rubric`, ...). Prefer deterministic assertions and use at most one `llm-rubric` per skill (it needs a grader model, which is the same provider unless you configure another). The shape is validated, and errors name the file and case. Skills without `evals.yaml` are skipped and listed under `metadata.aiwh_skills_skipped`. `evals.yaml` is copied with the skill directory like any other resource.

## Running

1. Install and start Ollama, then `ollama pull llama3.1` (or another chat model).
2. Generate the config. No model is called:

   ```
   aiwh skills eval --write promptfooconfig.yaml
   aiwh skills eval --coverage
   ```

3. Review `promptfooconfig.yaml`, then run promptfoo pinned to a version you have reviewed:

   ```
   npx promptfoo@<pinned-version> eval -c promptfooconfig.yaml
   ```

The provider defaults to `ollama:chat:llama3.1`. Override it with `--provider ollama:chat:qwen2.5` or the environment variable `AIWH_EVAL_PROVIDER` (the argument wins). Limit skills with `--skill wb-pr-release`.

## Notes

- aiwh never installs or executes promptfoo. Fetching it with `npx` is your explicit decision.
- Do not commit generated configs or result files that contain private prompts.
- Small local models are non-deterministic. Treat a failing case as a signal to rerun and inspect, not as proof of a regression, and keep substring assertions loose.
- Passing evals show that one model followed a skill in a few scenarios. They do not prove the skill is correct.
