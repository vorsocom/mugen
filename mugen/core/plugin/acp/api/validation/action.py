"""Provides Pydantic data validators for action endpoints."""

from dataclasses import dataclass
from typing import Optional

from pydantic import EmailStr, SecretStr

from mugen.core.plugin.acp.contract.api.validation import (
    IValidationBase,
    IRowVersionValidation,
)


@dataclass
class UserActionResetPasswordAdmin(IValidationBase, IRowVersionValidation):
    """A Pydantic data validator for the resetpasswordadmin action on a User entity."""

    new_password: SecretStr

    confirm_new_password: SecretStr


@dataclass
class UserActionResetPasswordUser(IValidationBase, IRowVersionValidation):
    """A Pydantic data validator for the resetpassworduser action on a User entity."""

    current_password: SecretStr

    new_password: SecretStr

    confirm_new_password: SecretStr


@dataclass
class UserActionUpdateProfile(IValidationBase, IRowVersionValidation):
    """A Pydantic data validator for the updateprofile action on a User entity."""

    first_name: Optional[str] = None

    last_name: Optional[str] = None


@dataclass
class UserActionUpdateRoles(IValidationBase):
    """A Pydantic data validator for the updateroles action on a User entity."""

    roles: list[str]


@dataclass
class UsersActionProvision(IValidationBase):
    """A Pydantic data validator for the provision action on the Users entity set."""

    username: str

    password: SecretStr

    login_email: EmailStr

    first_name: str

    last_name: str
