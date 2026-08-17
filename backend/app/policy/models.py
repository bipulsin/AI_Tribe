"""SQLAlchemy models for the policy booking demo module."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class PolicyBookingRequest(Base):
    __tablename__ = "policy_booking_requests"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    booking_reference: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    session_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), index=True, nullable=False, default="started")
    current_step: Mapped[str] = mapped_column(String(64), nullable=False, default="welcome")
    previous_policy_declared: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    kyc_mode_used: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    agent = relationship("User")
    customer = relationship("PolicyCustomer", back_populates="booking", uselist=False, cascade="all, delete-orphan")
    vehicle = relationship("PolicyVehicle", back_populates="booking", uselist=False, cascade="all, delete-orphan")
    messages = relationship(
        "PolicyConversationMessage",
        back_populates="booking",
        cascade="all, delete-orphan",
        order_by="PolicyConversationMessage.created_at",
    )
    kyc_events = relationship("PolicyKycEvent", back_populates="booking", cascade="all, delete-orphan")
    quotes = relationship("PolicyQuoteOption", back_populates="booking", cascade="all, delete-orphan")
    issued_policy = relationship(
        "PolicyIssuedPolicy", back_populates="booking", uselist=False, cascade="all, delete-orphan"
    )


class PolicyCustomer(Base):
    __tablename__ = "policy_customers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    booking_request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("policy_booking_requests.id"), unique=True, nullable=False
    )
    name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(16), nullable=True)
    id_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    id_masked: Mapped[str | None] = mapped_column(String(32), nullable=True)
    id_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    dob: Mapped[str | None] = mapped_column(String(16), nullable=True)
    gender: Mapped[str | None] = mapped_column(String(16), nullable=True)
    address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    pincode: Mapped[str | None] = mapped_column(String(8), nullable=True)

    booking = relationship("PolicyBookingRequest", back_populates="customer")


class PolicyVehicle(Base):
    __tablename__ = "policy_vehicles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    booking_request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("policy_booking_requests.id"), unique=True, nullable=False
    )
    registration_number: Mapped[str] = mapped_column(String(16), index=True, nullable=False)
    make: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    color: Mapped[str | None] = mapped_column(String(32), nullable=True)
    fuel_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    owner_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="demo_fallback")
    raw_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    booking = relationship("PolicyBookingRequest", back_populates="vehicle")


class PolicyConversationMessage(Base):
    __tablename__ = "policy_conversation_messages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    booking_request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("policy_booking_requests.id"), index=True, nullable=False
    )
    sender: Mapped[str] = mapped_column(String(16), nullable=False)
    message_type: Mapped[str] = mapped_column(String(16), nullable=False, default="text")
    content_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    booking = relationship("PolicyBookingRequest", back_populates="messages")


class PolicyKycEvent(Base):
    __tablename__ = "policy_kyc_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    booking_request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("policy_booking_requests.id"), index=True, nullable=False
    )
    id_type: Mapped[str] = mapped_column(String(16), nullable=False)
    id_number_masked: Mapped[str] = mapped_column(String(32), nullable=False)
    validation_mode: Mapped[str] = mapped_column(String(64), nullable=False)
    validation_result: Mapped[str] = mapped_column(String(32), nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    demo_mode: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    booking = relationship("PolicyBookingRequest", back_populates="kyc_events")


class PolicyQuoteOption(Base):
    __tablename__ = "policy_quote_options"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    booking_request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("policy_booking_requests.id"), index=True, nullable=False
    )
    insurer_code: Mapped[str] = mapped_column(String(8), nullable=False)
    insurer_name: Mapped[str] = mapped_column(String(64), nullable=False)
    premium: Mapped[float] = mapped_column(Float, nullable=False)
    package_type: Mapped[str] = mapped_column(String(32), nullable=False)
    coverage_summary: Mapped[str] = mapped_column(Text, nullable=False)
    validity_note: Mapped[str] = mapped_column(String(128), nullable=False, default="Illustrative only · 7-day demo validity")
    source_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="demo_rules")
    selected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    booking = relationship("PolicyBookingRequest", back_populates="quotes")


class PolicyIssuedPolicy(Base):
    __tablename__ = "policy_issued_policies"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    booking_request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("policy_booking_requests.id"), unique=True, nullable=False
    )
    policy_reference: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    document_path: Mapped[str] = mapped_column(String(512), nullable=False)
    issue_date: Mapped[date] = mapped_column(Date, nullable=False)
    expiry_date: Mapped[date] = mapped_column(Date, nullable=False)
    source_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="demo_issuance")
    insurer_name: Mapped[str] = mapped_column(String(64), nullable=False)
    package_type: Mapped[str] = mapped_column(String(32), nullable=False)
    premium: Mapped[float] = mapped_column(Float, nullable=False)

    booking = relationship("PolicyBookingRequest", back_populates="issued_policy")


class PolicySettings(Base):
    __tablename__ = "policy_settings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, nullable=False)
    encrypted_payload: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
