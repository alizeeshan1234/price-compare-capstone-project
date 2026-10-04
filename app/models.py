"""Database tables."""
from datetime import datetime
from sqlalchemy import Column, Integer, Float, String, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship

from .database import Base


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True)
    url = Column(String(2048), nullable=False, unique=True)
    title = Column(String(512), nullable=False, default="Untitled product")
    store = Column(String(64), nullable=False)
    target_price = Column(Float, nullable=False)
    currency = Column(String(8), nullable=False, default="INR")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Health tracking
    last_checked_at = Column(DateTime, nullable=True)
    last_error = Column(Text, nullable=True)

    prices = relationship("PriceHistory", back_populates="product", cascade="all, delete-orphan",
                          order_by="PriceHistory.checked_at")
    alerts = relationship("Alert", back_populates="product", cascade="all, delete-orphan")
    logs = relationship("ScrapeLog", back_populates="product", cascade="all, delete-orphan")

    @property
    def current_price(self):
        return self.prices[-1].price if self.prices else None

    @property
    def lowest_price(self):
        return min((p.price for p in self.prices), default=None)

    @property
    def highest_price(self):
        return max((p.price for p in self.prices), default=None)

    @property
    def average_price(self):
        if not self.prices:
            return None
        return sum(p.price for p in self.prices) / len(self.prices)

    @property
    def in_stock(self):
        return self.prices[-1].in_stock if self.prices else None


class PriceHistory(Base):
    __tablename__ = "price_history"

    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)
    price = Column(Float, nullable=False)
    in_stock = Column(Boolean, nullable=False, default=True)
    checked_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    product = relationship("Product", back_populates="prices")


class Alert(Base):
    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)
    price = Column(Float, nullable=False)
    sent_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    delivered = Column(Boolean, nullable=False, default=False)

    product = relationship("Product", back_populates="alerts")


class ScrapeLog(Base):
    """One row per scrape attempt, used for the success-rate metric."""
    __tablename__ = "scrape_logs"

    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)
    success = Column(Boolean, nullable=False)
    message = Column(Text, nullable=True)
    duration_ms = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    product = relationship("Product", back_populates="logs")
