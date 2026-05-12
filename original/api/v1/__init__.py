"""
api/v1/__init__.py — API v1 router composition.

Combines all v1 endpoints into a single router.
"""

from fastapi import APIRouter

from .admin import router as admin_router
from .auth import router as auth_router
from .paper_import import router as import_router
from .students import router as students_router
from .submissions import router as submissions_router

v1_router = APIRouter()
v1_router.include_router(auth_router)
v1_router.include_router(students_router)
v1_router.include_router(submissions_router)
v1_router.include_router(admin_router)
v1_router.include_router(import_router)

__all__ = ["v1_router"]
