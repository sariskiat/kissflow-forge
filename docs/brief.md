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
