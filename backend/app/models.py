from sqlalchemy import Column, DateTime, Integer, JSON, String, func
from geoalchemy2 import Geometry

from .database import Base


class ImportedFeature(Base):
    __tablename__ = "imported_features"

    id = Column(Integer, primary_key=True, index=True)
    source = Column(String, nullable=False, index=True)
    layer = Column(String, nullable=False, index=True)
    geometry = Column(Geometry("GEOMETRY", srid=4326), nullable=False, index=True)
    properties = Column(JSON, nullable=False, default=dict)
    timestamp = Column(DateTime(timezone=True), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
