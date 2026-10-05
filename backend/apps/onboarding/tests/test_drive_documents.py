"""Employee documents → Google Drive (drive.py, settings + documents API)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings

from apps.onboarding.drive import DriveError, employee_folder_name, parse_folder_id
from apps.onboarding.google_auth import (
    DRIVE_CONNECT_SESSION_KEY,
    DRIVE_SCOPE,
    GoogleOAuth2WithOptionalDrive,
    has_drive_access,
)
from apps.onboarding.models import EmployeeDocument, OnboardingProfile, OnboardingSettings
from apps.planner.tests.factories import PersonFactory

User = get_user_model()
SCHED = "scheduler@blackcapitaltechnology.com"
FOLDER_ID = "1AbCdEfGhIjKlMnOpQrStUv"


def _fake_service(*, existing=None, root_mime="application/vnd.google-apps.folder"):
    """A MagicMock shaped like drive.files() with canned responses."""
    service = MagicMock()
    files = service.files.return_value
    files.get.return_value.execute.return_value = {
        "id": FOLDER_ID, "name": "Employees", "mimeType": root_mime, "trashed": False,
    }
    files.list.return_value.execute.return_value = {"files": existing or []}

    def create(**kwargs):
        call = MagicMock()
        body = kwargs["body"]
        if body.get("mimeType") == "application/vnd.google-apps.folder":
            call.execute.return_value = {"id": "emp-folder-1"}
        else:
            call.execute.return_value = {
                "id": "file-1", "name": body["name"], "webViewLink": "https://drive/file-1",
                "mimeType": "application/pdf", "size": "11",
            }
        return call

    files.create.side_effect = create
    return service


class ParseAndScopeTests(TestCase):
    def test_parse_folder_id(self):
        self.assertEqual(parse_folder_id(f"https://drive.google.com/drive/folders/{FOLDER_ID}?usp=sharing"), FOLDER_ID)
        self.assertEqual(parse_folder_id(f"https://drive.google.com/drive/u/0/folders/{FOLDER_ID}"), FOLDER_ID)
        self.assertEqual(parse_folder_id(f"https://drive.google.com/open?id={FOLDER_ID}"), FOLDER_ID)
        self.assertEqual(parse_folder_id(FOLDER_ID), FOLDER_ID)
        with self.assertRaises(DriveError):
            parse_folder_id("Employees")

    def test_drive_scope_only_when_connecting(self):
        strategy = MagicMock()
        strategy.setting.return_value = None
        backend = GoogleOAuth2WithOptionalDrive(strategy=strategy)
        session = {}
        strategy.session_get.side_effect = lambda k, d=None: session.get(k, d)
        with patch("social_core.backends.oauth.BaseOAuth2.get_scope", return_value=["email"]):
            self.assertNotIn(DRIVE_SCOPE, backend.get_scope())
            session[DRIVE_CONNECT_SESSION_KEY] = True
            self.assertIn(DRIVE_SCOPE, backend.get_scope())

    def test_has_drive_access_reads_granted_scopes(self):
        from social_django.models import UserSocialAuth

        user = User.objects.create_user(username="s", email=SCHED)
        self.assertFalse(has_drive_access(user))
        UserSocialAuth.objects.create(
            user=user, provider="google-oauth2", uid=SCHED,
            extra_data={"refresh_token": "r", "scope": "email " + DRIVE_SCOPE},
        )
        self.assertTrue(has_drive_access(user))


@override_settings(ONBOARDING_SCHEDULER_EMAIL=SCHED)
class DocumentsApiTests(TestCase):
    def setUp(self):
        self.client = Client()
        group, _ = Group.objects.get_or_create(name="manager")
        self.manager = User.objects.create_user(username="mgr", email="mgr@blackcapitaltechnology.com")
        self.manager.groups.add(group)
        self.scheduler = User.objects.create_user(username="sched", email=SCHED)
        self.person = PersonFactory(legacy_id="E100", email="anna@x.dk", name="Anna Hansen")
        emp = User.objects.create_user(username="anna", email="anna@x.dk", is_active=False)
        self.profile = OnboardingProfile.objects.create(
            user=emp, erp_employee_id="E100", first_name="Anna", last_name="Hansen"
        )
        self.person.onboarding_profile = self.profile
        self.person.save(update_fields=["onboarding_profile"])
        self.client.force_login(self.manager)
        self.url = "/api/onboarding/manage/employees/E100/documents"

    def _upload(self, *names):
        files = [SimpleUploadedFile(n, b"hello world", content_type="application/pdf") for n in names]
        return self.client.post(self.url, data={"file": files})

    def test_folder_name(self):
        self.assertEqual(employee_folder_name(self.profile), "Anna Hansen (E100)")

    @patch("apps.onboarding.google_auth.has_drive_access", return_value=True)
    def test_settings_put_validates_folder(self, _):
        service = _fake_service()
        with patch("apps.onboarding.drive._service", return_value=service):
            r = self.client.put(
                "/api/onboarding/manage/settings",
                data={"drive_root_folder": f"https://drive.google.com/drive/folders/{FOLDER_ID}"},
                content_type="application/json",
            )
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["drive_root_folder_name"], "Employees")
        self.assertEqual(OnboardingSettings.load().drive_root_folder_id, FOLDER_ID)

    @patch("apps.onboarding.google_auth.has_drive_access", return_value=True)
    def test_settings_put_rejects_non_folder(self, _):
        with patch("apps.onboarding.drive._service", return_value=_fake_service(root_mime="application/pdf")):
            r = self.client.put(
                "/api/onboarding/manage/settings",
                data={"drive_root_folder": FOLDER_ID}, content_type="application/json",
            )
        self.assertEqual(r.status_code, 400)

    def test_upload_without_drive_access_explains(self):
        OnboardingSettings.objects.create(drive_root_folder_id=FOLDER_ID)
        r = self._upload("Kontrakt.pdf")
        self.assertEqual(r.status_code, 400)
        self.assertIn("Drive-adgang", r.json()["detail"])

    @patch("apps.onboarding.google_auth.has_drive_access", return_value=True)
    def test_upload_without_root_folder_explains(self, _):
        r = self._upload("Kontrakt.pdf")
        self.assertEqual(r.status_code, 400)
        self.assertIn("Employee-mappe", r.json()["detail"])

    @patch("apps.onboarding.google_auth.has_drive_access", return_value=True)
    def test_upload_creates_folder_then_reuses_it(self, _):
        OnboardingSettings.objects.create(drive_root_folder_id=FOLDER_ID)
        service = _fake_service()
        with patch("apps.onboarding.drive._service", return_value=service):
            r = self._upload("Kontrakt.pdf", "ID.pdf")
        self.assertEqual(r.status_code, 201, r.content)
        body = r.json()
        self.assertEqual([d["name"] for d in body["results"]][::-1], ["Kontrakt.pdf", "ID.pdf"])
        self.assertEqual(body["folder_url"], "https://drive.google.com/drive/folders/emp-folder-1")
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.drive_folder_id, "emp-folder-1")
        folder_creates = [
            c for c in service.files.return_value.create.call_args_list
            if c.kwargs["body"].get("mimeType") == "application/vnd.google-apps.folder"
        ]
        self.assertEqual(len(folder_creates), 1)
        self.assertEqual(folder_creates[0].kwargs["body"]["name"], "Anna Hansen (E100)")
        self.assertEqual(folder_creates[0].kwargs["body"]["parents"], [FOLDER_ID])
        self.assertEqual(EmployeeDocument.objects.filter(profile=self.profile).count(), 2)
        self.assertEqual(EmployeeDocument.objects.first().uploaded_by, self.manager)

        # Second upload: remembered folder is used, no new folder.
        service2 = _fake_service()
        with patch("apps.onboarding.drive._service", return_value=service2):
            self.assertEqual(self._upload("Bilag.pdf").status_code, 201)
        self.assertFalse(any(
            c.kwargs["body"].get("mimeType") == "application/vnd.google-apps.folder"
            for c in service2.files.return_value.create.call_args_list
        ))
        self.assertEqual(self.client.get(self.url).json()["results"][0]["name"], "Bilag.pdf")

    @patch("apps.onboarding.google_auth.has_drive_access", return_value=True)
    def test_existing_folder_with_same_name_is_reused(self, _):
        OnboardingSettings.objects.create(drive_root_folder_id=FOLDER_ID)
        service = _fake_service(existing=[{"id": "already-there", "name": "Anna Hansen (E100)"}])
        with patch("apps.onboarding.drive._service", return_value=service):
            self.assertEqual(self._upload("Kontrakt.pdf").status_code, 201)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.drive_folder_id, "already-there")

    def test_person_without_profile_400(self):
        PersonFactory(legacy_id="E200", email="x@x.dk", name="No Profile")
        r = self.client.get("/api/onboarding/manage/employees/E200/documents")
        self.assertEqual(r.status_code, 400)


@override_settings(ONBOARDING_SCHEDULER_EMAIL=SCHED)
class SystemEmailSettingTests(TestCase):
    def setUp(self):
        group, _ = Group.objects.get_or_create(name="manager")
        self.manager = User.objects.create_user(username="mgr", email="mgr@blackcapitaltechnology.com")
        self.manager.groups.add(group)
        self.client = Client()
        self.client.force_login(self.manager)

    def _put(self, body):
        return self.client.put(
            "/api/onboarding/manage/settings", data=body, content_type="application/json"
        )

    def test_default_then_override_then_off_then_default(self):
        from apps.onboarding.calendar_booking import scheduler_email

        body = self.client.get("/api/onboarding/manage/settings").json()
        self.assertEqual((body["scheduler_email"], body["system_email_source"]), (SCHED, "default"))

        r = self._put({"system_email": " JVO@blackcapitaltechnology.com "})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["system_email_source"], "setting")
        self.assertEqual(scheduler_email(), "jvo@blackcapitaltechnology.com")
        # Saving the email must not touch the Drive folder setting.
        self.assertEqual(OnboardingSettings.load().drive_root_folder_id, "")

        r = self._put({"system_email": ""})
        self.assertEqual(r.json()["system_email_source"], "none")
        self.assertEqual(scheduler_email(), "")

        r = self._put({"system_email": None})
        self.assertEqual(scheduler_email(), SCHED)

    def test_invalid_email_rejected(self):
        self.assertEqual(self._put({"system_email": "not an email"}).status_code, 400)

    def test_booking_uses_configured_system_account(self):
        from apps.onboarding.calendar_booking import scheduler_user

        me = User.objects.create_user(username="jvo", email="jvo@blackcapitaltechnology.com")
        self._put({"system_email": "jvo@blackcapitaltechnology.com"})
        self.assertEqual(scheduler_user(), me)
