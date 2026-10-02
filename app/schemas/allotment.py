import enum
from typing import Optional
from pydantic import BaseModel, Field


class AllotmentQueryType(str, enum.Enum):
    PAN = "PAN"
    APPLICATION_NO = "APPLICATION_NO"
    DP_CLIENT_ID = "DP_CLIENT_ID"


class AllotmentStatus(str, enum.Enum):
    ALLOTTED = "ALLOTTED"
    NOT_ALLOTTED = "NOT_ALLOTTED"
    NOT_FOUND = "NOT_FOUND"
    PENDING = "PENDING"
    ERROR = "ERROR"


class RegistrarCompanyItem(BaseModel):
    company_id: str = Field(..., description="Unique company identifier on the registrar system")
    company_name: str = Field(..., description="Company name as shown on registrar portal")


class AllotmentQueryRequest(BaseModel):
    company_id: str = Field(..., description="Company identifier on Link Intime (e.g. '1052' or 'TATATECH')")
    query_type: AllotmentQueryType = Field(default=AllotmentQueryType.PAN, description="PAN, APPLICATION_NO, or DP_CLIENT_ID")
    query_value: str = Field(..., description="The PAN number, application number, or DP ID / Client ID")


class AllotmentResultResponse(BaseModel):
    success: bool
    status: AllotmentStatus
    company_name: str
    company_id: str
    applicant_name: Optional[str] = None
    pan: Optional[str] = None
    application_no: Optional[str] = None
    dp_client_id: Optional[str] = None
    shares_applied: Optional[int] = None
    shares_allotted: Optional[int] = None
    refund_amount: Optional[float] = None
    message: str
    source_registrar: str = "Link Intime"
