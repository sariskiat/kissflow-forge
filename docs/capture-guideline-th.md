# ไกด์ไลน์: บอก feature → กดใน builder → ก๊อป network → วางให้ Claude

สำหรับคนที่ใช้ Claude Code + kissflow-forge MCP แล้วเจอว่า Claude สร้างของบางอย่างไม่ได้
หรือสร้างแล้วไม่ครบ (เช่น assignee, computed field, lookup) วิธีแก้ที่เร็วที่สุดคือ
**ทำของชิ้นนั้นเองใน builder หนึ่งชิ้น แล้วเอา network request ที่ builder ยิงมาให้ Claude ดู**
Claude จะเทียบ node ต่อ node กับสิ่งที่ตัวเองสร้าง แล้วแก้ให้ตรง

เป้าหมายของไกด์นี้: **ให้พี่ทำได้เอง ด้วยวิธีไหนก็ได้** ทุกอย่างข้างล่างคือทางที่เราลองแล้วเร็วสุด
ไม่ใช่กติกาที่ต้องผ่านก่อน ทำแบบอื่นได้ผลก็ส่งมาเลย ทุก PR เรารีวิวอยู่แล้ว (ดูหัวข้อ "ส่งของกลับ")

กฎเหล็กข้อเดียวที่ควรจำ (จาก `CLAUDE.md` > THE RULE): API ตอบ 200 ไม่ได้แปลว่าใช้งานได้
สิ่งเดียวที่เชื่อได้คือ **ของที่สร้างจาก UI จริง เอามา diff** การเดาซ้ำ ๆ ช้ากว่า diff จริงหนึ่งครั้งเสมอ

## ก่อนเริ่ม

- **ให้ Claude ของพี่อ่าน `docs/agents/developerguide.md` ก่อนเริ่มทุกครั้ง** ไฟล์นั้นคือคู่มือฉบับ Claude (วางแผน, เขียน test แดงก่อน, capture, diff, ส่งกลับ) ไฟล์นี้คือฉบับคน

- ต่อ MCP ให้ได้ก่อน: ดู `docs/connect-claude-desktop.md` (ใช้ server ที่โฮสต์ไว้แล้ว)
  หรือ `docs/notes/SETUP.md` (รันเองในเครื่อง)
- ค่าเริ่มต้นคือ **dev tenant** (`KF_DEV_*` มีตัวกัน `dev-`) จะเขียน prod ได้ต้องตั้งใจใส่ชุด `KF_*` แทน (ดูหัวข้อ `.env`)
- **ห้ามกดปุ่ม Deploy** ใน builder เด็ดขาด ปุ่มนั้นคือ dev → UAT/prod promotion
  คำว่า publish ใน engine (`forge_publish`, `forge_publish_app`) คือ go-live ภายใน dev เท่านั้น

### `.env` ที่ต้องมี (รัน server เองในเครื่อง)

`cp .env.example .env` แล้วเติม 5 ค่านี้ (ขอจากคนที่ดูแล dev tenant ส่งทาง DM ไม่ใช่แชทรวม):

```bash
KF_DEV_DOMAIN=              # โดเมน dev ต้องมีคำว่า dev- ไม่งั้น engine ปฏิเสธ
KF_DEV_ACCOUNT_ID=          # account id ของ tenant
KF_DEV_ACCESS_KEY_ID=       # access key จาก Kissflow > My profile > API keys
KF_DEV_ACCESS_KEY_SECRET=   # secret คู่กัน
KF_APP=                     # app id ที่จะ build (ไม่ใส่ก็ได้ แล้วส่ง app_id ต่อ tool call หรือ forge_use_app)
```

- อยาก build บน tenant ที่ไม่ใช่ dev (เช่น prod, โปรเจกต์ citizen developer) → **ไม่ต้องใส่ `KF_DEV_*` เลย** ใส่ชุดนี้แทน
  (endpoint `/flow` `/metadata` เหมือนกันทุก tenant เปลี่ยนแค่โดเมนกับ credential โค้ดไม่ต้องแก้อะไรเพิ่ม):

```bash
KF_DOMAIN=                  # โดเมนจริง ไม่ต้องมี dev-
KF_ACCOUNT_ID=
KF_ACCESS_KEY_ID=
KF_ACCESS_KEY_SECRET=
KF_APP=
```

  กฎ: ถ้า `KF_DEV_DOMAIN` ตั้งอยู่ engine ใช้ชุด `KF_DEV_*` และบังคับ `dev-` เหมือนเดิม
  ถ้าไม่ตั้ง ถึงจะอ่านชุด `KF_*` (ไม่มีตัวกัน) เขียนของจริงทันที ตรวจ app id ให้ดีก่อนทุก call
- `.env` อยู่ใน `.gitignore` แล้ว ห้าม commit ห้ามวางค่าในแชท
- ตัวเลือก: `KF_PROCESS_TEMPLATE` (id ของ process template ที่ใช้ clone identity shell) ปกติไม่ต้องตั้ง
- ค่า `MCP_HTTP`, `PORT`, `MCP_OAUTH_*` ใช้เฉพาะคนที่โฮสต์ server ไม่เกี่ยวกับการใช้ในเครื่อง
- ถ้าใช้ server ที่โฮสต์ไว้แล้ว ไม่ต้องมี `.env` เลย ใส่ access key ของตัวเองใน connector ตาม `docs/connect-claude-desktop.md`

วิธีต่อเข้า Claude Code หลังมี `.env` (รันใน folder repo):

```bash
claude mcp add kissflow-forge -- sh -lc "cd '$(pwd)' && set -a; . ./.env; set +a; exec uv run mcp-server"
```

รายละเอียดทีละขั้นอยู่ใน `docs/notes/SETUP.md`

## รอบการทำงาน (ทำซ้ำได้ทีละ feature)

```text
 1. บอก feature ให้ Claude   ──►  Claude ลองสร้างด้วย forge_*  ──►  ใช้ได้? จบ
                                          │
                                          ▼ ไม่ได้ / ไม่ครบ
 2. เปิด builder + DevTools Network
 3. ทำของชิ้นนั้น "หนึ่งชิ้น" ใน UI
 4. ก๊อป request ที่ยิงไป /flow หรือ /metadata
 5. วางให้ Claude ตาม template ด้านล่าง
                                          │
                                          ▼
    Claude: diff graph ของตัวเอง vs graph จาก UI → แก้ → สร้างใหม่ใน flow ทดสอบ
            → forge_doctor → forge_simulate_case → บันทึก shape ลง repo
```

### ขั้น 1: บอก feature

บอกเป็นภาษาคน หนึ่ง feature ต่อหนึ่งข้อความ ระบุ app และ flow (dev) ให้ชัด ตัวอย่าง:

> เพิ่ม lookup field ชื่อ "Customer" ใน process "Order Request" (app dev-orders)
> ดึงจาก dataform "Customer Master" เอาคอลัมน์ Name กับ Phone มาด้วย

ให้ Claude ลองสร้างเองก่อน แล้วต้องเปิดดูใน builder จริง (ไม่ใช่เชื่อ 200)

### ขั้น 2: เปิด DevTools

1. เปิด builder ของ flow นั้นใน Chrome
2. กด `F12` (หรือ `Cmd+Option+I`) → แท็บ **Network**
3. ติ๊ก **Preserve log**
4. ช่อง Filter พิมพ์ `flow` (request ส่วนใหญ่ยิงไป `/flow/2/...` หรือ `/metadata`)
5. กดปุ่ม 🚫 (Clear) ให้ list ว่างก่อนลงมือ

### ขั้น 3: ทำ "หนึ่งชิ้น" ใน UI

ทำแค่อย่างเดียวต่อรอบ เช่น เพิ่ม lookup field หนึ่งอัน, ตั้ง assignee หนึ่ง step,
ตั้ง computed หนึ่ง field แล้วกด save

ทำหลายอย่างในรอบเดียว = request ปนกัน Claude แยกไม่ออกว่า key ไหนมาจากอะไร

### ขั้น 4: ก๊อป request

ต้องการ 3 อย่าง สำหรับ request แต่ละอันที่เป็น `PUT` / `POST` / `PATCH`:

| อะไร | เอามาจากไหน |
|---|---|
| URL + method | คลิก request → แท็บ **Headers** → บรรทัด Request URL, Request Method |
| body ที่ส่งไป | แท็บ **Payload** → **view source** → ก๊อปทั้งก้อน |
| สิ่งที่ตอบกลับ | แท็บ **Response** → ก๊อปทั้งก้อน |

ทางลัด: คลิกขวาที่ request → **Copy** → **Copy as cURL** ได้ URL + method + body ในคลิกเดียว
แต่ **cURL มี cookie และ token ติดมาด้วย ต้องลบบรรทัด `-H 'Cookie: ...'`
และ `-H 'Authorization: ...'` ออกก่อนวาง** (ดูหัวข้อความปลอดภัย)

ถ้ามีหลาย request: คลิกขวา → **Save all as HAR with content** แล้วส่งไฟล์ให้ Claude
แทนการวางทีละอัน (HAR ก็มี cookie ให้ Claude ลบก่อนใช้ ไม่ต้อง commit ไฟล์นี้)

ควรเก็บ **GET ของ flow ก่อนและหลัง** ด้วย ถ้ามี (builder มักโหลด graph ทั้งก้อนตอนเปิดหน้า)
diff ก่อน/หลังคือหลักฐานที่ดีที่สุดว่า UI เปลี่ยน node ไหนบ้าง

### ขั้น 5: วางให้ Claude ด้วย template นี้

```text
Feature: <หนึ่งประโยค เช่น lookup field "Customer" ดึงจาก dataform "Customer Master">
App / flow (dev): <app id หรือชื่อ> / <flow id หรือชื่อ>
สิ่งที่ Claude สร้างไว้แล้ว: <flow ทดสอบที่ Claude ลองทำแล้วไม่ครบ ถ้ามี>

ทำใน UI: <ขั้นตอนที่กดจริง 2-3 บรรทัด>

--- request 1 ---
PUT https://.../flow/2/<acct>/...
payload:
<วาง>
response:
<วาง>

--- request 2 --- (ถ้ามี)
...

ที่ต้องการ:
1. diff graph ที่ UI เขียน กับ graph ที่ forge_* เขียน บอกว่า key ไหนขาด/ต่าง
2. สร้างชิ้นเดียวกันใหม่ใน flow ทดสอบด้วย forge_* แล้ว read-back ให้ตรงกับ UI
3. รัน forge_doctor แล้ว forge_simulate_case พิสูจน์ว่าใช้ได้จริง ไม่ใช่แค่ publish ผ่าน
4. บันทึก shape ลง shapes/*.json และ docs/capabilities/<ชื่อ>.md (ใช้ docs/capabilities/TEMPLATE.md)
   เปลี่ยนชื่อ tenant/คน/app จริงเป็นชื่อสมมติก่อนเขียนลง repo
```

## ความปลอดภัย: ลบก่อนวางเสมอ

- ลบ header `Cookie`, `Authorization`, `x-access-key`, `x-access-secret` หรืออะไรที่ดูเหมือน token
- ลบ email / ชื่อคนจริงใน payload ถ้าไม่จำเป็นกับ shape (assignee ใช้ user id สมมติแทนได้)
- HAR และ cURL ดิบ **ห้าม commit** เข้า repo วางใน chat หรือไฟล์นอก repo เท่านั้น
- ของที่ลง `shapes/` และ `docs/capabilities/` ต้องไม่มีชื่อ tenant จริง มี test กวาดอยู่
  (`tests/test_p0_scaffold.py`) ถ้าหลุดไป test จะแดง

## ตัวอย่าง: 3 ชิ้นที่ clone มักขาด

| ชิ้น | ทำอะไรใน UI | request ที่ต้องมอง | shape / doc ใน repo ที่มีอยู่แล้ว |
|---|---|---|---|
| assignee | Workflow → คลิก step → ตั้ง Assignee → save | `PUT` ที่แก้ `Activity` node (key ประมาณ `Assignee`/`Assignees`) | `docs/engine/02-workflow.md`, `docs/engine/09-members-first.md` (assignee ต้องเป็น member ก่อน ไม่งั้น publish พัง) |
| computed | Field → Computed → ใส่สูตร → save | `PUT` ที่เพิ่ม `Event` + `Field::Event` บน field ต้นทาง | `docs/engine/07-field-events.md`, `docs/capabilities/config.computed.md`, `shapes/field_computed_expression.json` |
| lookup | Field palette → Lookup → เลือก flow ต้นทาง + คอลัมน์ → save | `PUT` ที่เพิ่ม `Field{Type:"Reference"}` + `Field::QueryDefinition{FlowType:"Process"}` | `docs/capabilities/field.lookup.md`, `shapes/field_lookup.json` |

ถ้า Claude บอกว่า "สร้างไม่ได้" ให้ชี้ไปที่ไฟล์ในคอลัมน์ขวาก่อน หลายชิ้นมี shape อยู่แล้ว
ปัญหาอาจเป็นแค่ tool ไม่ได้ใช้ shape นั้น ไม่ใช่ว่าไม่มีทางทำ

## สิ่งที่ Claude ต้องทำหลังได้ capture (สำหรับ Claude อ่าน)

1. Snapshot draft ก่อนเขียนอะไร (`docs/engine/10-write-path.md`)
2. Diff node ต่อ node, key ต่อ key ห้าม diff ซ้ำส่วนที่เช็คไปแล้ว ถ้ายังพังให้ไปหา layer
   ที่ยังไม่ได้ดู: config payload ของ flow, membership, key ที่คิดว่า optional, request ที่ UI ยิงตอนโหลดหน้าที่พัง
3. เขียนด้วย `forge_*` → read-back → `forge_doctor` → `forge_simulate_case`
   (สำหรับ assignee ต้องเดินไอเท็มจริงให้ถึง step นั้น)
4. บันทึก: `shapes/<name>.json` + `docs/capabilities/<name>.md` ตาม TEMPLATE, status = `captured`
   จนกว่าจะเดินไอเท็มผ่านแล้วค่อยเป็น `proven-live`
5. รายงานแบบนับครบ: key ที่เพิ่ม / ที่ต่าง / ที่ยังไม่รู้ ห้ามมี key ที่หายไปเงียบ ๆ

## ส่งของกลับ: branch → PR บน GitHub → เรารีวิว

พี่ clone จาก GitHub ของเรา ทำบน branch ของตัวเอง แล้วเปิด pull request กลับมา
เราเช็คทุก PR อยู่แล้ว ไม่ต้องกลัวพัง แค่ให้ก้อนเล็กและมีหลักฐาน

```bash
git checkout develop && git pull
git checkout -b feat/<ชื่อฟีเจอร์>       # หนึ่ง branch ต่อหนึ่งฟีเจอร์
# ... ทำงานกับ Claude ตามไกด์นี้ ...
uv run pytest -q          # ควรเขียว
make lint                 # ruff + import-linter
git push -u origin feat/<ชื่อฟีเจอร์>
gh pr create --base develop --fill        # หรือกดเปิด PR ในหน้าเว็บ GitHub
```

ใน PR ควรมี:

- **อะไร** ฟีเจอร์ที่เพิ่ม หนึ่งประโยค
- **หลักฐาน** capture ที่ใช้: `shapes/<name>.json` + `docs/capabilities/<name>.md` (status `captured` หรือ `proven-live`)
  ห้ามมี HAR / cURL ดิบ / `.env` / ชื่อ tenant จริงใน diff
- **พิสูจน์** ผล `forge_doctor` และ `forge_simulate_case` สั้น ๆ ไม่ใช่ "publish ผ่าน"
- ถ้าแก้โค้ดใน `kfforge/` มี test อย่างน้อยหนึ่งตัวที่แดงถ้าโค้ดใหม่พัง

เรารีวิวแล้วอาจขอแก้ใน comment ของ PR ตอบตรงนั้นได้เลย

## เรื่อง UAT / prod

ข้อเท็จจริงที่รู้ตอนนี้ (2026-08-26):

- prod **สร้าง app ได้** (ท่อเปิดอยู่) แต่ **deploy / approve ได้เฉพาะ admin** สิทธิ์กันไว้ที่ขั้น approve ไม่ใช่ขั้นสร้าง
- engine เขียน prod ได้เมื่อตั้ง `.env` เป็นชุด `KF_*` (ไม่มี `KF_DEV_DOMAIN`) ชุด `KF_DEV_*` ยังบังคับ `dev-` เหมือนเดิม

แนวทาง:

1. ตั้ง `.env` ชุด `KF_*` ชี้ prod แล้วให้ Claude สร้าง framework เปล่า (app + flow + members) ด้วย forge
2. build ฟีเจอร์ต่อจากนั้นตามไกด์นี้ ทำทีละชิ้น `forge_doctor` หลังทุกครั้ง
3. ของที่ต้อง approve ส่ง admin กดตามขั้นตอนของ tenant

บน prod ไม่มีตัวกันแล้ว ก่อน call ที่ลบหรือเขียนทับ ให้ Claude snapshot draft ก่อนเสมอ
(`docs/engine/10-write-path.md`) และห้ามเพิ่ม `everyone` เข้า role (ลบไม่ได้ ดู `skills/kissflow-forge-builder/SKILL.md` ตาราง refuse)
