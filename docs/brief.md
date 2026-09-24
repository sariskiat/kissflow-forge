# Kissflow Forge working brief

## Researcher's view

**Result to check:** one MCP login succeeds only after both an allowed Microsoft Entra user and that same user's valid Kissflow access-key pair are proven. Either credential alone must fail.

**Null baseline:** the current `KissflowOAuthProvider` proves only the Kissflow pair. The reference `image-gen-mcp` `AzureProvider` proves only Entra. Neither alone meets the requested two-gate rule.

**Comparison not used to build the change:** ChatGPT Developer mode documents OAuth with static client credentials, while its official page does not document user-set arbitrary HTTP headers. The existing Kissflow flow already uses static OAuth Client ID and Client Secret fields in desktop clients. Keep that transport rather than add a second header-only setup.

## Decision layer

1. **Truth condition:** Entra identity valid AND Kissflow pair valid. A token minted after only one check is a failure.
2. **Smallest authority:** extend the existing OAuth boundary. Do not add Istio, another proxy, a credential database, or tool arguments carrying secrets.
3. **Literal result:** each person enters their own Kissflow key in the client's OAuth Client ID and Client Secret fields, then completes Entra browser login.
4. **Evaluation first:** tests cover Entra redirect, invalid Entra callback/token, wrong Kissflow secret, valid dual-gate token, refresh, tampering, and absence of raw secrets in token text or logs.
5. **Killed alternative:** arbitrary custom headers are not a shared desktop-client contract. Tool arguments would expose secrets to the model. A shared SRE Kissflow key would remove per-user Kissflow access.
6. **Output contract:** every auth attempt ends as Entra rejected, Kissflow rejected, token minted, or internal error. No request falls outside a counted result.

## User decisions

- Microsoft Entra and Kissflow are separate gates. Both are required.
- Every user supplies their own Kissflow access-key pair.
- The app must not depend on Istio.
- Desktop clients should use their OAuth credential fields where available; no secret is passed as a tool argument.

## Load-bearing choices

- **FastMCP 3.4.7:** the current server and the `image-gen-mcp` auth pattern use the FastMCP 3.x API. The unbounded `fastmcp==3.4.7` check resolved to 4.x and failed at `fastmcp.tools.tool`. A broad 4.x port is rejected for this auth change.
- **One combined provider:** FastMCP accepts one `auth` provider. The combined provider uses `AzureProvider` for Entra and validates the MCP client's static Client ID and Client Secret as the user's Kissflow pair.
- **Sealed pair in the issued token:** reuse the existing shared signing secret and authenticated encryption. Do not store user Kissflow secrets in a new database.

## Build and checks

1. Add a failing dual-gate test before changing auth code.
2. Adapt the proven Entra provider configuration from `image-gen-mcp/app/auth.py`, without its image, quota, IP, or Firestore features.
3. Preserve the current Kissflow pair validation and redirect allowlist.
4. Keep existing non-dev tenant work in `kfforge/client.py` and related tests unchanged.
5. Pin the FastMCP 3.x range wherever runtime installation occurs.
6. Run focused auth tests, the full offline suite, Git diff checks, and an independent security review.
7. Do not commit, push, trigger CI, or deploy without separate approval.

## Measured facts

- `image-gen-mcp` commit `258da57ac1457a430748370a29d5daae360cc367` uses `AzureProvider`; it contains no Istio or `oauth2-proxy` configuration.
- `mcp-server-python-boilerplate` branch `feat-gpt-boilerplate` commit `03bd2f1a045f0be2a8fb612bb2c26eade8113475` contains no auth module.
- FastMCP 3.4.7 exposes one `FastMCP(auth=AuthProvider | None)` slot and supports `AzureProvider` with static OAuth clients.
- Official OpenAI documentation says ChatGPT Developer mode supports OAuth with static credentials, CIMD, or DCR. It documents no arbitrary per-user HTTP-header field in that UI.
- Baseline check with unbounded `fastmcp==3.4.7`: `tests/test_p0_scaffold.py` had 2 failures because `fastmcp.tools.tool` was missing.
- Baseline focused check with `fastmcp==3.4.7`: 255 passed and 3 existing MCP-envelope failures outside the auth seam.

## Final local result

- Two-gate auth tests: 26 passed with FastMCP 3.4.7.
- Full offline suite with inherited `KF_*`, `MCP_*`, `AZURE_*`, and `ALLOWED_EMAIL_*` variables removed: 2269 passed and 31 live tests skipped.
- The first unsanitized full run failed 21 tests because this shell already exported both dev and non-dev Kissflow variables. The sanitized run proved the code path; that first failure remains recorded as an environment warning.
- Auth-file type check, Python compile check, auth/test Ruff check, and `git diff --check` passed. Nothing is staged.
- The security judge found four blockers: concurrent authorization-code replay, concurrent refresh replay, use of unverified Entra claims, and tests that did not reach the Entra gate. The fixes serialize one-replica grants, verify claims before token issue, and exercise each gate independently. Follow-up review confirmed those fixes.
- Docker was not checked because the local daemon is unavailable. No live Entra login, live Kissflow credential check, commit, push, pipeline, or deployment was performed.
- Production use still requires one active replica with the default disk store, a stable shared signing key, real Entra app settings, and an experienced human review of the deployment configuration.

## 2026-09-23 architecture refactor continuation

- Stage D's 61 tools were already merged when this continuation began. The app
  fix round and flow fix round were merged, then Stage E switched `main.py` to
  `create_server()` and removed the old server and client modules. G14 moved the
  live suites to `tests/integration/`. The local G14 check passed: 3,971 tests,
  41 skipped; coverage 96.81%; eight architecture scans at zero; ten
  boilerplate conformance checks passed.
- The Stage E judge found two missing proof checks. The new offline build-order
  test now drives `create_server()` through a fake HTTP transport and checks
  dev-host, headers, and draft-first writes across families. A surface-derived
  test now names the write-order exceptions. The post-fix local check passed:
  3,973 tests, 41 skipped, coverage 97%. This is local evidence, not tenant
  behavior.
- `make verify` now includes the 90% coverage gate. CI runs that target in a
  quality-gate job. The slim CI image installs `make` first. The GitLab pipeline
  itself has not run in this continuation.
- Failed checks kept for audit: one 5,051-pass run failed only because a supplied
  untracked transcript matched the repo's real-app blindness scan; after the
  transcript was held and restored, 5,052 passed. The first Stage E merge run
  stopped on five missing `AppResources.artifacts` type arguments. Its next
  run had five stale boundary-test failures; after fixes, 3,970 passed. The
  first G14 conformance run had two failures (artifact slot and missing test
  layout files); both passed after G14. The live gate first collected 31 tests
  but skipped all 31 because `KF_APP` was unset. A separate template-app run
  reached the dev tenant: two tests passed, one failed because the test treated
  a dictionary response as an object, and one skipped after that failure.
  The sample app from that run was absent from the tenant app list after
  teardown. The live gate remains open.
- Before an HTTP deployment, resolve the two pre-existing caller path risks in
  section 14 of the refactor spec: design `out_dir` writes and
  `forge_create_flow`'s `extra["template_path"]` read. The gateway and the
  current running endpoint have not been verified for this version.
- After the new temporary-app fixtures, `make verify` passed with 96.84%
  coverage. The next live run had five passed, 23 skipped after earlier steps,
  and three failed: lifecycle and branching still treated a dictionary create
  response as an object; page teardown still found the page in its app-scoped
  inventory after delete. Read-only app-list checks found none of the three
  temporary apps after their module teardowns. The page-delete result needs a
  separate check before the live gate can be called green.
- After response-shape fixes, the next full live run reached all 31 tests:
  23 passed and eight failed. Bare process fixtures removed the template's
  unrelated required fields; a local `make verify` then passed with 96.84%
  coverage while the supplied transcripts were held outside the repo and
  restored afterward. The next live run passed 26 and failed five: lifecycle
  doctor flagged the Checklist table, lifecycle page read-back had seven
  FieldMapping nodes where the test expected four, and three item walks
  stopped at Start. The item tool's error omitted the saved cause. A new
  read-only `forge_list_apps` call found zero lifecycle, branching, or page
  temporary apps among nine listed apps. Gate 5 remains red.
- The next live run passed 27 and failed four. The page read-back passed.
  Lifecycle doctor still flagged the Checklist table, and three item walks
  showed the saved cause: Start fill landed, but submit returned 403
  `KISSFLOW_ERROR_050302`. The repo's live findings say a new role must include
  the caller as a user. The following live run passed 26 and failed five:
  the new probe item was attempted before publish in both suites, and the
  three walks still failed. The test setup is being corrected.
- The user identified `N_A00` as the app to inspect. A read-only MCP sweep
  found zero flows there. MCP then created `Forge_Validation_Process_A00`
  as a bare process in `N_A00`; draft read-back had nine nodes and the app
  inventory listed it. A first publish failed with tenant `MetadataError`
  500 despite doctor reporting no problems. After adding a `Request Summary`
  field in a `Request` section and setting Start/Review visibility, doctor
  had zero problems and publish status read back `Live`. The calling user was
  added to the process's AppRole (user count one), and the app was published.
  A live item advanced through Start and Review, then read back as
  `Completed` with `Request Summary` saved. A diagnostic template draft in
  `N_A00` had a red doctor report and was deleted; the app inventory now
  lists one process. Browser rendering is not yet verified.
- A separate MCP `forge_create_template_app` call created and published
  `Forge_Template_Delivery_2026_09_23_A00` and its process; process status
  read back `Live` and 279 graph nodes were checked. Its doctor report still
  has template visibility/required-field problems, so this is not evidence
  of a normal usable template process. The wrong-target app created earlier
  (`Forge_MCP_Delivery_2026_09_23_A00`) and its process were both deleted
  with verified read-backs after the user provided `N_A00`.
- The corrected live suites passed 31/31 on the dev tenant. A separate
  `forge_list_apps` read found zero temporary lifecycle, branching, or page
  apps, while `forge_sweep` still listed only
  `Forge_Validation_Process_A00` in `N_A00`.
- The Stage E Docker image rebuilt successfully. Its stdio MCP server listed
  61 tools, and a Docker `forge_sweep` call returned one process in `N_A00`
  without error. The first 61-tool Docker exercise was invalid as a full
  proof: it logged 8 ok, 0 error, 53 skipped and exited 0 because the runner
  did not unwrap typed MCP replies, so it lost the created app/process ids.
  Two `ExerciseTool` apps left by that run were deleted; a fresh app-list
  read found zero. One process delete timed out after archiving and a retry
  got 400 `KISSFLOW_ERROR_04205`; direct deletion of the already-archived
  process succeeded, then its app was deleted. The MCP retry path is being
  fixed. The 61-tool Docker gate remains open.
- `make verify` attempts after the 31/31 live pass failed in sequence:
  formatting in `tests/live_helpers.py`; then a type error in the new
  `tests/unit/test_live_helpers.py`; then one stale big-picture doctor
  expectation. The last run reached all tests with 96.82% coverage, but was
  red because that one test expected the table-host warning that live doctor
  no longer emits. Code-writer fixes for these three checks landed locally;
  the final full rerun is pending. The two supplied transcripts were held
  only during each blindness scan and restored afterward.
- The persistent template app's process completed a live item walk through
  manager approval, and the computed and user field read-back test passed.
  A fresh read-only sweep on 2026-09-24 found one Live process in each of
  `N_A00` and `Forge_Template_Delivery_2026_09_23_A00`, the template role
  still listed, and no `ExerciseTool` apps. Browser rendering remains untested.
- The Docker 61-tool exercise runs kept these results: round 1 had 8 ok,
  0 error, 53 skipped but exited 0 because the runner lost typed response
  ids; round 2 had 8 ok, 0 error, 53 skipped and exited 1 after fixing that
  exit rule; round 3 had 57 ok, 2 error, 2 skipped and exited 1 because a
  rename collided with an existing field and the item walk assigned a
  different role; round 4 had 59 ok, 0 error, 2 skipped and exited 1.
  Round 4 proved the rename and item walk. A fresh live Copilot read showed
  `conversation_id` null with a status beginning `pending:`. The runner had
  checked exact `pending`, so it called the follow-up skip an upstream failure.
  `forge_share_report` was the other intentional skip: the 61-tool surface
  has no way to create or discover a report id. A runner fix and final Docker
  rerun remain pending.
- Round 5 of the Docker exercise exited 0: 59 ok, 0 error, 2 intentional
  skips. The Copilot check had no conversation id yet after a pending ask;
  report sharing still had no report id to use. The full `make verify` gate
  passed with 96.82% coverage. The 31 live tests passed again. The supplied
  transcripts were restored after the local scan.
- After the final run, a fresh app list found no `ExerciseTool` app. Both
  intended processes still read back `Live`. A later Copilot conversation
  read found zero threads for the harmless probe message, so the follow-up
  check still lacks a real conversation id. The template process's doctor
  report still has 11 inherited section, required-field and visibility
  problems, even though its live item walk and computed/user field read-back
  passed. The browser UI could not be checked: the Chrome tool refused the
  shared profile because another browser instance owns it.
