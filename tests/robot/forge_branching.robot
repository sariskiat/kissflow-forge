*** Settings ***
Documentation     Node M acceptance: CONDITIONAL branch routing — the centerpiece this engine was
...               missing (forge_build_workflow's `parallel` was only ever an UNCONDITIONAL
...               and-fork). Builds a 3-way Parallel gated by forge_set_branch_conditions, plus a
...               per-branch GotoTask via forge_add_goto_gate's new `branch_name`, against the LIVE
...               dev tenant (KF_APP only). BLIND: every name below is neutral/synthetic ("Sample
...               ..."/"Tier ..."), no real-app tokens.
...
...               THE REAL PROOF (CLAUDE.md > THE RULE): a branch that never fires looks IDENTICAL
...               to one that works right up until you walk two real items with different values
...               of the deciding field and read back which step each one actually landed on. Test
...               10 is that proof — every earlier step here could pass with the conditions
...               silently inverted, or not wired at all, and still report clean.
...
...               Test 11 is the NEGATIVE control: a value matching NO branch condition. It does
...               not park and does not error — it silently skips the whole Parallel and the item
...               completes with no work done (CLAUDE.md > Conditional routing's fail-open
...               warning). Asserts the OBSERVED outcome only, never a wished-for one.
...
...               Ordered, dependent test cases sharing suite variables (a lifecycle is inherently
...               sequential — RF runs a suite's tests in file order), same pattern as
...               forge_lifecycle.robot. Suite Teardown ALWAYS runs and ALWAYS attempts to delete
...               every artifact this suite created, regardless of which step failed.
Library           Collections
Library           ForgeKeywords.py
Suite Setup       Run Keywords    Load Env File    AND    Connect To Forge Server
Suite Teardown    Delete Everything This Suite Created

*** Variables ***
${PROCESS_NAME}       Sample Branch Process
${FLOW_ID}            ${EMPTY}
${ROLE_ID}            ${EMPTY}
${ROLE_NAME}          ${EMPTY}

*** Test Cases ***
01 Create Sample Process
    [Documentation]    forge_create_process: a scaffolded, publishable draft shell.
    ${result}=    Call Forge Tool    forge_create_process    name=${PROCESS_NAME}
    Result Should Not Error    ${result}    create process
    Dictionary Should Contain Key    ${result}    flow_id
    Set Suite Variable    ${FLOW_ID}    ${result}[flow_id]
    Log    Created process ${FLOW_ID}

02 Harvest Role Members
    [Documentation]    forge_member_batch: same account-level AppRole fallback as
    ...    forge_lifecycle.robot's own step 02 (CLAUDE.md Members first, corrected 2026-08-07).
    ...    Every workflow step below — root AND every branch step — needs this SAME role id as
    ...    its real assignee, or a first submit 500s (membership alone is not enough).
    Skip If    "${FLOW_ID}" == "${EMPTY}"    msg=no flow to grant members on — step 01 failed
    ${result}=    Call Forge Tool    forge_member_batch    target_flow_id=${FLOW_ID}
    Result Should Not Error    ${result}    member batch (harvest+apply)
    Should Not Be Empty    ${result}[role_ids]
    ...    msg=role_ids is EMPTY -- KF_APP now has no grantable AppRole at all; this suite cannot proceed as written
    Should Be Empty    ${result}[missing]
    Set Suite Variable    ${ROLE_ID}    ${result}[role_ids][0]
    Set Suite Variable    ${ROLE_NAME}    ${result}[harvested][0]
    Log    role_ids=${result}[role_ids] harvested=${result}[harvested]

03 Apply Sample Fields
    [Documentation]    forge_apply_fields: the DECIDING field ("Track") plus a Boolean ("Done
    ...    Flag") for the per-branch loop gate.
    ...
    ...    Track is Type Text, not Select: KF_APP's list inventory is EMPTY (checked live —
    ...    ?_application_id=${APP_ID} on the list-inventory route returns 0; CLAUDE.md's own
    ...    "never synthesize a ReferredList wiring" rules out faking one). This is the SAME
    ...    fallback forge_lifecycle.robot's step 03 already documents and uses. A Select-backed
    ...    deciding field, with real list-option literal validation exercised live, remains
    ...    UNVERIFIED on this tenant pending a human wiring at least one real Kissflow List into
    ...    KF_APP — logged here rather than silently glossed over.
    Skip If    "${FLOW_ID}" == "${EMPTY}"    msg=no flow to add fields to — step 01 failed
    ${f1}=    Create Dictionary    name=Track    type=Text    required=${False}
    ${f2}=    Create Dictionary    name=Done Flag    type=Boolean    required=${False}
    ${fields}=    Create List    ${f1}    ${f2}
    ${intake}=    Create List    Track
    ${work}=    Create List    Done Flag
    ${sections}=    Create Dictionary    Intake=${intake}    Work=${work}
    ${result}=    Call Forge Tool    forge_apply_fields
    ...    flow_id=${FLOW_ID}    fields=${fields}    sections=${sections}
    Result Should Not Error    ${result}    apply fields + sections
    Should Be Empty    ${result}[missing]

04 Build Sample Three Way Parallel Workflow
    [Documentation]    forge_build_workflow: Start -> Intake -> Parallel("Route", 3 branches, one
    ...    step each) -> End. This alone is still an UNCONDITIONAL and-fork (every branch would
    ...    run) — test 05 is what makes it conditional. DESTRUCTIVE — wipes the whole Permission
    ...    matrix, hence step 07 re-sets visibility right after this.
    Skip If    "${FLOW_ID}" == "${EMPTY}"    msg=no flow to build a workflow on — step 01 failed
    ${intake_step}=    Create List    Intake    ${ROLE_ID}
    ${steps}=    Create List    ${intake_step}
    ${a1}=    Create List    Handle Alpha    ${ROLE_ID}
    ${branch_a_steps}=    Create List    ${a1}
    ${branch_a}=    Create List    Tier Alpha    ${branch_a_steps}
    ${b1}=    Create List    Handle Beta    ${ROLE_ID}
    ${branch_b_steps}=    Create List    ${b1}
    ${branch_b}=    Create List    Tier Beta    ${branch_b_steps}
    ${g1}=    Create List    Handle Gamma    ${ROLE_ID}
    ${branch_g_steps}=    Create List    ${g1}
    ${branch_g}=    Create List    Tier Gamma    ${branch_g_steps}
    ${branches}=    Create List    ${branch_a}    ${branch_b}    ${branch_g}
    ${parallel}=    Create Dictionary    name=Route    branches=${branches}
    ${roles}=    Create Dictionary    ${ROLE_ID}    ${ROLE_NAME}
    ${result}=    Call Forge Tool    forge_build_workflow
    ...    flow_id=${FLOW_ID}    steps=${steps}    parallel=${parallel}    parallel_after=${0}
    ...    roles=${roles}
    Result Should Not Error    ${result}    build 3-way parallel workflow
    Should Be Empty    ${result}[missing_steps]
    Log    assigned=${result}[assigned] unassigned=${result}[unassigned]

05 Set Sample Branch Conditions
    [Documentation]    forge_set_branch_conditions: THIS is the tool that makes the Parallel from
    ...    step 04 conditional — Track="Alpha" selects Tier Alpha, "Beta" selects Tier Beta,
    ...    "Gamma" selects Tier Gamma. Node M's gap #1 (kfforge.expr.build_branch_condition had
    ...    ZERO callers from the MCP surface) closes here.
    Skip If    "${FLOW_ID}" == "${EMPTY}"    msg=no flow to set branch conditions on — step 01 failed
    ${branch_literals}=    Create Dictionary
    ...    Tier Alpha=Alpha    Tier Beta=Beta    Tier Gamma=Gamma
    ${result}=    Call Forge Tool    forge_set_branch_conditions
    ...    flow_id=${FLOW_ID}    field_name=Track    branch_literals=${branch_literals}
    Result Should Not Error    ${result}    set branch conditions
    Should Be Empty    ${result}[missing]
    ${verified}=    Set Variable    ${result}[verified]
    List Should Contain Value    ${verified}    Tier Alpha
    List Should Contain Value    ${verified}    Tier Beta
    List Should Contain Value    ${verified}    Tier Gamma

06 Add Sample Per Branch Goto Gate
    [Documentation]    forge_add_goto_gate with the NEW `branch_name` — Node M's gap #3
    ...    (add_goto_task always landed the GotoTask last in whatever chain the target's own
    ...    ProcessDef happened to be, with no explicit way to PIN it to one branch). "Handle Beta"
    ...    exists in exactly Tier Beta, so branch_name here is a belt-and-braces assertion of
    ...    intent, not strictly required for disambiguation in THIS suite (see 06b for the case
    ...    where it IS required: a step name that repeats across branches).
    Skip If    "${FLOW_ID}" == "${EMPTY}"    msg=no flow to gate — step 01 failed
    ${result}=    Call Forge Tool    forge_add_goto_gate
    ...    flow_id=${FLOW_ID}    target_activity_name=Handle Beta    field_name=Done Flag
    ...    branch_name=Tier Beta
    Result Should Not Error    ${result}    add per-branch goto gate
    Should Be True    ${result}[verified]
    Should Be Equal As Strings    ${result}[branch_name]    Tier Beta

07 Set Sample Visibility
    [Documentation]    forge_set_visibility: re-applied AFTER forge_build_workflow, which wipes
    ...    every Permission (CLAUDE.md). "Intake" (Track) is owned by [Start, Intake] — Start IS
    ...    the submission form. "Work" (Done Flag) is owned by ALL THREE branches' first step —
    ...    whichever branch actually runs for a given item, Done Flag must be reachable there.
    Skip If    "${FLOW_ID}" == "${EMPTY}"    msg=no flow to set visibility on — step 01 failed
    ${intake_owners}=    Create List    Start    Intake
    ${work_owners}=    Create List    Handle Alpha    Handle Beta    Handle Gamma
    ${owners}=    Create Dictionary    Intake=${intake_owners}    Work=${work_owners}
    ${result}=    Call Forge Tool    forge_set_visibility    flow_id=${FLOW_ID}    owners=${owners}
    Result Should Not Error    ${result}    set visibility
    Should Be Empty    ${result}[missing]

08 Publish Sample Process
    [Documentation]    forge_publish -> Status Live, read back from the flow's OWN metadata
    ...    record (never trust the publish response alone — THE RULE).
    Skip If    "${FLOW_ID}" == "${EMPTY}"    msg=no flow to publish — step 01 failed
    ${result}=    Call Forge Tool    forge_publish    kind=process    flow_id=${FLOW_ID}
    Result Should Not Error    ${result}    publish process
    Should Be Equal As Strings    ${result}[status]    Live

09 Doctor Reports The Process Clean
    [Documentation]    forge_doctor -> 0 problems (assert exact). Runs the SAME rule 2 (branch
    ...    literal validation) and rule 2b (goto condition / branch-local check) this suite's own
    ...    node M changes rely on — a clean report here means the graph doctor itself considers
    ...    the conditional-Parallel + per-branch-goto shape well-formed, independent of whether
    ...    the conditions actually FIRE correctly at runtime (that's test 10).
    Skip If    "${FLOW_ID}" == "${EMPTY}"    msg=no flow to audit — step 01 failed
    ${result}=    Call Forge Tool    forge_doctor    flow_id=${FLOW_ID}
    Log    ${result}
    Result Should Not Error    ${result}    doctor
    Should Be Empty    ${result}[problems]
    Should Be True    ${result}[ok]

10 Walk Two Items With Different Track Values And Show They Diverge
    [Documentation]    THE REAL PROOF (CLAUDE.md > THE RULE): every step above could pass with the
    ...    branch conditions silently inverted, or genuinely absent, and still report clean — a
    ...    branch that never fires looks identical to one that works. This walks TWO real items
    ...    through the SAME published workflow, one with Track=Alpha and one with Track=Beta, and
    ...    reads back (Get Current Step — a DIRECT, non-MCP read of the item's own
    ...    `_current_step`, never an echo of the plan) which concrete step each one actually landed
    ...    on after crossing the conditional Parallel. They must differ, and each must match its
    ...    OWN branch's step name exactly.
    ...
    ...    2 hops per item (CLAUDE.md Item data plane / the two-phase aiid rule): hop "Start" fills
    ...    Track (Intake section is owned by [Start, Intake], so it is already editable/required-
    ...    enforced right there) and submits, landing on "Intake"; hop "Intake" submits again with
    ...    no further fields, which is the hop that crosses the Parallel gateway itself — read
    ...    live, verified 2026-08-07 (node M): the gateway crossing happens for free as part of
    ...    that SAME submit, landing directly on the selected branch's own first step, no separate
    ...    submit for the Parallel node itself.
    Skip If    "${FLOW_ID}" == "${EMPTY}"    msg=no flow to walk — step 01 failed

    ${field_ids}=    Resolve Field Ids    ${FLOW_ID}
    ${id_track}=    Get From Dictionary    ${field_ids}    Track

    ${a_start_values}=    Create Dictionary
    Set To Dictionary    ${a_start_values}    ${id_track}    Alpha
    ${a_hop0}=    Create Dictionary    name=Start    values=${a_start_values}
    ${a_intake_values}=    Create Dictionary
    ${a_hop1}=    Create Dictionary    name=Intake    values=${a_intake_values}
    ${a_steps}=    Create List    ${a_hop0}    ${a_hop1}
    ${a_result}=    Call Forge Tool    forge_simulate_case    flow_id=${FLOW_ID}    steps=${a_steps}
    Result Should Not Error    ${a_result}    walk item A (Track=Alpha)
    Should Be Empty    ${a_result}[failed]
    ${a_step}=    Get Current Step    ${FLOW_ID}    ${a_result}[iid]
    Log    item A (Track=Alpha) landed on step: ${a_step}

    ${b_start_values}=    Create Dictionary
    Set To Dictionary    ${b_start_values}    ${id_track}    Beta
    ${b_hop0}=    Create Dictionary    name=Start    values=${b_start_values}
    ${b_intake_values}=    Create Dictionary
    ${b_hop1}=    Create Dictionary    name=Intake    values=${b_intake_values}
    ${b_steps}=    Create List    ${b_hop0}    ${b_hop1}
    ${b_result}=    Call Forge Tool    forge_simulate_case    flow_id=${FLOW_ID}    steps=${b_steps}
    Result Should Not Error    ${b_result}    walk item B (Track=Beta)
    Should Be Empty    ${b_result}[failed]
    ${b_step}=    Get Current Step    ${FLOW_ID}    ${b_result}[iid]
    Log    item B (Track=Beta) landed on step: ${b_step}

    Should Be Equal As Strings    ${a_step}    Handle Alpha
    ...    msg=item A (Track=Alpha) did not land on Tier Alpha's own step -- branch condition did not fire as intended
    Should Be Equal As Strings    ${b_step}    Handle Beta
    ...    msg=item B (Track=Beta) did not land on Tier Beta's own step -- branch condition did not fire as intended
    Should Not Be Equal As Strings    ${a_step}    ${b_step}
    ...    msg=THE REAL PROOF FAILED: both items landed on the SAME step -- the conditional Parallel did not diverge

11 Walk A No Match Value And Show It Skips The Whole Parallel
    [Documentation]    THE FAIL-OPEN HAZARD (CLAUDE.md > Conditional routing, node M review
    ...    2026-08-07): a value matching NO branch's condition does not park and does not error —
    ...    it silently skips the ENTIRE Parallel and the item completes with NO WORK DONE. This is
    ...    the same fail-open hazard Gate polarity already names for a loop (a blank optional
    ...    Select silently escapes), now confirmed for a switch. This test asserts the OBSERVED
    ...    outcome, not the wished-for one: Track="Zulu" matches none of Tier Alpha/Beta/Gamma's
    ...    own literals, so the item's detail must carry NO `_current_step` KEY AT ALL (found live
    ...    running this exact test — the key is ABSENT, not present with a null value; an earlier
    ...    draft of this test assumed "present as null" from a paraphrase and a real run corrected
    ...    it, exactly the kind of belief this project only trusts after a live check) and
    ...    `_status` must come back "Completed".
    Skip If    "${FLOW_ID}" == "${EMPTY}"    msg=no flow to walk — step 01 failed

    ${field_ids}=    Resolve Field Ids    ${FLOW_ID}
    ${id_track}=    Get From Dictionary    ${field_ids}    Track
    ${z_start_values}=    Create Dictionary
    Set To Dictionary    ${z_start_values}    ${id_track}    Zulu
    ${z_hop0}=    Create Dictionary    name=Start    values=${z_start_values}
    ${z_intake_values}=    Create Dictionary
    ${z_hop1}=    Create Dictionary    name=Intake    values=${z_intake_values}
    ${z_steps}=    Create List    ${z_hop0}    ${z_hop1}
    ${z_result}=    Call Forge Tool    forge_simulate_case    flow_id=${FLOW_ID}    steps=${z_steps}
    Result Should Not Error    ${z_result}    walk item C (Track=Zulu, matches no branch)
    Should Be Empty    ${z_result}[failed]

    ${z_detail}=    Get Item Detail    ${FLOW_ID}    ${z_result}[iid]
    Log    no-match item detail: ${z_detail}
    Dictionary Should Not Contain Key    ${z_detail}    _current_step
    ...    msg=expected NO _current_step key at all (item skipped the whole Parallel) -- if this key now appears the platform's fail-open behavior changed and CLAUDE.md > Conditional routing needs re-verifying
    Should Be Equal As Strings    ${z_detail}[_status]    Completed
    ...    msg=expected the item to have completed with no work done -- see CLAUDE.md Conditional routing's fail-open warning

*** Keywords ***
Delete Everything This Suite Created
    [Documentation]    Suite Teardown. ALWAYS runs, even if earlier steps failed. Archives+deletes
    ...    the process and reports its deletion status via the app-scoped LIST route (never the
    ...    delete response alone — CLAUDE.md > THE RULE), tolerating a suite variable never having
    ...    been set.
    IF    "${FLOW_ID}" != "${EMPTY}"
        ${flow_del}=    Call Forge Tool    forge_delete_flow    kind=process    flow_id=${FLOW_ID}
        Log    flow delete: ${flow_del}
        Run Keyword And Ignore Error
        ...    Should Be True    ${flow_del}[verified]    flow ${FLOW_ID} deletion not verified
    ELSE
        Log    no flow was created — nothing to delete
    END

    Disconnect From Forge Server
