from unittest.mock import MagicMock, patch

import pytest
from celery.exceptions import Reject, Retry
from resend.exceptions import ResendError

from app.worker.tasks.email import send_email

TASK_ID: str = "5d1f2a9e-0000-4000-8000-000000000002"

EMAIL_KWARGS: dict = {
    "email_id": "0b7e6a4c-0000-4000-8000-000000000001",
    "recipient_email": "merchant@example.com",
    "subject": "DisputePilot: Verify your email",
    "html": "<p>123456</p>",
}


def _resend_error(code: int | str) -> ResendError:
    return ResendError(
        code=code, error_type="error", message="failed", suggested_action="", headers=None
    )


@pytest.fixture
def resend_send():
    with patch("app.worker.tasks.email.resend.Emails.send") as send:
        yield send


@pytest.fixture
def retry():
    # a bound task called directly re-raises instead of publishing a retry message
    with patch.object(send_email, "retry", side_effect=Retry()) as task_retry:
        yield task_retry


class TestSendEmail:
    def test_sends_with_task_id_as_idempotency_key(self, resend_send: MagicMock):
        send_email.push_request(id=TASK_ID)
        try:
            send_email.run(**EMAIL_KWARGS)
        finally:
            send_email.pop_request()

        (params,) = resend_send.call_args.args
        assert params["to"] == EMAIL_KWARGS["recipient_email"]
        assert params["subject"] == EMAIL_KWARGS["subject"]
        assert params["html"] == EMAIL_KWARGS["html"]
        assert resend_send.call_args.kwargs["options"] == {"idempotency_key": TASK_ID}

    @pytest.mark.parametrize("code", [429, 500, 503, "500"])
    def test_transient_error_retries(
        self, resend_send: MagicMock, retry: MagicMock, code: int | str
    ):
        resend_send.side_effect = _resend_error(code)

        with pytest.raises(Retry):
            send_email(**EMAIL_KWARGS)

        assert retry.call_args.kwargs["exc"] is resend_send.side_effect

    @pytest.mark.parametrize("code", [400, 401, 403, 422])
    def test_permanent_error_is_dead_lettered(
        self, resend_send: MagicMock, retry: MagicMock, code: int
    ):
        resend_send.side_effect = _resend_error(code)

        with pytest.raises(Reject) as rejected:
            send_email(**EMAIL_KWARGS)

        assert rejected.value.requeue is False
        retry.assert_not_called()

    def test_retries_exhausted_is_dead_lettered(self, resend_send: MagicMock, retry: MagicMock):
        resend_send.side_effect = _resend_error(500)

        send_email.push_request(retries=send_email.max_retries)
        try:
            with pytest.raises(Reject) as rejected:
                send_email.run(**EMAIL_KWARGS)
        finally:
            send_email.pop_request()

        assert rejected.value.requeue is False
        retry.assert_not_called()
