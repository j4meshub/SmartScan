from .models import Role, User


def can_read_data(actor: User, owner: User) -> bool:
    if actor.id == owner.id:
        return True
    if actor.role == Role.super_admin:
        return True
    return actor.role == Role.admin and owner.role == Role.user


def can_manage_account(actor: User, target: User) -> bool:
    if actor.role not in (Role.admin, Role.super_admin):
        return False
    if target.role == Role.super_admin:
        return False
    if actor.id == target.id:
        return False
    if actor.role == Role.super_admin:
        return True
    return target.role == Role.user
