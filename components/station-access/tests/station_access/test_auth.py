import json
from django.contrib.auth import get_user_model
from django.test import TestCase

class AuthenticationTests(TestCase):
    def setUp(self):
        get_user_model().objects.create_user(username="alice", password="secret")

    def test_session_endpoint_sets_csrf_cookie(self):
        response = self.client.get("/api/session/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("csrftoken", response.cookies)
        self.assertFalse(response.json()["authenticated"])

    def test_login_and_logout(self):
        response = self.client.post("/api/login/", data=json.dumps({"username": "alice", "password": "secret"}), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["authenticated"])
        self.assertTrue(self.client.get("/api/session/").json()["authenticated"])
        self.assertFalse(self.client.post("/api/logout/").json()["authenticated"])
