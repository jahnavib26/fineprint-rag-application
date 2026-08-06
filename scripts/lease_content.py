"""Synthetic lease content with ground truth attached.

Everything the eval suite asserts on is declared here, next to the text it comes
from, so a lease edit can't silently invalidate a case. ``generate_leases.py``
renders these to PDFs and dumps ``ground_truth.json`` beside them.

Three leases, chosen to exercise the three things that break naive RAG:

* ``maple-court``  — clean ``ARTICLE`` / ``14.`` / ``(b)`` structure, and two
  addenda that override the deposit and pet clauses. The override cases live here.
* ``birch-lane``   — ``Section 8 –`` and dotted ``14.2.1`` numbering, so the
  segmenter is exercised on a second style with deeper nesting.
* ``messy-loft``   — near-unstructured prose; must land in the fallback chunker.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ClauseSpec:
    """One clause as it will be printed, plus what evals expect of it."""

    number: str
    heading: str
    body: str
    clause_type: str = "other"
    parent: str | None = None


@dataclass
class DocumentSpec:
    doc_id: str
    title: str
    kind: str  # "original" | "addendum"
    signed_date: str
    clauses: list[ClauseSpec]
    preamble: str = ""


@dataclass
class LeaseSpec:
    lease_id: str
    documents: list[DocumentSpec]
    # question topic -> clause numbers that must be cited
    answerable: dict[str, list[str]] = field(default_factory=dict)
    # topics the lease is genuinely silent on; correct answer is a refusal
    not_covered: list[str] = field(default_factory=list)
    # original clause -> clause that supersedes it (the M5 fixture)
    overrides: dict[str, str] = field(default_factory=dict)
    # expected segmentation strategy: "clause_tree" | "fallback"
    strategy: str = "clause_tree"


# --------------------------------------------------------------------------
# maple-court: the flagship lease. Clean structure, two overriding addenda.
# --------------------------------------------------------------------------

_MAPLE_ORIGINAL = DocumentSpec(
    doc_id="maple-court-lease",
    title="RESIDENTIAL LEASE AGREEMENT",
    kind="original",
    signed_date="2024-06-01",
    preamble=(
        "This Residential Lease Agreement (the \"Lease\") is made on June 1, 2024, "
        "between Maple Court Holdings LLC (\"Landlord\") and the undersigned "
        "(\"Tenant\") for the premises at 411 Maple Court, Unit 3B."
    ),
    clauses=[
        ClauseSpec(
            number="I",
            heading="TERM AND RENT",
            body="",
            clause_type="other",
        ),
        ClauseSpec(
            number="1",
            heading="TERM",
            body=(
                "The term of this Lease shall commence on July 1, 2024 and shall "
                "terminate on June 30, 2025, unless sooner terminated in accordance "
                "with the provisions hereof. Tenant shall surrender the premises in "
                "the condition received, ordinary wear and tear excepted."
            ),
            clause_type="termination",
            parent="I",
        ),
        ClauseSpec(
            number="2",
            heading="MONTHLY RENT",
            body=(
                "Tenant shall pay to Landlord monthly rent in the amount of Two "
                "Thousand One Hundred Dollars ($2,100.00), payable in advance on the "
                "first day of each calendar month, without demand, deduction, or "
                "setoff."
            ),
            clause_type="fees",
            parent="I",
        ),
        ClauseSpec(
            number="3",
            heading="LATE CHARGES",
            body=(
                "If any installment of rent is not received by Landlord on or before "
                "the fifth (5th) day of the month in which it is due, Tenant shall pay "
                "a late charge of Seventy-Five Dollars ($75.00), plus Ten Dollars "
                "($10.00) for each additional day the rent remains unpaid. Late "
                "charges shall be deemed additional rent."
            ),
            clause_type="fees",
            parent="I",
        ),
        ClauseSpec(
            number="II",
            heading="SECURITY DEPOSIT",
            body="",
            clause_type="deposit",
        ),
        ClauseSpec(
            number="4",
            heading="AMOUNT OF DEPOSIT",
            body=(
                "Upon execution of this Lease, Tenant shall deposit with Landlord the "
                "sum of Two Thousand One Hundred Dollars ($2,100.00) as security for "
                "the faithful performance of Tenant's obligations hereunder."
            ),
            clause_type="deposit",
            parent="II",
        ),
        ClauseSpec(
            number="5",
            heading="RETURN OF DEPOSIT",
            body=(
                "Landlord shall return the security deposit, less any lawful "
                "deductions, within forty-five (45) days after the termination of this "
                "Lease and delivery of possession to Landlord, together with an "
                "itemized statement of any deductions taken."
            ),
            clause_type="deposit",
            parent="II",
        ),
        ClauseSpec(
            number="III",
            heading="USE AND OCCUPANCY",
            body="",
            clause_type="other",
        ),
        ClauseSpec(
            number="12",
            heading="GUESTS",
            body=(
                "Tenant may host guests upon the premises, provided that no guest shall "
                "occupy the premises for more than fourteen (14) consecutive days, nor "
                "more than thirty (30) days in any twelve (12) month period, without "
                "the prior written consent of Landlord. Any guest remaining beyond "
                "these limits shall be deemed an unauthorized occupant."
            ),
            clause_type="subletting",
            parent="III",
        ),
        ClauseSpec(
            number="14",
            heading="SUBLETTING AND ASSIGNMENT",
            body=(
                "Tenant shall not assign this Lease, nor sublet the premises or any "
                "portion thereof, except as expressly provided in this Section 14."
            ),
            clause_type="subletting",
            parent="III",
        ),
        ClauseSpec(
            number="14(a)",
            heading="",
            body=(
                "Tenant shall submit any request to sublet in writing not less than "
                "thirty (30) days prior to the proposed commencement of the sublease, "
                "together with the name, employment history, and credit report of the "
                "proposed subtenant."
            ),
            clause_type="subletting",
            parent="14",
        ),
        ClauseSpec(
            number="14(b)",
            heading="",
            body=(
                "Notwithstanding subsection (a), Tenant shall not sublet the premises "
                "on any short-term basis, including through any hosting platform, for "
                "any term of less than thirty (30) days. Landlord's consent shall not "
                "be required to be reasonable with respect to any such short-term "
                "arrangement, and any violation of this subsection shall constitute a "
                "material breach of this Lease."
            ),
            clause_type="subletting",
            parent="14",
        ),
        ClauseSpec(
            number="15",
            heading="PETS",
            body=(
                "No dog, cat, or other animal shall be kept upon the premises at any "
                "time. This prohibition shall not apply to service animals or "
                "assistance animals required by law to be accommodated."
            ),
            clause_type="pets",
            parent="III",
        ),
        ClauseSpec(
            number="IV",
            heading="MAINTENANCE AND REPAIRS",
            body="",
            clause_type="maintenance",
        ),
        ClauseSpec(
            number="18",
            heading="TENANT OBLIGATIONS",
            body=(
                "Tenant shall keep the premises in a clean and sanitary condition, "
                "shall promptly notify Landlord in writing of any needed repairs, and "
                "shall be responsible for replacement of light bulbs, smoke detector "
                "batteries, and air filters."
            ),
            clause_type="maintenance",
            parent="IV",
        ),
        ClauseSpec(
            number="19",
            heading="LANDLORD OBLIGATIONS",
            body=(
                "Landlord shall maintain the structural elements of the building, the "
                "plumbing, heating, and electrical systems, and all common areas in "
                "good repair. Landlord shall commence any emergency repair within "
                "twenty-four (24) hours of written notice."
            ),
            clause_type="maintenance",
            parent="IV",
        ),
        ClauseSpec(
            number="V",
            heading="TERMINATION",
            body="",
            clause_type="termination",
        ),
        ClauseSpec(
            number="22",
            heading="EARLY TERMINATION",
            body=(
                "Tenant may terminate this Lease prior to the expiration of the term "
                "upon sixty (60) days' prior written notice to Landlord and payment of "
                "a termination fee equal to two (2) months' rent. Tenant shall remain "
                "liable for all rent accruing during the notice period."
            ),
            clause_type="termination",
            parent="V",
        ),
        ClauseSpec(
            number="23",
            heading="HOLDOVER",
            body=(
                "Any holding over after the expiration of the term, with the consent "
                "of Landlord, shall be construed as a tenancy from month to month at a "
                "rental rate equal to one hundred fifty percent (150%) of the monthly "
                "rent then in effect."
            ),
            clause_type="termination",
            parent="V",
        ),
    ],
)

_MAPLE_ADDENDUM_ONE = DocumentSpec(
    doc_id="maple-court-addendum-1",
    title="FIRST ADDENDUM TO RESIDENTIAL LEASE AGREEMENT",
    kind="addendum",
    signed_date="2024-09-15",
    preamble=(
        "This First Addendum is entered into on September 15, 2024 and amends the "
        "Residential Lease Agreement dated June 1, 2024 between the parties. Except "
        "as expressly modified herein, all terms of the Lease remain in full force "
        "and effect."
    ),
    clauses=[
        ClauseSpec(
            number="A1",
            heading="AMENDMENT TO SECURITY DEPOSIT",
            body=(
                "Section 4 of the Lease is hereby amended and restated in its entirety "
                "to read as follows: Tenant shall maintain with Landlord a security "
                "deposit in the amount of Three Thousand One Hundred Fifty Dollars "
                "($3,150.00). Tenant shall remit the additional One Thousand Fifty "
                "Dollars ($1,050.00) within thirty (30) days of the date of this "
                "Addendum."
            ),
            clause_type="deposit",
        ),
        ClauseSpec(
            number="A2",
            heading="AMENDMENT TO RETURN OF DEPOSIT",
            body=(
                "Section 5 of the Lease is hereby amended to substitute twenty-one "
                "(21) days for forty-five (45) days as the period within which "
                "Landlord shall return the security deposit."
            ),
            clause_type="deposit",
        ),
    ],
)

_MAPLE_ADDENDUM_TWO = DocumentSpec(
    doc_id="maple-court-addendum-2",
    title="SECOND ADDENDUM TO RESIDENTIAL LEASE AGREEMENT — PET AGREEMENT",
    kind="addendum",
    signed_date="2025-01-10",
    preamble=(
        "This Second Addendum is entered into on January 10, 2025 and amends the "
        "Residential Lease Agreement dated June 1, 2024 between the parties."
    ),
    clauses=[
        ClauseSpec(
            number="B1",
            heading="PET PERMISSION",
            body=(
                "Notwithstanding Section 15 of the Lease, which is hereby superseded, "
                "Tenant is permitted to keep upon the premises one (1) domestic cat not "
                "exceeding fifteen (15) pounds in weight. No dog of any size shall be "
                "kept upon the premises. Tenant shall pay a one-time non-refundable pet "
                "fee of Four Hundred Dollars ($400.00) and additional monthly rent of "
                "Thirty-Five Dollars ($35.00) per month for the duration of the tenancy."
            ),
            clause_type="pets",
        ),
        ClauseSpec(
            number="B2",
            heading="PET DAMAGE",
            body=(
                "Tenant shall be liable for all damage caused by the permitted animal, "
                "including damage in excess of the security deposit, and shall "
                "indemnify Landlord against any claim arising from the animal."
            ),
            clause_type="pets",
        ),
    ],
)

MAPLE_COURT = LeaseSpec(
    lease_id="maple-court",
    documents=[_MAPLE_ORIGINAL, _MAPLE_ADDENDUM_ONE, _MAPLE_ADDENDUM_TWO],
    answerable={
        "short_term_sublet": ["14(b)"],
        "sublet_process": ["14(a)"],
        "guest_stay_limit": ["12"],
        "late_fee": ["3"],
        "early_termination": ["22"],
        "holdover": ["23"],
        "landlord_repairs": ["19"],
        "tenant_repairs": ["18"],
    },
    not_covered=[
        "who_pays_electricity",
        "parking_space",
        "renters_insurance_required",
        "smoking_policy",
        "washer_dryer_installation",
        "rent_increase_at_renewal",
        "mail_and_package_delivery",
    ],
    overrides={"4": "A1", "5": "A2", "15": "B1"},
)


# --------------------------------------------------------------------------
# birch-lane: second numbering style, deeper nesting, no addenda.
# --------------------------------------------------------------------------

_BIRCH_ORIGINAL = DocumentSpec(
    doc_id="birch-lane-lease",
    title="APARTMENT LEASE",
    kind="original",
    signed_date="2025-02-01",
    preamble=(
        "This Apartment Lease is made as of February 1, 2025 by and between Birch "
        "Lane Properties, Inc. and the Resident named below, covering Apartment 7 at "
        "88 Birch Lane."
    ),
    clauses=[
        ClauseSpec(
            number="1",
            heading="RENT AND CHARGES",
            body=(
                "Resident shall pay monthly rent of One Thousand Eight Hundred Dollars "
                "($1,800.00) due on the first day of each month."
            ),
            clause_type="fees",
        ),
        ClauseSpec(
            number="1.1",
            heading="",
            body=(
                "Rent not received within three (3) days of the due date shall incur a "
                "late fee equal to five percent (5%) of the monthly rent."
            ),
            clause_type="fees",
            parent="1",
        ),
        ClauseSpec(
            number="1.2",
            heading="",
            body=(
                "Any check returned for insufficient funds shall incur a charge of "
                "Fifty Dollars ($50.00) in addition to any applicable late fee."
            ),
            clause_type="fees",
            parent="1",
        ),
        ClauseSpec(
            number="2",
            heading="SECURITY DEPOSIT",
            body=(
                "Resident shall pay a security deposit of One Thousand Eight Hundred "
                "Dollars ($1,800.00) prior to occupancy, to be held in an "
                "interest-bearing account as required by law."
            ),
            clause_type="deposit",
        ),
        ClauseSpec(
            number="2.1",
            heading="",
            body=(
                "The deposit shall be returned within thirty (30) days of move-out, "
                "less deductions for damage beyond ordinary wear and tear, unpaid rent, "
                "and cleaning costs necessary to restore the apartment to move-in "
                "condition."
            ),
            clause_type="deposit",
            parent="2",
        ),
        ClauseSpec(
            number="2.1.1",
            heading="",
            body=(
                "Resident may request a pre-move-out inspection not more than "
                "fourteen (14) days before vacating, at which Landlord shall identify "
                "any deficiency Resident may cure to avoid deduction."
            ),
            clause_type="deposit",
            parent="2.1",
        ),
        ClauseSpec(
            number="6",
            heading="UTILITIES",
            body=(
                "Resident shall be responsible for electricity, gas, and internet "
                "service. Landlord shall pay for water, sewer, and trash collection."
            ),
            clause_type="fees",
        ),
        ClauseSpec(
            number="8",
            heading="QUIET ENJOYMENT",
            body=(
                "Resident shall not create or permit any noise audible outside the "
                "apartment between the hours of 10:00 p.m. and 8:00 a.m. Repeated "
                "violations shall constitute grounds for termination."
            ),
            clause_type="other",
        ),
        ClauseSpec(
            number="9",
            heading="PETS",
            body=(
                "Dogs and cats are permitted with prior written approval, subject to a "
                "refundable pet deposit of Three Hundred Dollars ($300.00) per animal "
                "and a limit of two (2) animals per apartment. Aggressive breeds, as "
                "designated by Landlord's insurer, are prohibited."
            ),
            clause_type="pets",
        ),
        ClauseSpec(
            number="11",
            heading="SUBLETTING",
            body=(
                "Resident shall not sublet the apartment or assign this Lease without "
                "Landlord's prior written consent, which shall not be unreasonably "
                "withheld."
            ),
            clause_type="subletting",
        ),
        ClauseSpec(
            number="14",
            heading="TERMINATION AND NOTICE",
            body=(
                "Either party may terminate this Lease at the end of the term by "
                "giving not less than sixty (60) days' written notice. Early "
                "termination by Resident requires payment of a fee equal to one and "
                "one-half (1.5) months' rent."
            ),
            clause_type="termination",
        ),
    ],
)

BIRCH_LANE = LeaseSpec(
    lease_id="birch-lane",
    documents=[_BIRCH_ORIGINAL],
    answerable={
        "deposit_return_window": ["2.1"],
        "pre_move_out_inspection": ["2.1.1"],
        "who_pays_electricity": ["6"],
        "late_fee": ["1.1"],
        "returned_check_fee": ["1.2"],
        "pets_allowed": ["9"],
        "quiet_hours": ["8"],
        "early_termination": ["14"],
    },
    not_covered=[
        "parking_space",
        "guest_stay_limit",
        "renters_insurance_required",
        "smoking_policy",
    ],
)


# --------------------------------------------------------------------------
# messy-loft: deliberately unstructured. Must route to the fallback chunker.
# --------------------------------------------------------------------------

_MESSY_BODY = """\
LOFT OCCUPANCY AGREEMENT

This agreement is between the owner of the loft space at 12 Warehouse Row and \
the occupant, and sets out the understanding between them as to the use of the \
space. The occupant agrees to pay one thousand four hundred dollars each month, \
due at the beginning of the month, and the owner agrees to keep the freight \
elevator and the building entry in working order. Neither party intends this to \
be a formal lease of the kind used for apartments, and the parties have written \
it in plain language on purpose.

Regarding the deposit, the occupant has paid one thousand four hundred dollars \
which the owner holds and will return after the occupant leaves and the space \
has been looked over, normally within a month, minus anything needed to repair \
damage that goes beyond ordinary use of a loft space. The owner will explain any \
deduction in writing. The occupant should understand that the loft is an older \
industrial building and that marks on the concrete floor and brick walls are \
expected and will not be charged for.

The occupant may have people over and may have someone stay for a while, but the \
loft is for one occupant and anyone staying longer than about a month should be \
discussed with the owner first. Subletting the whole space to someone else is not \
something the owner agrees to in advance, and the occupant should ask. Short stays \
arranged over the internet are not permitted at all, because the building \
insurance does not cover them and the other occupants have objected.

Animals are a case-by-case matter and the occupant should ask before bringing one \
in. Noise carries in the building and the occupant should be considerate after \
ten at night. Either party can end this arrangement with two months of notice, and \
if the occupant leaves earlier than that, the occupant owes rent through the end \
of the notice period. The owner will not raise the rent during the first year.
"""

MESSY_LOFT = LeaseSpec(
    lease_id="messy-loft",
    documents=[
        DocumentSpec(
            doc_id="messy-loft-agreement",
            title="",  # title lives inside the prose body
            kind="original",
            signed_date="2025-03-20",
            clauses=[],
        )
    ],
    answerable={},
    not_covered=["parking_space", "renters_insurance_required"],
    strategy="fallback",
)

MESSY_LOFT_TEXT = _MESSY_BODY

ALL_LEASES: list[LeaseSpec] = [MAPLE_COURT, BIRCH_LANE, MESSY_LOFT]
