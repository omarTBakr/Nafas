"""
The specializations Nafas ships with, as data.

`scope` is what the scope classifier reads to decide whether a patient's
question belongs to this doctor; write it as a clinician would describe the
field's boundary. `always_escalate` lists topics that go to the doctor however
harmless the question looks. Rules that hold for every specialization —
emergencies, diagnoses, starting, stopping or changing a medicine or a dose —
live in the safety gates (conversation service), not here.

Editing this file changes what patients may ask: it is a clinical change and
is reviewed as one. `python -m nafas_identity.cli seed` applies it.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SpecializationSeed:
    code: str
    name_en: str
    name_ar: str
    scope: str
    in_scope_topics: list[str] = field(default_factory=list)
    always_escalate: list[str] = field(default_factory=list)


SPECIALIZATIONS: list[SpecializationSeed] = [
    SpecializationSeed(
        code="general_practice",
        name_en="General practice",
        name_ar="طب عام",
        scope=(
            "First-contact care for adults and children: common acute illnesses (colds, flu, sore throat, mild "
            "stomach upsets, minor injuries), preventive care and vaccinations, lifestyle advice, and follow-up of "
            "stable chronic conditions. Questions that clearly belong to a single specialty are out of scope."
        ),
        in_scope_topics=[
            "common cold and flu",
            "fever care at home",
            "vaccination schedules",
            "healthy lifestyle",
            "minor wounds",
        ],
        always_escalate=["fever lasting more than three days", "symptoms in infants under three months"],
    ),
    SpecializationSeed(
        code="internal_medicine",
        name_en="Internal medicine",
        name_ar="باطنة",
        scope=(
            "Adult non-surgical medicine: hypertension, diabetes, thyroid disorders, digestive complaints, "
            "liver and kidney function, anaemia, infections, and the interpretation of routine blood tests "
            "as explained by the doctor."
        ),
        in_scope_topics=["blood pressure", "blood sugar", "digestion and reflux", "cholesterol", "preparing for blood tests"],
        always_escalate=["new abnormal lab results", "blood in stool or vomit", "unexplained weight loss"],
    ),
    SpecializationSeed(
        code="cardiology",
        name_en="Cardiology",
        name_ar="قلب وأوعية دموية",
        scope=(
            "The heart and blood vessels: hypertension, coronary artery disease, heart failure, arrhythmias and "
            "palpitations, cholesterol, and preparation for and recovery from cardiac tests and procedures "
            "(ECG, echocardiography, stress tests, catheterisation)."
        ),
        in_scope_topics=[
            "blood pressure readings",
            "heart-healthy diet",
            "preparing for an echo or stress test",
            "exercise after a cardiac event",
        ],
        always_escalate=["chest pain or pressure", "fainting", "new or worsening shortness of breath", "anticoagulant questions"],
    ),
    SpecializationSeed(
        code="dermatology",
        name_en="Dermatology",
        name_ar="جلدية",
        scope=(
            "Skin, hair and nails: acne, eczema, psoriasis, fungal infections, hair loss, pigmentation, "
            "skin care routines, and follow-up of dermatological treatments."
        ),
        in_scope_topics=["skin care routine", "acne care", "eczema flare care", "sun protection", "hair loss"],
        always_escalate=["a changing or bleeding mole", "rapidly spreading rash with fever", "isotretinoin questions"],
    ),
    SpecializationSeed(
        code="pediatrics",
        name_en="Pediatrics",
        name_ar="أطفال",
        scope=(
            "Children from birth to adolescence: growth and development, feeding and nutrition, vaccinations, "
            "common childhood illnesses, and parents' questions about their child's care."
        ),
        in_scope_topics=["feeding and weaning", "growth milestones", "vaccination schedule", "common colds in children", "sleep"],
        always_escalate=[
            "any fever in an infant under three months",
            "dehydration signs",
            "breathing difficulty",
            "a medicine dose by weight",
        ],
    ),
    SpecializationSeed(
        code="obstetrics_gynecology",
        name_en="Obstetrics and gynecology",
        name_ar="نساء وتوليد",
        scope=(
            "Women's reproductive health: menstrual concerns, contraception, fertility, pregnancy follow-up and "
            "antenatal care, postpartum recovery, and menopause."
        ),
        in_scope_topics=["antenatal visit schedule", "pregnancy nutrition", "cycle tracking", "postpartum recovery"],
        always_escalate=[
            "bleeding in pregnancy",
            "reduced fetal movements",
            "severe abdominal pain",
            "medicines in pregnancy or breastfeeding",
        ],
    ),
    SpecializationSeed(
        code="endocrinology",
        name_en="Endocrinology",
        name_ar="غدد صماء وسكر",
        scope=(
            "Hormonal and metabolic conditions: diabetes (type 1, type 2, gestational), thyroid disease, obesity "
            "management, osteoporosis, and adrenal and pituitary disorders."
        ),
        in_scope_topics=["glucose monitoring", "diabetic diet", "thyroid test preparation", "foot care in diabetes"],
        always_escalate=["very high or very low glucose readings", "insulin dose questions", "symptoms of hypoglycaemia"],
    ),
    SpecializationSeed(
        code="orthopedics",
        name_en="Orthopedics",
        name_ar="عظام",
        scope=(
            "Bones, joints, muscles and ligaments: fractures and sprains, back and neck pain, arthritis, sports "
            "injuries, and rehabilitation before and after orthopedic surgery."
        ),
        in_scope_topics=["exercises after a sprain", "posture and back care", "cast care", "recovery after joint surgery"],
        always_escalate=[
            "numbness or weakness in a limb",
            "a swollen, hot, painful joint with fever",
            "wound problems after surgery",
        ],
    ),
    SpecializationSeed(
        code="ent",
        name_en="Ear, nose and throat",
        name_ar="أنف وأذن وحنجرة",
        scope=(
            "The ear, nose, sinuses, throat and voice: ear infections and hearing, sinusitis, allergic rhinitis, "
            "tonsillitis, snoring, hoarseness, and recovery after ENT procedures."
        ),
        in_scope_topics=["nasal rinsing", "allergy season care", "ear hygiene", "voice rest", "recovery after tonsillectomy"],
        always_escalate=["bleeding after tonsillectomy", "sudden hearing loss", "difficulty swallowing or breathing"],
    ),
    SpecializationSeed(
        code="ophthalmology",
        name_en="Ophthalmology",
        name_ar="رمد وعيون",
        scope=(
            "The eyes and vision: refractive errors, dry eye, conjunctivitis, glaucoma and cataract follow-up, "
            "diabetic eye screening, contact lens care, and recovery after eye surgery."
        ),
        in_scope_topics=["dry eye care", "contact lens hygiene", "screen time and eye strain", "recovery after cataract surgery"],
        always_escalate=["sudden loss or change of vision", "eye pain with redness", "flashes or new floaters", "eye injury"],
    ),
    SpecializationSeed(
        code="psychiatry",
        name_en="Psychiatry",
        name_ar="طب نفسي",
        scope=(
            "Mental health: anxiety, depression, sleep problems, stress, and follow-up of ongoing psychiatric "
            "care. The assistant offers general wellbeing information and logistics only; anything about the "
            "patient's own symptoms, risk or treatment goes to the doctor."
        ),
        in_scope_topics=["sleep hygiene", "what to expect at a first visit", "general stress management"],
        always_escalate=[
            "thoughts of self-harm or suicide",
            "any question about the patient's own medication",
            "worsening symptoms",
            "harm to others",
        ],
    ),
]
