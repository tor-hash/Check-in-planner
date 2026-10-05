"""Upload employee documents (contracts, ...) to Google Drive.

Layout in Drive::

    <Employee folder>                 ← OnboardingSettings.drive_root_folder_id
        Anna Hansen (E100)/           ← one per employee, created on first upload
            Kontrakt.pdf
            ...

All Drive calls are made as the system account (Onboarding → Indstillinger,
see ``calendar_booking.scheduler_email``), which needs:

1. edit access to the Employee folder (share it with the scheduler), and
2. to have granted Drive access once — "Giv Drive-adgang" on the
   Onboarding → Indstillinger tab (see ``google_auth.py``).

Works for folders in a shared drive as well as in someone's "My Drive".
The employee's folder id is remembered on ``OnboardingProfile.drive_folder_id``,
so renaming the folder (or the employee) never creates a duplicate.
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

FOLDER_MIME = "application/vnd.google-apps.folder"
MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # Cloud Run caps request bodies at 32 MB

_FOLDER_URL_RE = re.compile(r"/folders/([A-Za-z0-9_-]{10,})")
_ID_PARAM_RE = re.compile(r"[?&]id=([A-Za-z0-9_-]{10,})")
_BARE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{10,}$")


class DriveError(Exception):
    """A user-facing problem (not connected, no access, bad folder, ...)."""


def parse_folder_id(value: str) -> str:
    """Accept a Drive folder link or a bare folder id; return the id."""
    value = (value or "").strip()
    for regex in (_FOLDER_URL_RE, _ID_PARAM_RE):
        m = regex.search(value)
        if m:
            return m.group(1)
    if _BARE_ID_RE.match(value):
        return value
    raise DriveError(
        "Det ligner ikke et Google Drive-mappelink. Kopiér linket fra "
        "adresselinjen når mappen er åben i Drive (…/drive/folders/<id>)."
    )


def folder_url(folder_id: str) -> str:
    return f"https://drive.google.com/drive/folders/{folder_id}" if folder_id else ""


def drive_user():
    """The account Drive calls are made as (the scheduler). Raises DriveError."""
    from .calendar_booking import OrganizerResolutionError, scheduler_email, scheduler_user
    from .google_auth import has_drive_access

    if not scheduler_email():
        raise DriveError(
            "Der er ikke valgt en systemkonto. Vælg den under Onboarding → Indstillinger."
        )
    try:
        user = scheduler_user()
    except OrganizerResolutionError as exc:
        raise DriveError(str(exc)) from exc
    if not has_drive_access(user):
        raise DriveError(
            f"{user.email} har ikke givet adgang til Google Drive endnu. Log ind som "
            f"{user.email} og klik \"Giv Drive-adgang\" under Onboarding → Indstillinger."
        )
    return user


def _service(user):
    from googleapiclient.discovery import build

    from apps.planner.google.credentials import credentials_for_user

    return build("drive", "v3", credentials=credentials_for_user(user), cache_discovery=False)


def _http_error_message(exc) -> str:
    status = getattr(getattr(exc, "resp", None), "status", None)
    if status in (403, 404):
        return (
            "Planlægger-kontoen kan ikke se eller skrive i mappen. Del mappen med "
            "systemkontoen med redigeringsadgang."
        )
    return f"Google Drive svarede med en fejl: {exc}"


def get_folder(service, folder_id: str) -> dict:
    from googleapiclient.errors import HttpError

    try:
        meta = (
            service.files()
            .get(fileId=folder_id, fields="id,name,mimeType,trashed", supportsAllDrives=True)
            .execute()
        )
    except HttpError as exc:
        raise DriveError(_http_error_message(exc)) from exc
    if meta.get("mimeType") != FOLDER_MIME:
        raise DriveError("Linket peger ikke på en mappe.")
    if meta.get("trashed"):
        raise DriveError("Mappen ligger i papirkurven.")
    return meta


def verify_root_folder(value: str) -> tuple[str, str]:
    """Check the Employee folder is reachable. Returns ``(folder_id, name)``."""
    folder_id = parse_folder_id(value)
    meta = get_folder(_service(drive_user()), folder_id)
    return folder_id, meta.get("name", "")


def employee_folder_name(profile) -> str:
    person = getattr(profile, "planner_person", None)
    name = " ".join(p for p in (profile.first_name, profile.last_name) if p).strip()
    if not name and person is not None:
        name = (person.name or "").strip()
    name = name or profile.user.email
    return f"{name} ({profile.erp_employee_id})"


def _escape_query(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def ensure_employee_folder(service, profile, root_folder_id: str) -> str:
    """Return the id of the employee's folder, creating it if needed."""
    from googleapiclient.errors import HttpError

    if profile.drive_folder_id:
        try:
            meta = (
                service.files()
                .get(fileId=profile.drive_folder_id, fields="id,trashed", supportsAllDrives=True)
                .execute()
            )
            if not meta.get("trashed"):
                return profile.drive_folder_id
        except HttpError:
            logger.warning(
                "drive: remembered folder %s for %s is gone; finding/creating again",
                profile.drive_folder_id, profile.erp_employee_id,
            )

    name = employee_folder_name(profile)
    try:
        existing = (
            service.files()
            .list(
                q=(
                    f"'{_escape_query(root_folder_id)}' in parents and "
                    f"name = '{_escape_query(name)}' and "
                    f"mimeType = '{FOLDER_MIME}' and trashed = false"
                ),
                fields="files(id,name)",
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
                pageSize=1,
            )
            .execute()
            .get("files", [])
        )
        if existing:
            folder_id = existing[0]["id"]
        else:
            folder_id = (
                service.files()
                .create(
                    body={"name": name, "mimeType": FOLDER_MIME, "parents": [root_folder_id]},
                    fields="id",
                    supportsAllDrives=True,
                )
                .execute()["id"]
            )
    except HttpError as exc:
        raise DriveError(_http_error_message(exc)) from exc

    profile.drive_folder_id = folder_id
    profile.save(update_fields=["drive_folder_id", "updated_at"])
    return folder_id


def upload_employee_documents(*, profile, files, uploaded_by) -> list:
    """Upload Django ``UploadedFile``s to the employee's folder.

    Returns the created ``EmployeeDocument`` rows. Raises ``DriveError``
    for anything the manager can fix (settings, access, size).
    """
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaIoBaseUpload

    from .models import EmployeeDocument, OnboardingSettings

    if not files:
        raise DriveError("Vælg mindst én fil.")
    for f in files:
        if f.size > MAX_UPLOAD_BYTES:
            raise DriveError(
                f"“{f.name}” er for stor ({f.size // (1024 * 1024)} MB) — max "
                f"{MAX_UPLOAD_BYTES // (1024 * 1024)} MB pr. fil."
            )

    root = OnboardingSettings.load().drive_root_folder_id
    if not root:
        raise DriveError(
            "Der er ikke valgt en Employee-mappe i Google Drive endnu. Indsæt linket "
            "under Onboarding → Indstillinger."
        )

    service = _service(drive_user())
    folder_id = ensure_employee_folder(service, profile, root)

    documents = []
    for f in files:
        media = MediaIoBaseUpload(
            f, mimetype=f.content_type or "application/octet-stream", resumable=True
        )
        try:
            created = (
                service.files()
                .create(
                    body={"name": f.name, "parents": [folder_id]},
                    media_body=media,
                    fields="id,name,webViewLink,mimeType,size",
                    supportsAllDrives=True,
                )
                .execute()
            )
        except HttpError as exc:
            raise DriveError(_http_error_message(exc)) from exc
        documents.append(
            EmployeeDocument.objects.create(
                profile=profile,
                name=created.get("name") or f.name,
                drive_file_id=created["id"],
                web_view_link=created.get("webViewLink", ""),
                mime_type=created.get("mimeType", ""),
                size_bytes=int(created["size"]) if created.get("size") else f.size,
                uploaded_by=uploaded_by,
            )
        )
        logger.info(
            "drive: uploaded %s for %s (file %s) by %s",
            f.name, profile.erp_employee_id, created["id"], getattr(uploaded_by, "email", "?"),
        )
    return documents
