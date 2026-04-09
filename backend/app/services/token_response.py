from app.models import User
from app.models.enums import UserRole
from app.schemas.auth import Token
from app.services.auth_service import issue_token


def build_token_response(user: User) -> Token:
    role = user.role.value if isinstance(user.role, UserRole) else str(user.role)
    return Token(
        access_token=issue_token(user),
        token_type="bearer",
        role=UserRole(role),
        user_id=user.id,
    )
