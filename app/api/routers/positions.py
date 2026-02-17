"""
Positions router — kept for backwards compatibility.
Redirects to credit assessment endpoints.
"""
from fastapi import APIRouter
from app.api.routers.assessments import router as assessments_router

# This module is no longer the primary router.
# Import the assessments router if needed, or remove this file.
router = APIRouter()
