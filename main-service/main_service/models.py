"""Product requirements owned by the main service."""
from typing import Literal
from pydantic import BaseModel, Field

# ---------------------------------------------------------------- spec proposal (what Claude / rules return)

Category = Literal["electronics", "computer_accessories", "office_supplies", "tools", "safety_equipment",
                   "furniture", "software", "cleaning_supplies", "weapons", "medicine", "age_restricted",
                   "gift_cards", "other"]

Criterion = Literal["price", "quality", "delivery_speed", "brand_match", "warranty", "supplier_rating",
                    "durability", "compatibility"]


Op = Literal["eq", "ne", "ge", "le"]

Unit = Literal["mm", "cm", "m", "in", "ft", "g", "kg", "oz", "lb", "MB", "GB", "TB", "W", "V", "mAh", "Hz",
               "GHz", "count"]

Condition = Literal["new", "refurbished", "used", "unspecified"]


class Constraint(BaseModel):
    field: str = Field(description="snake_case property name without unit, e.g. power, ram, length, connector, compatible_with")
    op: Op = Field(description="eq, ne, ge (at least) or le (at most)")
    value: str = Field(description="The value: a plain number for numeric fields (e.g. '65', '15.6'), else the text value")
    unit: Unit | None = Field(default=None, description="Unit of a numeric value; null for text values")
    required: bool = Field(description="True if the item is useless without it; false if merely preferred")


class Weight(BaseModel):
    criterion: Criterion
    weight: int = Field(description="Relative importance 0-100; weights should add up to 100")


class SpecProposal(BaseModel):
    understood: bool = Field(description="False if the text is not a purchase request or is too vague to search")
    unclear_reason: str | None = Field(default=None, description="Why it could not be understood, if understood is false")
    item: str = Field(description="What to buy, as a short noun phrase")
    category: Category
    quantity: int = Field(description="Number of units requested; 1 if not stated")
    condition: Condition = Field(description="new / refurbished / used if the request says so, else unspecified")
    constraints: list[Constraint]
    unsupported_requirements: list[str] = Field(default_factory=list,
        description="Explicit requested requirements that could not be represented as typed constraints; never silently omit them")
    weights: list[Weight]
    stated_budget_cents: int | None = Field(default=None, description="Any budget or price ceiling written in the request, in integer cents; null if none")
