"""kfforge.intake.questions — the grilling script: what to ask a Thai business owner to fill in
whichever of the 11 dimensions (schema.py) are still gaps.

Pure and offline: no network, no LLM call, no app-specific vocabulary. `text_th`/`why`/`example`/
`follow_ups` are written in Thai business language on purpose — the reader is a business owner
deciding how their shop should run, never a builder reading wire-level field names. Every
`example` below illustrates with the SAME neutral, fictional domain (an equipment repair intake
shop) so the question set reads as one coherent interview rather than 11 disconnected prompts;
that domain is illustration only, never baked into `text_th` itself, so the same question set
reads naturally for a completely different business.

Dimensions 4 (routing), 5 (rework loops) and 7 (master data) are genuinely optional in a real
app — a straight-line process with no branch, no rework, and no dropdown list is a perfectly
normal, complete app, not an incomplete one. Their questions say so explicitly ("ถ้าไม่มีให้ตอบว่า
ไม่มี" — "if there is none, you may answer 'none'"), because `schema.py`'s own
`confirmed_none` flag exists precisely so an interviewer never has to manufacture a fake branch or
loop just to satisfy this module — that used to be a real bug here, not a hypothetical one.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..types import FieldType
from .schema import AppSpec, _gap_dimensions


@dataclass(frozen=True)
class Question:
    id: str
    text_th: str
    why: str
    example: str
    follow_ups: tuple[str, ...]


# The legal FieldType wire values, spelled out so Q6a can tell a business owner exactly which
# "ประเภทข้อมูล" (data type) choices actually exist — answering with a type outside this list is
# not a valid answer, so the question should never let that ambiguity stand.
_LEGAL_FIELD_TYPES_TH = ", ".join(t.value for t in FieldType)

# Dimension 1 — problem / goal ------------------------------------------------------------------
_Q1: tuple[Question, ...] = (
    Question(
        id="1a",
        text_th="ตอนนี้ปัญหาหรือความเจ็บปวดหลักที่ทำให้ต้องสร้างระบบนี้คืออะไร?",
        why="ทุกฟีเจอร์ที่จะสร้างต้องย้อนกลับไปแก้ปัญหานี้ได้ ไม่งั้นจะสร้างของที่ไม่มีใครใช้",
        example="เช่น 'ทีมช่างซ่อมไม่รู้ว่างานไหนค้างอยู่กับใคร ลูกค้าโทรมาถามแล้วตอบไม่ได้'",
        follow_ups=("ปัญหานี้เกิดบ่อยแค่ไหน?", "ถ้าไม่แก้ตอนนี้จะเสียหายอย่างไร?"),
    ),
    Question(
        id="1b",
        text_th="เป้าหมายที่อยากได้คืออะไร และจะรู้ได้อย่างไรว่างานหนึ่งชิ้น 'เสร็จสมบูรณ์' แล้ว?",
        why="ต้องมีเส้นชัยที่ชัดเจน ไม่งั้นจะไม่รู้ว่าเมื่อไหร่ควรปิดงาน",
        example=(
            "เช่น เป้าหมาย = 'ลูกค้ารู้สถานะงานซ่อมได้ตลอดเวลา', "
            "เสร็จสมบูรณ์ = 'อุปกรณ์ซ่อมเสร็จ ส่งคืนลูกค้า และปิดงานในระบบแล้ว'"
        ),
        follow_ups=(
            "งานหนึ่งชิ้นจบลงได้กี่สถานะ (เช่น เสร็จสมบูรณ์ / ยกเลิก)?",
            "แต่ละงานจบด้วยผลลัพธ์แบบไหนได้บ้าง (เช่น ซ่อมสำเร็จ / ซ่อมไม่ได้)?",
        ),
    ),
)

# Dimension 2 — roles ----------------------------------------------------------------------------
_Q2: tuple[Question, ...] = (
    Question(
        id="2a",
        text_th="มีใครบ้างที่ต้องเข้ามาใช้ระบบนี้ และแต่ละคนทำหน้าที่อะไร?",
        why="สิทธิ์การเข้าถึงต้องผูกกับบทบาทจริง ไม่ใช่ผูกกับตัวบุคคลคนเดียว — และขั้นตอนถัดไปที่จะถามถึง (ใครเป็นเจ้าของแต่ละขั้นตอน) ต้องอ้างอิงบทบาทที่มีอยู่จริงในลิสต์นี้",
        example="เช่น 'พนักงานรับเรื่อง', 'ช่างซ่อม', 'หัวหน้าฝ่ายซ่อมบำรุง (แอดมิน)'",
        follow_ups=("ใครเป็นแอดมินที่ดูแลระบบทั้งหมด?", "แต่ละบทบาทมีกี่คนโดยประมาณ?"),
    ),
)

# Dimension 3 — stages ---------------------------------------------------------------------------
_Q3: tuple[Question, ...] = (
    Question(
        id="3a",
        text_th="งานหนึ่งชิ้นเดินทางผ่านขั้นตอนอะไรบ้าง ตั้งแต่เริ่มจนจบ?",
        why="ขั้นตอนเหล่านี้คือกระดูกสันหลังของ workflow ทั้งหมด ทุกอย่างที่ตามมาอ้างอิงกับมัน",
        example="เช่น 'รับเรื่อง -> ประเมินอาการ -> ซ่อม -> ตรวจสอบคุณภาพ -> ส่งคืนลูกค้า'",
        follow_ups=(
            "แต่ละขั้นตอนใครเป็นเจ้าของ (เลือกจากบทบาทที่คุยกันไปแล้วในข้อก่อนหน้า)?",
            "อะไรคือเงื่อนไขที่ทำให้เข้าขั้นตอนนั้นได้ และอะไรคือเงื่อนไขที่ทำให้ผ่านไปขั้นต่อไป?",
        ),
    ),
)

# Dimension 6 — data model -----------------------------------------------------------------------
_Q6: tuple[Question, ...] = (
    Question(
        id="6a",
        text_th="แต่ละขั้นตอนต้องกรอกข้อมูลอะไรบ้าง (ชื่อช่อง ประเภทข้อมูล และจำเป็นต้องกรอกไหม)?",
        why=(
            "นี่คือฟอร์มจริงที่ผู้ใช้จะเห็น ขาดช่องไหนไป งานจะกรอกข้อมูลไม่ครบ. "
            f"ประเภทข้อมูลที่เลือกได้มีเท่านี้เท่านั้น: {_LEGAL_FIELD_TYPES_TH} — "
            "ถ้าอยากได้แบบอื่นที่ไม่อยู่ในลิสต์นี้ ระบบสร้างให้ไม่ได้ ต้องเลือกจากลิสต์นี้เท่านั้น"
        ),
        example=(
            "เช่น 'ชื่ออุปกรณ์' (Text, บังคับกรอก), 'วันที่รับเรื่อง' (Date, บังคับกรอก), "
            "'ระดับความเร่งด่วน' (Select ตัวเลือก: สูง/กลาง/ต่ำ)"
        ),
        follow_ups=(
            "มีช่องไหนที่ผูกกับ dropdown ที่ใช้ซ้ำ (เช่น สถานะ, ประเภท) ไหม?",
            "ฟอร์มขั้นตอนนี้มีมากกว่าหนึ่งส่วน (section) ไหม เช่น ส่วนข้อมูลทั่วไป กับส่วนรายละเอียดเฉพาะ?",
        ),
    ),
    Question(
        id="6b",
        text_th=(
            "มีตารางที่ต้องกรอกได้หลายแถวไหม (เช่น รายการอะไหล่ที่ใช้), "
            "มีช่องที่ต้องคำนวณอัตโนมัติจากช่องอื่นไหม, "
            "และมีเลขที่งานที่ต้องออกให้อัตโนมัติไหม?"
        ),
        why="ตาราง/สูตรคำนวณ/เลขรันเป็นส่วนที่มักถูกลืมตอนเริ่มคุย แต่กระทบโครงสร้างข้อมูลทั้งหมด",
        example=(
            "เช่น ตาราง 'รายการอะไหล่ที่ใช้' (ชื่ออะไหล่, จำนวน, ราคา) สูงสุด 20 แถว; "
            "ช่องคำนวณ 'ราคารวม' = จำนวน x ราคาต่อชิ้น; เลขที่งาน = 'RPR-0001', 'RPR-0002', ..."
        ),
        follow_ups=(
            "ตารางมีจำกัดจำนวนแถวสูงสุดไหม?",
            "ช่องคำนวณอัตโนมัติ อ้างอิงจากช่องไหนบ้าง (ต้องเป็นช่องที่มีอยู่จริงในฟอร์มหรือในตาราง)?",
        ),
    ),
    Question(
        id="6c",
        text_th=(
            "ถ้ามีตารางจากข้อก่อนหน้า แต่ละคอลัมน์ในตารางเก็บข้อมูลประเภทอะไร "
            "(Text/Number/Date/...) และคอลัมน์ไหนบังคับต้องกรอกทุกแถวบ้าง?"
        ),
        why=(
            "แต่ละคอลัมน์ในตารางต้องมีประเภทข้อมูลและสถานะบังคับกรอกที่ชัดเจน เหมือนกับช่องข้อมูลทั่วไป "
            "ไม่งั้นระบบจะไม่รู้ว่าควรสร้างคอลัมน์แบบไหน. "
            f"ประเภทข้อมูลเลือกได้จากลิสต์เดียวกับข้อ 6a เท่านั้น: {_LEGAL_FIELD_TYPES_TH}"
        ),
        example=(
            "เช่น ตาราง 'รายการอะไหล่ที่ใช้': 'ชื่ออะไหล่' (Text, บังคับ), "
            "'จำนวน' (Number, บังคับ), 'ราคาต่อชิ้น' (Number, บังคับ)"
        ),
        follow_ups=("มีคอลัมน์ไหนที่ปล่อยว่างได้บ้างไหม หรือทุกคอลัมน์บังคับหมด?",),
    ),
    Question(
        id="6d",
        text_th="แต่ละส่วน (section) ของฟอร์มที่พูดถึงในข้อ 6a ควรมีคำอธิบายสั้นๆ ว่าเก็บข้อมูลอะไร — แต่ละส่วนอธิบายว่าอะไร?",
        why=(
            "คำอธิบายนี้ช่วยให้ทีมสร้างระบบแยกแยะส่วนต่างๆ ได้ถูกต้องเวลาขั้นตอนเดียวกันมีหลายส่วน "
            "และช่วยให้ผู้ใช้จริงเข้าใจว่าแต่ละส่วนของฟอร์มมีไว้ทำอะไร"
        ),
        example=(
            "เช่น ส่วน 'ข้อมูลทั่วไป' = 'ชื่อและรายละเอียดของลูกค้ากับอุปกรณ์', "
            "ส่วน 'ความเร่งด่วน' = 'ระดับความสำคัญและกำหนดเวลาที่ต้องใช้ในการจัดคิวงาน'"
        ),
        follow_ups=(),
    ),
)

# Dimension 7 — master data -----------------------------------------------------------------------
_Q7: tuple[Question, ...] = (
    Question(
        id="7a",
        text_th=(
            "ตัวเลือกแบบ dropdown ที่ใช้ซ้ำในหลายที่ (เช่น สถานะ, ประเภท, สาขา) "
            "มีอะไรบ้าง และใครเป็นคนดูแลรายการนี้? (ถ้าฟอร์มนี้ไม่มี dropdown แบบนี้เลย ให้ตอบว่า 'ไม่มี' ได้เลย)"
        ),
        why="รายการเหล่านี้ต้องมีค่าที่แน่นอนตายตัว ไม่งั้นเงื่อนไขที่ผูกกับมันจะพังแบบเงียบๆ — แต่ถ้าฟอร์มใช้แต่ช่องข้อความล้วนๆ ก็ไม่จำเป็นต้องมีมิติข้อนี้เลย",
        example=(
            "เช่น รายการ 'สถานะงาน' = ['รับเรื่องแล้ว', 'กำลังซ่อม', 'ซ่อมเสร็จ', 'ส่งคืนแล้ว'], "
            "เจ้าของ = หัวหน้าฝ่ายซ่อมบำรุง"
        ),
        follow_ups=(
            "มีรายการไหนที่จะเปลี่ยนบ่อยไหม?",
            "ค่าที่ใช้ต้องสะกดตรงตัวเป๊ะๆ ทุกที่ที่ใช้ — ยืนยันได้ไหมว่าสะกดถูกต้องตรงกันหมด?",
        ),
    ),
)

# Dimension 4 — routing ---------------------------------------------------------------------------
_Q4: tuple[Question, ...] = (
    Question(
        id="4a",
        text_th=(
            "มีจุดไหนที่ต้องเลือกเส้นทางต่างกัน ขึ้นอยู่กับคำตอบของฟิลด์ใดฟิลด์หนึ่งไหม? "
            "(ถ้าเป็นงานที่เดินตรงเส้นเดียวไม่มีทางแยกเลย ให้ตอบว่า 'ไม่มี' ได้เลย ไม่ต้องเสกทางแยกขึ้นมา)"
        ),
        why="ถ้าไม่ระบุจุดแตกแขนง workflow จะเดินเส้นตรงเส้นเดียวเท่านั้น — และนั่นเป็นคำตอบที่ถูกต้องสมบูรณ์ได้เหมือนกัน ถ้าธุรกิจจริงเป็นแบบนั้น",
        example=(
            "เช่น ที่ขั้น 'ประเมินอาการ' ถ้าฟิลด์ 'ซ่อมได้ไหม' ตอบ 'ซ่อมได้' ไปขั้น 'ซ่อม', "
            "ถ้าตอบ 'ซ่อมไม่ได้' ไปขั้น 'ส่งคืนลูกค้า' เลย"
        ),
        follow_ups=(
            "ตัวเลือกของฟิลด์นั้นมีอะไรบ้างทั้งหมด?",
            "แต่ละตัวเลือกไปขั้นตอนไหนต่อ — ทุกตัวเลือกต้องมีปลายทาง ห้ามมีตัวเลือกที่ไม่รู้ว่าจะไปไหน?",
        ),
    ),
)

# Dimension 5 — rework loops -----------------------------------------------------------------
_Q5: tuple[Question, ...] = (
    Question(
        id="5a",
        text_th=(
            "มีขั้นตอนไหนที่บางครั้งต้องย้อนกลับไปแก้ไขใหม่ ก่อนจะไปต่อได้ไหม? "
            "(ถ้าไม่มีการย้อนกลับเลยในงานนี้ ให้ตอบว่า 'ไม่มี' ได้เลย)"
        ),
        why="ถ้าไม่ระบุ ระบบจะไม่มีทางส่งงานย้อนกลับให้แก้ไขเลย งานที่ไม่ผ่านจะค้างอยู่เฉยๆ — แต่ถ้างานจริงไม่เคยต้องย้อนกลับ ก็ไม่ต้องมีมิติข้อนี้เช่นกัน",
        example=(
            "เช่น ถ้า 'ตรวจสอบคุณภาพ' ไม่ผ่าน ต้องย้อนกลับไปขั้น 'ซ่อม' ใหม่ "
            "จนกว่าจะติ๊กช่อง 'ผ่านคุณภาพแล้ว'"
        ),
        follow_ups=(
            "ตัวชี้วัดว่าออกจากลูปได้แล้วต้องเป็นช่องติ๊กใช่/ไม่ใช่เท่านั้น ห้ามเป็นตัวเลือกที่เว้นว่างได้ — มีช่องแบบนี้ไหม?",
            "ขั้นที่ย้อนกลับไป ต้องอยู่ก่อนขั้นที่ย้อนกลับมาจริงไหม (ย้อนไปข้างหน้าไม่ได้)?",
            "จำกัดจำนวนรอบไหม กี่รอบ?",
        ),
    ),
)

# Dimension 8 — visibility matrix -----------------------------------------------------------------
_Q8: tuple[Question, ...] = (
    Question(
        id="8a",
        text_th="แต่ละส่วนของฟอร์ม ใครควรเห็น/แก้ไขได้/ไม่ควรเห็นเลย ในแต่ละขั้นตอน?",
        why="ถ้าไม่ระบุ ทุกคนจะเห็นทุกอย่างตลอดเวลา ซึ่งมักไม่ใช่สิ่งที่ต้องการจริง",
        example=(
            "เช่น ส่วน 'ราคาซ่อม' ที่ขั้น 'รับเรื่อง' = ซ่อนไว้ก่อน, "
            "ที่ขั้น 'ประเมินอาการ' = แก้ไขได้ (เฉพาะช่าง), "
            "ที่ขั้น 'ส่งคืนลูกค้า' = อ่านได้อย่างเดียว"
        ),
        follow_ups=(
            "มีส่วนไหนที่ต้องซ่อนทั้งส่วน ไม่ใช่แค่บางช่อง ไหม?",
            "หน้าฟอร์มแรกสุดที่ลูกค้า/พนักงานเห็นตอนเริ่มงานใหม่ (ก่อนขั้นตอนแรก) ใครควรเห็นส่วนไหนบ้าง?",
        ),
    ),
)

# Dimension 9 — timing -----------------------------------------------------------------------------
_Q9: tuple[Question, ...] = (
    Question(
        id="9a",
        text_th=(
            "แต่ละขั้นตอนมี SLA (กำหนดเวลา) ไหม และมีงานที่ต้องรันเป็นรอบ "
            "(เช่น ทุกเช้าวันศุกร์) หรือต้องมีการแจ้งเตือนไหม?"
        ),
        why=(
            "เวลาเป็นตัวแปรที่ลืมง่ายที่สุดตอนคุยงาน แต่กระทบ operation จริงมากที่สุด "
            "(หมายเหตุ: ข้อมูลข้อนี้เก็บไว้เป็นข้อมูลอ้างอิงสำหรับตั้งค่าการแจ้งเตือนนอกระบบ "
            "ไม่ใช่สิ่งที่ต้องตอบให้ครบก่อนถึงจะสร้างระบบได้)"
        ),
        example=(
            "เช่น SLA = 'ประเมินอาการต้องเสร็จภายใน 1 วันทำการ', "
            "batch = 'ทุกเช้าวันศุกร์ สรุปงานค้างส่งหัวหน้า', "
            "เตือน = 'เตือนช่างถ้างานค้างเกิน 3 วัน'"
        ),
        follow_ups=("ถ้าเกิน SLA จะเกิดอะไรขึ้น ใครต้องรู้เป็นคนแรก?",),
    ),
)

# Dimension 10 — personas -----------------------------------------------------------------------
_Q10: tuple[Question, ...] = (
    Question(
        id="10a",
        text_th=(
            "แต่ละบทบาทอยากเห็นหน้าจออะไรตอนเปิดระบบขึ้นมา "
            "(มีอะไรบ้าง, ตัวเลขสำคัญอะไรที่อยากเห็น, ทำอะไรได้จากหน้านั้น)?"
        ),
        why="หน้าจอที่ใช้งานได้จริงต้องออกแบบตามบทบาท ไม่ใช่หน้าเดียวที่ทุกคนต้องงมหาของตัวเอง",
        example=(
            "เช่น หัวหน้าฝ่ายซ่อมบำรุงอยากเห็น: จำนวนงานค้างทั้งหมด, งานที่เกิน SLA, "
            "ปุ่มมอบหมายงานใหม่"
        ),
        follow_ups=("แต่ละบทบาทต้องทำอะไรได้จากหน้านั้นบ้าง (อนุมัติ, มอบหมาย, ปิดงาน ฯลฯ)?",),
    ),
)

# Dimension 11 — test cases -----------------------------------------------------------------------
_Q11: tuple[Question, ...] = (
    Question(
        id="11a",
        text_th="ช่วยยกตัวอย่างงานจริง 2-3 เคส ตั้งแต่เริ่มจนจบ พร้อมค่าที่กรอกจริงและผลลัพธ์ที่ควรได้?",
        why="นี่คือวิธีเดียวที่พิสูจน์ได้ว่าระบบทำงานถูกต้องจริง ไม่ใช่แค่ publish สำเร็จ",
        example=(
            "เช่น เคส 'ซ่อมได้ปกติ': กรอกอุปกรณ์ = เครื่องพิมพ์, ความเร่งด่วน = กลาง "
            "-> เดินผ่าน รับเรื่อง->ประเมิน->ซ่อม->ตรวจสอบ->ส่งคืน -> ผลลัพธ์ = 'ซ่อมสำเร็จ'"
        ),
        follow_ups=(
            "มีเคสที่ควรจะ 'ซ่อมไม่ได้' หรือ 'ยกเลิกกลางทาง' ด้วยไหม?",
            "ถ้ามีขั้นที่ย้อนกลับได้ (ลูป) มีเคสที่ต้องผ่านขั้นนั้นสองรอบไหม (รอบแรกไม่ผ่าน รอบสองผ่าน)?",
        ),
    ),
)

QUESTIONS: dict[int, tuple[Question, ...]] = {
    1: _Q1, 2: _Q2, 3: _Q3, 4: _Q4, 5: _Q5, 6: _Q6,
    7: _Q7, 8: _Q8, 9: _Q9, 10: _Q10, 11: _Q11,
}

# Most-blocking dimension first, and never a dimension before what IT depends on:
# 1 problem/goal comes first (nothing else means anything without it), then 2 roles BEFORE
# 3 stages (a stage names an owner_role — asking who owns a stage before any role exists puts the
# cart before the horse, a real bug an earlier round of this file had), then 6 data model and
# 7 master data BEFORE 4 routing and 5 rework loops (a branch/loop gates on a field, and a routing
# literal is checked against a master-data list — both need to exist first), then 8 visibility,
# then 11 test cases (needs stages/fields/lists to already make sense), then 10 personas, then
# 9 timing last — it's advisory (see schema.ADVISORY_DIMENSIONS), the most forgiving to leave for
# last.
_PRIORITY_ORDER: tuple[int, ...] = (1, 2, 3, 6, 7, 4, 5, 8, 11, 10, 9)


def next_questions(spec: AppSpec, limit: int = 4) -> tuple[Question, ...]:
    """The next questions to ask, most-blocking dimension first, capped at `limit` total.

    Only dimensions `spec.gaps()` currently flags produce questions — a dimension that's already
    answered is never re-asked, and a dimension with no gap never appears here even if `limit`
    leaves room. This reads the FULL gap set (`_gap_dimensions`, same as `AppSpec.gaps()`), not
    `blocking_gaps()` — dimension 9 (timing) is advisory and never blocks a build, but it should
    still get asked about while it's unanswered. Walks `_PRIORITY_ORDER`; within one gapped
    dimension, questions come back in the order `QUESTIONS` lists them.
    """
    gapped = _gap_dimensions(spec)
    out: list[Question] = []
    for dim in _PRIORITY_ORDER:
        if dim not in gapped:
            continue
        for q in QUESTIONS.get(dim, ()):
            out.append(q)
            if len(out) >= limit:
                return tuple(out)
    return tuple(out)
