from app.services.oidc import normalize_roles, primary_role


def test_normalize_roles_supports_multiple_and_aliases():
    roles = normalize_roles(["requester", "RAIO", "admin"], {"requester", "reviewer", "admin"})
    assert roles == ["requester", "reviewer", "admin"]
    assert primary_role(roles) == "admin"


def test_normalize_roles_defaults_to_requester():
    assert normalize_roles([], {"requester", "reviewer", "admin"}) == ["requester"]
    assert primary_role([]) == "requester"
