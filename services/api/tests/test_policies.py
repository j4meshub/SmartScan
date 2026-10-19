from types import SimpleNamespace

from services.api.app.models import Role
from services.api.app.policies import can_manage_account, can_read_data


def user(user_id: str, role: Role):
    return SimpleNamespace(id=user_id, role=role)


def test_data_access_matrix():
    regular = user("u1", Role.user)
    other = user("u2", Role.user)
    admin = user("a1", Role.admin)
    other_admin = user("a2", Role.admin)
    super_admin = user("s1", Role.super_admin)
    assert can_read_data(regular, regular)
    assert not can_read_data(regular, other)
    assert can_read_data(admin, other)
    assert not can_read_data(admin, other_admin)
    assert not can_read_data(admin, super_admin)
    assert can_read_data(super_admin, other_admin)


def test_super_admin_cannot_be_managed():
    admin = user("a1", Role.admin)
    super_admin = user("s1", Role.super_admin)
    regular = user("u1", Role.user)
    assert can_manage_account(admin, regular)
    assert not can_manage_account(admin, super_admin)
    assert not can_manage_account(admin, admin)
