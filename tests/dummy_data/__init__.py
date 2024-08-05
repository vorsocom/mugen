# pylint: disable=missing-module-docstring

from app.domain.entity.meeting import CreateMeetingDTO

dummy_create_meeting_dto_virtual = CreateMeetingDTO(
    "virtual",
    "Test Meeting",
    "1970-01-01",
    "09:00:00",
    ["user1@test.platform", "user2@test.platform"],
    "user3@test.platform",
)

dummy_create_meeting_dto_inperson = CreateMeetingDTO(
    "in-person",
    "Test Meeting",
    "1970-01-01",
    "09:00:00",
    ["user1@test.platform", "user2@test.platform"],
    "user3@test.platform",
)
