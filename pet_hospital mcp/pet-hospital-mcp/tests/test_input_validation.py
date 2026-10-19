"""Input validation for ``ListPetsInput``.

These tests exercise the Pydantic model directly, so no HTTP and no
MCP SDK is involved. The model is the first line of defence: anything
it rejects never reaches the tool function.
"""

from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from pet_hospital_mcp.tools.list_pets import ListPetsInput


class TestSpeciesValidation:
    def test_valid_species_accepted(self) -> None:
        for s in ("犬", "猫", "兔", "鸟", "仓鼠", "爬宠", "其他"):
            assert ListPetsInput(species=s).species == s

    def test_invalid_species_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ListPetsInput(species="鱼")

    def test_none_species_accepted(self) -> None:
        assert ListPetsInput(species=None).species is None


class TestStatusValidation:
    def test_valid_status_accepted(self) -> None:
        for s in ("待就诊", "就诊中", "住院中", "已康复", "慢性病随访"):
            assert ListPetsInput(status=s).status == s

    def test_invalid_status_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ListPetsInput(status="治愈")


class TestSortByAndOrder:
    def test_valid_sortby_accepted(self) -> None:
        assert ListPetsInput(sortBy="totalCost").sortBy == "totalCost"

    def test_invalid_sortby_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ListPetsInput(sortBy="price")

    def test_valid_order_accepted(self) -> None:
        assert ListPetsInput(order="asc").order == "asc"
        assert ListPetsInput(order="desc").order == "desc"

    def test_invalid_order_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ListPetsInput(order="up")


class TestPaginationValidation:
    def test_page_must_be_at_least_1(self) -> None:
        with pytest.raises(ValidationError):
            ListPetsInput(page=0)
        assert ListPetsInput(page=1).page == 1

    def test_pagesize_bounds(self) -> None:
        with pytest.raises(ValidationError):
            ListPetsInput(pageSize=0)
        with pytest.raises(ValidationError):
            ListPetsInput(pageSize=501)
        assert ListPetsInput(pageSize=1).pageSize == 1
        assert ListPetsInput(pageSize=500).pageSize == 500

    def test_defaults(self) -> None:
        m = ListPetsInput()
        assert m.page == 1
        assert m.pageSize == 20


class TestCostBounds:
    def test_negative_min_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ListPetsInput(min=-0.01)

    def test_negative_max_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ListPetsInput(max=-1)

    def test_nan_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ListPetsInput(min=float("nan"))
        with pytest.raises(ValidationError):
            ListPetsInput(max=float("nan"))

    def test_infinity_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ListPetsInput(min=float("inf"))
        with pytest.raises(ValidationError):
            ListPetsInput(max=float("inf"))
        with pytest.raises(ValidationError):
            ListPetsInput(min=float("-inf"))


class TestUnknownFieldsAndTypes:
    def test_unknown_field_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ListPetsInput(unknownParam="x")

    def test_wrong_type_for_page_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ListPetsInput(page="abc")

    def test_wrong_type_for_species_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ListPetsInput(species=123)
