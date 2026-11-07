## Scope

<!-- What changed, why, and what is deliberately out of scope? -->

## Evidence

<!-- Link or summarize the evidence that justifies this change. For audio/DSP changes, distinguish objective measurements from subjective listening. -->

## Verification

- [ ] Ruff passes
- [ ] mypy passes
- [ ] pytest passes
- [ ] QML offscreen validation passes, if QML / bridge / startup behavior is touched
- [ ] Windows required check passes
- [ ] macOS required check passes

## Manual verification

<!-- Use "Not required" only when the change is genuinely covered by deterministic automation. -->

- [ ] Manual verification completed, or explicitly not required with a reason
- [ ] Windows real-device / installer / GUI verification completed if this change requires it
- [ ] Listening verification completed if this change changes audible behavior

## Audio behavior

- [ ] No audible behavior change
- [ ] Audible behavior changes; objective evidence is attached or linked
- [ ] Audible behavior changes; subjective verification is still required

<!-- Leave only the applicable statement(s) checked. Do not claim naturalness or perceptual improvement from CI or signal metrics alone. -->

## Documentation / governance

- [ ] `docs/CURRENT_STATUS.md` updated if current status, priority, or next step changed
- [ ] Other affected docs / comments updated
- [ ] No stale "current" or "next step" claim was introduced into historical documents

## Risk / rollback

<!-- Main failure modes, compatibility risks, and the simplest rollback path. -->
