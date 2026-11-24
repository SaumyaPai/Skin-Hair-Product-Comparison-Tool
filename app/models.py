"""What a valid request looks like. FastAPI checks every request against these shapes
and answers 422 with a clear message if something is wrong."""
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SkinType = Literal["oily", "dry", "combination", "normal", "not sure"]
ScalpType = Literal["oily", "dry", "normal", "not sure"]


class Profile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    skin_type: Optional[SkinType] = None
    scalp_type: Optional[ScalpType] = None
    sensitive: bool = False
    avoid_fragrance: bool = False


class ProductIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_name: str = Field(min_length=1, max_length=60)
    barcode: Optional[str] = None
    ingredients_text: Optional[str] = Field(default=None, max_length=5000)
    extracted_text: Optional[str] = Field(default=None, max_length=5000)

    @field_validator("display_name")
    @classmethod
    def strip_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("display_name can't be blank")
        return v

    @field_validator("barcode")
    @classmethod
    def check_barcode(cls, v):
        if v is None or not v.strip():
            return None
        v = v.strip()
        if not v.isdigit() or not 8 <= len(v) <= 14:
            raise ValueError("barcode must be 8 to 14 digits")
        return v

    @model_validator(mode="after")
    def needs_one_input(self):
        if not (self.barcode or (self.ingredients_text or "").strip() or (self.extracted_text or "").strip()):
            raise ValueError("each product needs a barcode, ingredients_text or extracted_text")
        return self


class CompareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    product_type: str
    concerns: list[str] = Field(min_length=1, max_length=3)
    profile: Profile = Profile()
    products: list[ProductIn] = Field(min_length=2, max_length=4)

    @field_validator("concerns")
    @classmethod
    def unique_concerns(cls, v):
        if len(set(v)) != len(v):
            raise ValueError("each concern can only be chosen once")
        return v

    @model_validator(mode="after")
    def unique_names(self):
        names = [p.display_name.casefold() for p in self.products]
        if len(set(names)) != len(names):
            raise ValueError("each product needs a different display_name")
        return self
