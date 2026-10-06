from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from max_channel_agent.adapters import Delivery
from max_channel_agent.collectors import Item
from max_channel_agent.config import AgentError, Settings, fingerprint
from max_channel_agent.db import Approval, Draft, DraftRevision, Intent, Job, Material, Story, now
from max_channel_agent.editorial import next_slot, translation_gate

from conftest import write_topic


def seed(service, text="Нейросеть создала короткое видео длительностью 12 секунд."):
    service.ingest(
        "example_rss", [Item("article", "Нейровидео", text, "https://example.org/a", now(), "ru")]
    )
    with service.db.session() as session:
        return session.scalar(select(Story.id))


def draft(service):
    return service.edit_story("main", seed(service))


def ready_for_send(service):
    topic = service.settings.topic
    topic["channels"][0]["publication"]["mode"] = "review"
    write_topic(service.settings.root, topic)
    service.activate(Settings.load(service.settings.root))
    service.connect("main", "-123")
    service.pause("main", False)
    did = draft(service)
    with service.db.session() as session:
        d = session.get(Draft, did)
        revision, content_hash = d.revision, fingerprint(d.current)
    service.approve(did, revision, content_hash)
    with service.db.session.begin() as session:
        session.get(Draft, did).scheduled_at = now() - 1
    return did


def test_exact_and_cross_source_dedup(service):
    sid = seed(service)
    assert seed(service) == sid
    with service.db.session() as session:
        assert len(session.scalars(select(Material)).all()) == 1
        assert len(session.scalars(select(Job)).all()) == 1


def test_changed_source_not_discarded(service):
    seed(service)
    service.ingest(
        "example_rss",
        [
            Item(
                "article",
                "Обновление",
                "Видео длится 15 секунд.",
                "https://example.org/a",
                now(),
                "ru",
            )
        ],
    )
    with service.db.session() as session:
        assert len(session.scalars(select(Material)).all()) == 2


def test_draft_has_evidence_and_review(service):
    did = draft(service)
    with service.db.session() as session:
        d = session.get(Draft, did)
        assert d.state == "review_pending"
        assert "https://example.org/a" in d.current["body"]
        assert d.current["checks"] == ["EDITOR_REVIEW_REQUIRED"]
        assert session.scalar(select(DraftRevision))


def test_revision_revokes_approval(service):
    did = ready_for_send(service)
    with service.db.session() as session:
        body = session.get(Draft, did).current["body"]
    service.revise(did, 1, body)
    with service.db.session() as session:
        assert session.get(Draft, did).revision == 2
        assert session.scalar(select(Approval)).revoked
        assert len(session.scalars(select(DraftRevision)).all()) == 2
    assert service.publish_due() == 0


def test_stale_approval_rejected(service):
    did = draft(service)
    with pytest.raises(AgentError, match="CONFLICT"):
        service.approve(did, 2, "invalid")


def test_dry_run_cannot_publish(service):
    did = draft(service)
    service.connect("main", "-123")
    service.pause("main", False)
    with service.db.session() as session:
        d = session.get(Draft, did)
        h = fingerprint(d.current)
    service.approve(did, 1, h)
    with service.db.session.begin() as session:
        session.get(Draft, did).scheduled_at = now() - 1
    assert service.publish_due() == 0
    with service.db.session() as session:
        assert session.scalar(select(Intent)) is None


def test_confirmed_send_once(service):
    did = ready_for_send(service)
    assert service.publish_due() == 1
    assert service.publish_due() == 0
    with service.db.session() as session:
        assert session.get(Draft, did).state == "published"
        assert session.scalar(select(Intent)).external_id.startswith("offline-")


def test_unknown_send_no_blind_retry(service):
    ready_for_send(service)
    calls = []

    def unknown(chat, body):
        calls.append(body)
        return Delivery("unknown")

    service.publisher.publish = unknown
    assert service.publish_due() == 0
    assert service.publish_due() == 0
    with service.db.session() as session:
        assert session.scalar(select(Intent)).state == "unknown"
    assert len(calls) == 1


def test_sending_after_crash_is_not_retried(service):
    did = ready_for_send(service)
    with service.db.session.begin() as session:
        d = session.get(Draft, did)
        session.add(
            Intent(
                draft_id=did,
                channel_id="main",
                state="sending",
                body_hash=fingerprint(d.current["body"]),
            )
        )
    assert service.publish_due() == 0


def test_pause_stops_send(service):
    ready_for_send(service)
    service.pause("main")
    assert service.publish_due() == 0


def test_bad_topic_stops_send(service):
    ready_for_send(service)
    (service.settings.root / "TOPIC.md").write_text("corrupt")
    assert service.publish_due() == 0
    assert service.config_error == "CONFIG_INVALID"


def test_source_failure_does_not_move_cursor(service):
    def fail(*args):
        raise AgentError("SOURCE_HTTP_403")

    service.http.get = fail
    service.tick()
    with service.db.session() as session:
        jobs = session.scalars(select(Job).where(Job.kind == "collect")).all()
        assert len(jobs) == 1 and jobs[0].state == "dead_letter"


def test_scheduler_catchup_bounded(service):
    service.schedule_sources()
    service.schedule_sources()
    with service.db.session() as session:
        assert len(session.scalars(select(Job)).all()) == 1


@pytest.mark.parametrize(
    "original,translated",
    [("video 12 seconds", "видео 15 секунд"), ("video 12 seconds", "video 12 seconds")],
)
def test_translation_guard(original, translated):
    with pytest.raises(AgentError):
        translation_gate(original, translated)


def test_calendar_respects_cap_and_gap(service):
    channel = service.settings.channel("main")
    start = datetime(2026, 10, 6, 0, 0, tzinfo=UTC).timestamp()
    slots = []
    for _ in range(5):
        slots.append(next_slot(channel, slots, start))
    assert all(b - a >= 7200 for a, b in zip(slots, slots[1:], strict=False))
    assert (
        datetime.fromtimestamp(slots[3], UTC).date() > datetime.fromtimestamp(slots[0], UTC).date()
    )


def test_excluded_topic_blocks(service):
    with pytest.raises(AgentError, match="EXCLUDED_TOPIC"):
        service.edit_story("main", seed(service, "Нейровидео для казино"))


def test_unknown_publication_date_requires_review(service):
    service.ingest(
        "example_rss", [Item("nodate", "Видео", "Короткое видео.", "https://example.org/a")]
    )
    with service.db.session() as session:
        sid = session.scalar(select(Story.id))
    with pytest.raises(AgentError, match="UNKNOWN_PUBLICATION_DATE"):
        service.edit_story("main", sid)


def test_unknown_model_price_blocks(service):
    service.editor.mode = "live"
    with pytest.raises(AgentError, match="MODEL_PRICE_UNKNOWN"):
        service.model_task("bootstrap", "main", {})


def test_paid_model_zero_budget_blocks(service):
    service.editor.mode = "live"
    service.settings.app["opencode"]["max_task_cost_rub"] = 1
    with pytest.raises(AgentError, match="BUDGET_EXCEEDED"):
        service.model_task("bootstrap", "main", {})


def test_report_unknown_metrics_not_zero(service):
    report = service.report("main")
    assert report["subscribers"] == "unavailable" and report["views"] == "unavailable"


def test_growth_plan_never_executes_external(service):
    campaign = service.growth_plan("main")
    assert campaign["state"] == "planning"
