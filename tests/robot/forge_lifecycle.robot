*** Settings ***
Documentation     Node G acceptance: ONE full build-through-teardown lifecycle of a process,
...               against the LIVE dev tenant (KF_APP only — see kfforge/server.py forge_* tools).
...               BLIND: every name below is neutral/synthetic ("Sample ..."), no real-app tokens.
...
...               Ordered, dependent test cases sharing suite variables (a lifecycle is
...               inherently sequential — RF runs a suite's tests in file order). Each numbered
...               test corresponds 1:1 to a step in the Node G build spec. Suite Teardown ALWAYS
...               runs and ALWAYS attempts to delete every artifact this suite created, regardless
...               of which step failed.
Library           Collections
Library           ForgeKeywords.py
Suite Setup       Run Keywords    Load Env File    AND    Connect To Forge Server
...               AND    Set App Id From Env
Suite Teardown    Delete Everything This Suite Created

*** Variables ***
${PROCESS_NAME}       Sample Intake Process
${PAGE_NAME}          Sample Intake Hub
${FLOW_ID}            ${EMPTY}
${PAGE_ID}            ${EMPTY}
${APP_ID}             ${EMPTY}
${ASSIGNEE_ROLE_ID}    ${EMPTY}
${ASSIGNEE_ROLE_NAME}    ${EMPTY}

*** Test Cases ***
01 Create Sample Process
    [Documentation]    forge_create_process: a scaffolded, publishable draft shell.
    ${result}=    Call Forge Tool    forge_create_process    name=${PROCESS_NAME}
    Result Should Not Error    ${result}    create process
    Dictionary Should Contain Key    ${result}    flow_id
    Set Suite Variable    ${FLOW_ID}    ${result}[flow_id]
    Log    Created process ${FLOW_ID}

02 Harvest Role Members
    [Documentation]    forge_member_batch: with no sibling flow in KF_APP to harvest members
    ...    from, grants the app's OWN AppRoles instead, discovered at the ACCOUNT level
    ...    (CLAUDE.md Members first, corrected 2026-08-07) — Role="DataAdmin",
    ...    Permission=["InitiateItems"], the exact grant proven live to let the initiator submit
    ...    their own draft (Permission=[] 200s the grant but still refuses the initiator).
    ...
    ...    `role_ids`/`harvested` are EXPECTED non-empty on this tenant (2 AppRoles scoped to
    ...    KF_APP) — asserted EXPLICITLY, not just logged: the day this tenant has zero grantable
    ...    AppRoles again, this test must change colour (fail loudly) rather than silently mean
    ...    something completely different — steps 05's assignee wiring and 14's completion walk
    ...    both depend on a real role id coming out of this step.
    Skip If    "${FLOW_ID}" == "${EMPTY}"    msg=no flow to grant members on — step 01 failed
    ${result}=    Call Forge Tool    forge_member_batch    target_flow_id=${FLOW_ID}
    Result Should Not Error    ${result}    member batch (harvest+apply)
    Should Not Be Empty    ${result}[role_ids]
    ...    msg=role_ids is EMPTY -- KF_APP now has no grantable AppRole at all; step 05's assignee wiring and step 14's completion walk cannot proceed as written, review before treating this as a simple pass
    Should Be Empty    ${result}[missing]
    Set Suite Variable    ${ASSIGNEE_ROLE_ID}    ${result}[role_ids][0]
    Set Suite Variable    ${ASSIGNEE_ROLE_NAME}    ${result}[harvested][0]
    Log    role_ids=${result}[role_ids] harvested=${result}[harvested] note=${result}[note]

03 Apply Sample Fields And Sections
    [Documentation]    forge_apply_fields: ~8 fields across 3 named sections, one write.
    ...    No Select field: KF_APP's list inventory is EMPTY (checked live before writing this
    ...    suite — CLAUDE.md "never guess a literal": an unbacked Select would have no real
    ...    option to validate against) — a plain Text field stands in, logged here per the
    ...    Node G brief's own instruction to log that fallback.
    Skip If    "${FLOW_ID}" == "${EMPTY}"    msg=no flow to add fields to — step 01 failed
    Log    KF_APP has 0 lists (checked live) -> using Text instead of Select, as instructed
    ${f1}=    Create Dictionary    name=Reference Code    type=Text    required=${True}
    ${f2}=    Create Dictionary    name=Requested Date    type=Date    required=${False}
    ${f3}=    Create Dictionary    name=Priority    type=Text    required=${False}
    ${f4}=    Create Dictionary    name=Summary    type=Textarea    required=${True}
    ${f5}=    Create Dictionary    name=Details    type=Textarea    required=${False}
    ${f6}=    Create Dictionary    name=Done Flag    type=Boolean    required=${False}
    ${f7}=    Create Dictionary    name=Reviewer Note    type=Textarea    required=${False}
    ${f8}=    Create Dictionary    name=Outcome    type=Text    required=${False}
    ${fields}=    Create List    ${f1}    ${f2}    ${f3}    ${f4}    ${f5}    ${f6}    ${f7}    ${f8}
    ${intake}=    Create List    Reference Code    Requested Date    Priority
    ${description}=    Create List    Summary    Details
    ${review}=    Create List    Done Flag    Reviewer Note    Outcome
    ${sections}=    Create Dictionary
    ...    Intake=${intake}    Description=${description}    Review=${review}
    ${result}=    Call Forge Tool    forge_apply_fields
    ...    flow_id=${FLOW_ID}    fields=${fields}    sections=${sections}
    Result Should Not Error    ${result}    apply fields + sections
    Should Be Empty    ${result}[missing]

04 Add Sample Checklist Table
    [Documentation]    forge_add_table: 2-column child table, MaxRow 3 (Kissflow's native cap).
    Skip If    "${FLOW_ID}" == "${EMPTY}"    msg=no flow to add a table to — step 01 failed
    ${c1}=    Create List    Item    Text
    ${c2}=    Create List    Complete    Boolean
    ${columns}=    Create List    ${c1}    ${c2}
    ${result}=    Call Forge Tool    forge_add_table
    ...    flow_id=${FLOW_ID}    name=Checklist    columns=${columns}    max_rows=${3}
    Result Should Not Error    ${result}    add table
    Should Be Empty    ${result}[missing_columns]

05 Build Sample Workflow
    [Documentation]    forge_build_workflow: 3 sequential steps, each assigned the AppRole step
    ...    02 granted. DESTRUCTIVE — wipes the whole Permission matrix (CLAUDE.md), hence step 07
    ...    re-sets visibility right after this.
    ...
    ...    ⚠️ CORRECTED 2026-08-07 (Node L): membership alone is not enough for a submit to
    ...    succeed cleanly — a step with no real assignee fails a first submit with a generic
    ...    `500 processError`, not the clean 403 a plain membership gap gives (CLAUDE.md Members
    ...    first). Every step below is therefore built with the SAME role id step 02 granted,
    ...    not ${NONE} — the combination is what step 14's completion walk depends on.
    Skip If    "${FLOW_ID}" == "${EMPTY}"    msg=no flow to build a workflow on — step 01 failed
    ${s1}=    Create List    Intake Review    ${ASSIGNEE_ROLE_ID}
    ${s2}=    Create List    Detail Review    ${ASSIGNEE_ROLE_ID}
    ${s3}=    Create List    Final Review    ${ASSIGNEE_ROLE_ID}
    ${steps}=    Create List    ${s1}    ${s2}    ${s3}
    ${roles}=    Create Dictionary    ${ASSIGNEE_ROLE_ID}    ${ASSIGNEE_ROLE_NAME}
    ${result}=    Call Forge Tool    forge_build_workflow    flow_id=${FLOW_ID}    steps=${steps}
    ...    roles=${roles}
    Result Should Not Error    ${result}    build workflow
    Should Be Empty    ${result}[missing_steps]
    Log    assigned=${result}[assigned] unassigned=${result}[unassigned]
    # `assigned` above is an ECHO of the INPUT steps (kfforge/client.py apply_workflow computes it
    # from what was requested, never reads the draft back afterward) -- it can never be empty or
    # wrong as long as a role was passed in, so it proves nothing on its own. The real proof is a
    # live read-back of the Resource nodes this write actually produced.
    ${assigned_role_ids}=    Resolve Assigned Role Ids    ${FLOW_ID}
    ${expected_roles}=    Create List    ${ASSIGNEE_ROLE_ID}    ${ASSIGNEE_ROLE_ID}    ${ASSIGNEE_ROLE_ID}
    Lists Should Be Equal    ${assigned_role_ids}    ${expected_roles}
    ...    msg=read-back Resource nodes do not show all 3 steps assigned to the granted role -- step 14's walk cannot succeed without this (CLAUDE.md Members first)

06 Add Sample Goto Gate
    [Documentation]    forge_add_goto_gate: a backward loop from "Final Review" to "Intake
    ...    Review", gated on the Boolean "Done Flag" (never an optional Select — gate polarity,
    ...    CLAUDE.md). Re-run AFTER forge_build_workflow, matching how the manual describes a
    ...    loop added to an already-wired flow.
    Skip If    "${FLOW_ID}" == "${EMPTY}"    msg=no flow to gate — step 01 failed
    ${result}=    Call Forge Tool    forge_add_goto_gate
    ...    flow_id=${FLOW_ID}    target_activity_name=Intake Review    field_name=Done Flag
    Result Should Not Error    ${result}    add goto gate
    Should Be True    ${result}[verified]

07 Set Sample Visibility
    [Documentation]    forge_set_visibility: re-applied AFTER forge_build_workflow, which wipes
    ...    every Permission (CLAUDE.md). "Intake" section must list Start as an owner or the
    ...    submission form renders empty (StartEvent is position 0).
    Skip If    "${FLOW_ID}" == "${EMPTY}"    msg=no flow to set visibility on — step 01 failed
    ${intake_owners}=    Create List    Start    Intake Review
    ${description_owners}=    Create List    Detail Review
    ${review_owners}=    Create List    Final Review
    ${checklist_owners}=    Create List    Detail Review
    ${owners}=    Create Dictionary
    ...    Intake=${intake_owners}    Description=${description_owners}
    ...    Review=${review_owners}    Checklist=${checklist_owners}
    ${result}=    Call Forge Tool    forge_set_visibility    flow_id=${FLOW_ID}    owners=${owners}
    Result Should Not Error    ${result}    set visibility
    Should Be Empty    ${result}[missing]

08 Style Sample Section
    [Documentation]    forge_set_styles: only the 2 CONFIRMED design tokens (CLAUDE.md Styling —
    ...    tokens are UNVALIDATED by the API and fail silently at render if wrong).
    Skip If    "${FLOW_ID}" == "${EMPTY}"    msg=no flow to style — step 01 failed
    ${props}=    Create Dictionary
    ...    Section.Bg.Color=Color.Info.300    Section.Header.Color=Color.Secondary.Ten.800
    ${styles}=    Create Dictionary    Intake=${props}
    ${result}=    Call Forge Tool    forge_set_styles    flow_id=${FLOW_ID}    styles=${styles}
    Result Should Not Error    ${result}    set section style
    Should Be Empty    ${result}[missing]

09 Set Sample Field Event
    [Documentation]    forge_set_events: the formula-engine substitute (CLAUDE.md Field events —
    ...    Kissflow has no computed-field type, only SDK events). Attached to "Reference Code"
    ...    (Type Text, confirmed live trigger "onChange"), scripted as a SELF-reference (the
    ...    field sets its own value) so doctor's "script references a missing field" check can
    ...    never trip regardless of which other field ids happen to exist.
    Skip If    "${FLOW_ID}" == "${EMPTY}"    msg=no flow to attach an event to — step 01 failed
    ${field_ids}=    Resolve Field Ids    ${FLOW_ID}
    ${id_ref_code}=    Get From Dictionary    ${field_ids}    Reference Code
    ${script}=    Set Variable    (async () => { kf.form.setFieldValue('${id_ref_code}', 'x'); })();
    ${event_spec}=    Create List    onChange    ${script}
    ${event_specs}=    Create List    ${event_spec}
    ${events}=    Create Dictionary
    Set To Dictionary    ${events}    Reference Code    ${event_specs}
    ${result}=    Call Forge Tool    forge_set_events    flow_id=${FLOW_ID}    events=${events}
    Result Should Not Error    ${result}    set field event
    Should Be Empty    ${result}[missing]
    List Should Contain Value    ${result}[verified]    Reference Code

10 Publish Sample Process
    [Documentation]    forge_publish -> Status Live, read back from the flow's OWN metadata
    ...    record (never trust the publish response alone — THE RULE).
    ...
    ...    ⚠️ CORRECTED 2026-08-07 (Node L): this used to branch on a documented-limitation outcome
    ...    tied to the app under test having zero AppRole members. Steps 02/05 now grant real
    ...    membership AND a real assignee, so this is a hard assertion — a publish failure here is
    ...    a real regression, not a legitimate branch.
    Skip If    "${FLOW_ID}" == "${EMPTY}"    msg=no flow to publish — step 01 failed
    ${result}=    Call Forge Tool    forge_publish    kind=process    flow_id=${FLOW_ID}
    Result Should Not Error    ${result}    publish process
    Should Be Equal As Strings    ${result}[status]    Live

11 Doctor Reports The Process Clean
    [Documentation]    forge_doctor -> 0 problems (assert exact). Runs regardless of step 10's
    ...    outcome — doctor audits the DRAFT graph, independent of live/publish status, and is
    ...    exactly the diagnostic that tells apart "the graph itself is broken" from "publish
    ...    failed for an unrelated reason" (e.g. the membership gap).
    Skip If    "${FLOW_ID}" == "${EMPTY}"    msg=no flow to audit — step 01 failed
    ${result}=    Call Forge Tool    forge_doctor    flow_id=${FLOW_ID}
    Log    ${result}
    Result Should Not Error    ${result}    doctor
    Should Be Empty    ${result}[problems]
    Should Be True    ${result}[ok]

12 Create And Build Sample Page
    [Documentation]    forge_create_page + forge_build_page: a label + a view/table bound to the
    ...    new flow with FULL binding config (placeholders CANNOT ship — THE RULE: a page with a
    ...    placeholder binding publishes clean and renders broken). Published (publish=True)
    ...    right here so the built content actually becomes visible to a user — an unpublished
    ...    page's draft can 200 on every write and still show nothing live (review F5).
    ...
    ...    Asserts the REAL node-count shape, not just "no error" (review F2: `Result Should Not
    ...    Error` alone can never fail once F1 wired up verified/missing — a page-build tool that
    ...    is structurally unable to report a problem is not a test of anything). `missing` empty
    ...    is the F1 audit; the exact Component/FieldMapping/Property counts are the live-observed
    ...    shape of exactly this suite's 2 widgets (1 label + 1 view/table).
    Skip If    "${FLOW_ID}" == "${EMPTY}"    msg=no flow to bind a page view to — step 01 failed
    ${created}=    Call Forge Tool    forge_create_page    app_id=${APP_ID}    name=${PAGE_NAME}
    Result Should Not Error    ${created}    create page
    Set Suite Variable    ${PAGE_ID}    ${created}[page_id]
    Log    Created page ${PAGE_ID}

    ${label_kwargs}=    Create Dictionary
    ...    container_id=Container001    widget=general/label    name=Overview Label
    ${label_config}=    Create Dictionary    title=Sample Intake Overview
    Set To Dictionary    ${label_kwargs}    config=${label_config}
    ${label_step}=    Create Dictionary    kind=widget    kwargs=${label_kwargs}

    ${table_config}=    Create Dictionary
    ...    flow_type=process    flow_id=${FLOW_ID}    view_id=myitems
    ${table_kwargs}=    Create Dictionary
    ...    container_id=Container001    widget=view/table    config=${table_config}
    ${table_step}=    Create Dictionary    kind=widget    kwargs=${table_kwargs}

    ${steps}=    Create List    ${label_step}    ${table_step}
    ${built}=    Call Forge Tool    forge_build_page
    ...    app_id=${APP_ID}    page_id=${PAGE_ID}    steps=${steps}    publish=${True}
    Result Should Not Error    ${built}    build page content
    Log    node_counts=${built}[node_counts]
    Should Be Empty    ${built}[missing]
    Dictionary Should Contain Item    ${built}[node_counts]    Component    ${2}
    Dictionary Should Contain Item    ${built}[node_counts]    FieldMapping    ${4}
    Dictionary Should Contain Item    ${built}[node_counts]    Property    ${4}
    Should Be True    ${built}[published]    the page's own content must be published, not just drafted

13 Wire Sample Page Into Navigation
    [Documentation]    forge_set_navigation: Menu -> FieldMapping -> Property{Type:"Page"}.
    Skip If    "${PAGE_ID}" == "${EMPTY}"    msg=no page to wire into navigation — step 12 failed
    ${result}=    Call Forge Tool    forge_set_navigation
    ...    app_id=${APP_ID}    page_id=${PAGE_ID}    label=Sample Intake
    Result Should Not Error    ${result}    set navigation
    Should Not Be Equal    ${result}[menu_id]    ${NONE}

14 Simulate A Sample Case End To End
    [Documentation]    forge_simulate_case: create an item, fill+verify per step (Text/Textarea/
    ...    Boolean only — Date/Table read-backs normalize server-side and would false-fail the
    ...    verifier, per the Node G brief), submit through Start then all 3 user steps to
    ...    completion. "Done Flag" is filled TRUE so the goto's `= false()` condition never fires
    ...    — this test proves the LINEAR path reaches the end, not the loop-back path (the loop's
    ...    structural wiring is what step 06 + step 11's clean doctor report already prove).
    ...
    ...    The fill PAYLOAD MUST be keyed by field ID, never the human-readable name (CLAUDE.md
    ...    Item data plane: "fill PUT .../admin/{flow}/{iid} -> {field_id: value, ...}") — found
    ...    live: a name-keyed PUT 400s `KISSFLOW_ERROR_01003 FieldNotFound`. `Resolve Field Ids`
    ...    reads the draft once and maps every field NAME used below to its real ID.
    ...
    ...    Each StepPlan's `name` is only a REPORTING label — `forge_simulate_case` submits
    ...    whatever step the item actually sits at when that plan runs, never the name itself
    ...    (dataplane.py StepPlan's own docstring). Submit count for a full walk is 1 (the
    ...    StartEvent, a Draft item's own first submit) + N (the N UserTasks) — CLAUDE.md
    ...    Workflow, re-verified live 2026-08-07 with `_current_step` instrumented at every
    ...    submit. Four StepPlans below, one per hop, labeled by the step each one ACTUALLY
    ...    leaves: "Start" (the create response's own aiid, no prior context — dataplane.py's
    ...    two-phase rule), then "Intake Review", "Detail Review", "Final Review" — the last of
    ...    which completes the item directly, no second submit needed and no `GotoTask` involved
    ...    in the count (an earlier version of this suite mislabeled the hops one short — missing
    ...    the Start hop shifted every later plan's fields onto the WRONG step and made the last
    ...    step look like it needed submitting twice; it never did).
    ...
    ...    ⚠️ CORRECTED 2026-08-07 (Node L), replacing the earlier documented-limitation branch.
    ...    That branch existed because `live_aiid` correctly refused to submit an item with no
    ...    derivable context aiid — one step short of the raw `403 KISSFLOW_ERROR_050302` a bare
    ...    create-response aiid would have hit, root-caused to the app under test having no
    ...    grantable AppRole to assign a step to (CLAUDE.md Members first). That root cause no
    ...    longer holds: step 02 now grants real membership (`Permission: ["InitiateItems"]`) and
    ...    step 05 wires the same role as every step's real assignee. Layered on top,
    ...    dataplane.py's two-phase aiid rule (CLAUDE.md Item data plane) lets `walk` derive hop
    ...    1's aiid from the CREATE response instead of refusing outright — an item at its start
    ...    step, never yet submitted, has no `_current_context` yet, which is expected, not an
    ...    error. Together these let a real item walk all the way to Completed; this test now
    ...    asserts that end-to-end outcome instead of the refusal that used to be the only
    ...    reachable state.
    Skip If    "${FLOW_ID}" == "${EMPTY}"    msg=no flow to simulate a case on — step 01 failed

    ${field_ids}=    Resolve Field Ids    ${FLOW_ID}
    ${id_ref_code}=      Get From Dictionary    ${field_ids}    Reference Code
    ${id_priority}=      Get From Dictionary    ${field_ids}    Priority
    ${id_summary}=       Get From Dictionary    ${field_ids}    Summary
    ${id_details}=       Get From Dictionary    ${field_ids}    Details
    ${id_done_flag}=     Get From Dictionary    ${field_ids}    Done Flag
    ${id_reviewer_note}=    Get From Dictionary    ${field_ids}    Reviewer Note
    ${id_outcome}=       Get From Dictionary    ${field_ids}    Outcome

    ${start_values}=    Create Dictionary
    Set To Dictionary    ${start_values}    ${id_ref_code}    REF-0001    ${id_priority}    Normal
    ${step1_values}=    Create Dictionary
    ${step2_values}=    Create Dictionary
    Set To Dictionary    ${step2_values}
    ...    ${id_summary}    Sample summary text    ${id_details}    Sample details text
    ${step3_values}=    Create Dictionary
    Set To Dictionary    ${step3_values}    ${id_done_flag}    ${True}
    ...    ${id_reviewer_note}    Sample reviewer note    ${id_outcome}    Resolved

    # "Intake" (Reference Code required=True + Priority) is owned by [Start, Intake Review] in
    # step 07's visibility matrix -- it is visible, and Required-enforced, ALREADY at Start, so
    # its values must land on the Start hop, not the Intake Review one, or the Start submit
    # itself 400s KISSFLOW_ERROR_050312 FormValidationError (found live). "Description" (Summary
    # required=True + Details) is owned by [Detail Review] only, so its values belong on the
    # Detail Review hop; "Review" (Done Flag/Reviewer Note/Outcome) is owned by [Final Review]
    # only, so its values belong on the Final Review hop.
    ${hop0}=    Create Dictionary    name=Start    values=${start_values}
    ${step1}=    Create Dictionary    name=Intake Review    values=${step1_values}
    ${step2}=    Create Dictionary    name=Detail Review    values=${step2_values}
    ${step3}=    Create Dictionary    name=Final Review    values=${step3_values}
    ${steps}=    Create List    ${hop0}    ${step1}    ${step2}    ${step3}

    ${result}=    Call Forge Tool    forge_simulate_case    flow_id=${FLOW_ID}    steps=${steps}
    Log    ${result}
    Result Should Not Error    ${result}    simulate case walk to completion
    Should Be Empty    ${result}[failed]
    # `advanced` is an ECHO of the planned step NAMES (dataplane.py's walk() appends plan.name on
    # success, never reads it back from the item) -- Should Be Empty on `failed` already proves
    # every planned hop succeeded; the REAL, non-echo proof this walk did what it claims is the
    # live status read below.

    ${status}=    Get Item Status    ${FLOW_ID}    ${result}[iid]
    Should Be Equal As Strings    ${status}    Completed
    ...    msg=item did not reach Completed after every step advanced -- ${result}

*** Keywords ***
Set App Id From Env
    [Documentation]    `%{KF_APP}` resolves at PARSE time, before Suite Setup's own `Load Env
    ...    File` step has populated os.environ — so it cannot be a `*** Variables ***` default.
    ...    This runs AFTER `Load Env File`/`Connect To Forge Server` in Suite Setup instead, when
    ...    the environment variable genuinely exists.
    Set Suite Variable    ${APP_ID}    %{KF_APP}

Delete Everything This Suite Created
    [Documentation]    Suite Teardown. ALWAYS runs. Deletes the page (LIST-route verified) then
    ...    the flow (archive+delete), reporting every created artifact's deletion status — never
    ...    silent about what was or wasn't cleaned up. Runs even if earlier steps failed, so every
    ...    check here tolerates a suite variable never having been set.
    IF    "${PAGE_ID}" != "${EMPTY}"
        ${page_del}=    Call Forge Tool    forge_delete_flow
        ...    kind=page    flow_id=${PAGE_ID}    app_id=${APP_ID}
        Log    page delete: ${page_del}
        Run Keyword And Ignore Error
        ...    Should Be True    ${page_del}[verified]    page ${PAGE_ID} deletion not verified
    ELSE
        Log    no page was created — nothing to delete
    END

    IF    "${FLOW_ID}" != "${EMPTY}"
        ${flow_del}=    Call Forge Tool    forge_delete_flow    kind=process    flow_id=${FLOW_ID}
        Log    flow delete: ${flow_del}
        Run Keyword And Ignore Error
        ...    Should Be True    ${flow_del}[verified]    flow ${FLOW_ID} deletion not verified
    ELSE
        Log    no flow was created — nothing to delete
    END

    Disconnect From Forge Server
