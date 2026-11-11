from datetime import date, datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")

DISCLAIMER = ("Risk scores and alerts are investigative indicators produced from synthetic data. "
              "They are not determinations of fraud or wrongdoing and require human review.")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    size: int


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class AccountOut(ORM):
    account_id: str
    customer_id: str
    account_type: str
    country: str
    bank_id: str
    initial_balance: float
    opened_date: date | None


class CustomerSummary(ORM):
    customer_id: str
    full_name: str
    segment: str
    country: str
    kyc_level: str
    pep_flag: bool
    onboarding_date: date
    risk_score: float | None = None
    risk_level: str | None = None


class RiskIndicator(BaseModel):
    code: str
    label: str
    metric: str
    value: float | bool | int | None
    threshold: float | bool | int | list | None
    weight: float


class CustomerRiskOut(BaseModel):
    customer_id: str
    risk_score: float
    risk_level: str
    indicators: list[RiskIndicator]
    profile: dict
    scoring_version: str
    computed_at: datetime | None
    disclaimer: str = DISCLAIMER


class CustomerDetail(CustomerSummary):
    occupation: str | None
    date_of_birth: date | None
    accounts: list[AccountOut]
    risk: CustomerRiskOut | None = None
    alert_count: int = 0


class Factor(BaseModel):
    feature: str
    value: float
    contribution: float
    description: str


class PredictionOut(BaseModel):
    fraud_probability: float
    anomaly_score: float | None
    risk_score: float
    risk_band: str
    top_factors: list[Factor]
    model_version_id: int


class TransactionOut(BaseModel):
    transaction_id: int
    sender_account_id: str
    receiver_account_id: str
    sender_customer_id: str
    receiver_customer_id: str
    tx_type: str
    category: str
    amount: float
    currency: str
    timestamp: datetime
    is_cross_border: bool
    risk_score: float | None = None
    risk_band: str | None = None
    fraud_probability: float | None = None
    anomaly_score: float | None = None


class TransactionDetail(TransactionOut):
    prediction: PredictionOut | None = None
    sender_name: str | None = None
    receiver_name: str | None = None
    disclaimer: str = DISCLAIMER


class ScoreRequest(BaseModel):
    sender_account_id: str = Field(min_length=3, max_length=20)
    receiver_account_id: str = Field(min_length=3, max_length=20)
    amount: float = Field(gt=0, lt=1e9)
    tx_type: str = Field(pattern="^(TRANSFER|PAYMENT|WIRE)$")
    timestamp: datetime


class ScoreResponse(BaseModel):
    fraud_probability: float
    anomaly_score: float
    risk_score: float
    risk_band: str
    top_factors: list[Factor]
    features: dict[str, float]
    model_version_id: int
    is_cross_border: bool
    persisted: bool = False
    disclaimer: str = DISCLAIMER


class AlertOut(ORM):
    id: int
    alert_type: str
    source: str
    severity: str
    status: str
    customer_id: str
    account_id: str | None
    transaction_id: int | None
    score: float
    reasons: list[str]
    created_at: datetime | None
    customer_name: str | None = None


class ModelVersionOut(ORM):
    id: int
    model_name: str
    version: str
    model_type: str
    algorithm: str
    features: list[str]
    hyperparameters: dict
    metrics: dict
    feature_importance: dict
    training_data: dict
    is_active: bool
    created_at: datetime | None


class AuditLogOut(ORM):
    id: int
    actor: str
    action: str
    entity_type: str | None
    entity_id: str | None
    details: dict
    created_at: datetime | None
