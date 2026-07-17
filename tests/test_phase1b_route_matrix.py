PHASE1B_ROUTES = {
    ("GET", "/dashboards/summary"),
    ("GET", "/contacts"), ("POST", "/contacts"),
    ("GET", "/contacts/{contactId}"), ("PATCH", "/contacts/{contactId}"),
    ("PATCH", "/contacts/{contactId}/preferences"),
    ("GET", "/contacts/{contactId}/activities"),
    ("GET", "/leads"), ("POST", "/leads"),
    ("GET", "/leads/{leadId}"), ("PATCH", "/leads/{leadId}"),
    ("POST", "/leads/{leadId}/assignments"), ("GET", "/leads/{leadId}/assignments"),
    ("POST", "/leads/{leadId}/reassignment-requests"),
    ("GET", "/reassignment-requests"),
    ("POST", "/reassignment-requests/{requestId}/approve"),
    ("POST", "/reassignment-requests/{requestId}/reject"),
    ("POST", "/reassignment-requests/{requestId}/cancel"),
    ("GET", "/users/counsellor-options"), ("GET", "/users"), ("POST", "/users"),
    ("GET", "/users/{userId}"), ("PATCH", "/users/{userId}"),
    ("POST", "/users/{userId}/reset-password"),
    ("POST", "/contact-imports/analyze"),
    ("POST", "/contact-imports/{importId}/preview"),
    ("POST", "/contact-imports/{importId}/commit"),
    ("GET", "/contact-imports/{importId}"),
    ("GET", "/contact-imports/{importId}/rejections"),
}


def test_phase1b_route_matrix_is_registered_and_legacy_contact_routes_are_absent(client):
    registered = {
        (method, route.path)
        for route in client.app.routes
        for method in getattr(route, "methods", set())
    }
    assert PHASE1B_ROUTES.issubset(registered)
    paths = {path for _, path in registered}
    assert "/users/all" not in paths
    assert "/users/bulk-upload" not in paths
