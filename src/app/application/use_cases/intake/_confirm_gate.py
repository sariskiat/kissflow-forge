"""app.application.use_cases.intake._confirm_gate -- the approval-token
primitive shared by `forge_approve_spec` and `forge_plan_app` (Stage D
group 8).

Ported from `app.infrastructure.mcp.server`'s own `_mint_approval_token` /
`_APPROVAL_SECRET` (`_content_digest` itself is NOT re-ported here: it lives
once, in `app.application.use_cases.design._artifacts.content_digest`, and
both families import that copy -- `brief_stage_d_common.md`, "the intake use
cases may import the design private modules"). The one change this port
makes on purpose: the secret is no longer a module-level global generated
at import time -- it is `AppResources.approval_secret`, minted ONCE per
process by `app_lifespan` and threaded through to both use cases as a plain
`bytes` config value (never a key pair, never logged, never returned by any
tool). That keeps the exact same guarantee the old module-level secret gave
(`forge_approve_spec` is the only place a token can be minted for a given
spec content) without either use case reaching for process-global state.
"""

from __future__ import annotations

import hashlib
import hmac


def mint_approval_token(secret: bytes, digest: str) -> str:
    """HMAC-SHA256 of a content digest under the process's `approval_secret`
    -- the ONLY value `forge_plan_app` accepts as proof of approval.

    Only `forge_approve_spec`'s own use case calls this; nothing else in the
    intake family ever does, which is the entire point: a caller (or another
    tool) can always recompute `content_digest` for any content they like --
    that function is pure and public knowledge -- but cannot recompute THIS
    without the secret, so a plain content digest can never be mistaken for
    an approval token, however it was obtained.

    Args:
        secret: The process's `AppResources.approval_secret`.
        digest: The content digest to sign.

    Returns:
        The hex-encoded HMAC-SHA256 of `digest` under `secret`.
    """
    return hmac.new(secret, digest.encode("utf-8"), hashlib.sha256).hexdigest()
