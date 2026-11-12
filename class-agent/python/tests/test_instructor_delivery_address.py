from course_server.config import InstructorMessageTestRecipient
from course_server.mail.instructor_delivery import instructor_message_delivery_address


def test_only_configured_test_student_uses_delivery_override() -> None:
    recipient = InstructorMessageTestRecipient(
        username="test-student2", email="instructor@example.org"
    )
    assert (
        instructor_message_delivery_address("test-student2", "test-student2@example.com", recipient)
        == "instructor@example.org"
    )
    assert (
        instructor_message_delivery_address("alice", "alice@mit.edu", recipient) == "alice@mit.edu"
    )
    assert (
        instructor_message_delivery_address("test-student2", "test-student2@example.com", None)
        == "test-student2@example.com"
    )
