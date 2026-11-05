"""Domain models mirrored from the Go backend's ``internal/model`` package.

These are response shapes only — nothing here is used as tool input.
Every field name matches the Go ``json`` tag exactly, so a payload can be
validated straight from the wire without an adapter.

Optional Go fields use ``omitempty``, which means the key is simply
absent when zero-valued; the models therefore default every optional
field to ``None`` (or a neutral zero value) rather than requiring it.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Treatment(BaseModel):
    """A single charge line on a pet (Go: ``model.Treatment``)."""

    id: str
    item: str = ""
    category: str = ""
    amount: float = 0.0
    doctor: str | None = None
    date: str = ""
    note: str | None = None


class MedicalRecord(BaseModel):
    """A single visit record (Go: ``model.MedicalRecord``)."""

    id: str
    visitDate: str = ""
    doctor: str = ""
    diagnosis: str = ""
    symptoms: str | None = None
    treatment: str | None = None
    prescription: list[str] | None = None
    weightKg: float | None = None
    temperature: float | None = None
    followUp: str | None = None
    charge: float = 0.0
    createdAt: str = ""


class PetItem(BaseModel):
    """A single pet record (Go: ``model.Pet``).

    ``records`` and ``charges`` are ``null`` when the Go side has a nil
    slice (no history yet), and a list otherwise; both shapes are
    accepted here.
    """

    id: str
    name: str = ""
    species: str = ""
    breed: str | None = None
    gender: str | None = None
    ageMonths: int | None = None
    color: str | None = None
    chipNo: str | None = None

    ownerName: str = ""
    ownerPhone: str = ""
    ownerAddr: str | None = None

    doctor: str = ""
    disease: str = ""
    status: str = ""
    allergy: str | None = None
    note: str | None = None

    records: list[MedicalRecord] | None = None
    charges: list[Treatment] | None = None

    totalCost: float = 0.0
    visitCount: int = 0

    createdAt: str = ""
    updatedAt: str = ""


class PetSummary(BaseModel):
    """Response of ``GET /api/v1/pets/{id}/summary`` (Go: ``handleSummary``).

    A flat rollup: cost split by category and by doctor, the largest
    single charge, average cost per visit, the first/last visit dates and
    a one-line text history. ``costByCategory`` / ``costByDoctor`` are
    ``null`` when the pet has no charges yet (Go marshals a nil map).
    """

    id: str
    name: str = ""
    species: str = ""
    ownerName: str = ""
    ownerPhone: str = ""
    doctor: str = ""
    disease: str = ""
    status: str = ""

    totalCost: float = 0.0
    visitCount: int = 0
    chargeCount: int = 0

    costByCategory: dict[str, float] | None = None
    costByDoctor: dict[str, float] | None = None
    maxSingleCharge: float = 0.0
    avgCostPerVisit: float = 0.0

    firstVisit: str = ""
    lastVisit: str = ""
    historyText: str = ""


class HospitalStats(BaseModel):
    """Response of ``GET /api/v1/stats`` (Go: ``store.Stats``).

    ``topSpenders`` is capped by the ``top`` query parameter (default 5).
    The counters are clinic-wide, not per-doctor.
    """

    totalPets: int = 0
    totalRecords: int = 0
    totalCharges: int = 0
    totalRevenue: float = 0.0
    averageCost: float = 0.0
    maxCost: float = 0.0

    bySpecies: dict[str, int] | None = None
    byStatus: dict[str, int] | None = None
    byDoctor: dict[str, int] | None = None
    revenueByDoctor: dict[str, float] | None = None

    topSpenders: list[PetItem] | None = None
    logGarbagePct: float = Field(
        default=0.0,
        description=(
            "Share of the storage log that is dead space (0-100). "
            "High values mean the single-file DB is due for compaction."
        ),
    )


__all__ = [
    "Treatment", "MedicalRecord", "PetItem", "PetSummary", "HospitalStats",
]
