"""Executable invariants for the future Svenbot Link device task protocol."""
import tempfile
import unittest
from pathlib import Path

from svenbot.link_tasks import TaskInbox, TaskConflict


class InboxTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.temp.name) / "inbox.sqlite3")
        self.inbox = TaskInbox(self.path)

    def tearDown(self):
        self.inbox.close()
        self.temp.cleanup()

    def task(self, req="abc", text="Read my shop inventory"):
        return self.inbox.submit(device_id="phone-A", request_id=req, intent=text)

    def move(self, task, state, actor="mac", result=None):
        return self.inbox.transition(task["id"], expected_revision=task["revision"],
                                     new_state=state, actor=actor, result=result)

    def test_idempotent_submission_and_conflicting_replay(self):
        a = self.task()
        self.assertEqual(a["id"], self.task()["id"])
        self.assertEqual(len(self.inbox.list(device_id="phone-A")), 1)
        with self.assertRaises(TaskConflict):
            self.task(text="Delete all listings")
        self.assertEqual(self.inbox.get(a["id"])["intent"], "Read my shop inventory")

    def test_approval_flow_is_explicit_and_replay_safe(self):
        a = self.task()
        with self.assertRaises(TaskConflict):
            self.move(a, "approved", actor="owner")
        a = self.move(a, "waiting_approval")
        with self.assertRaises(TaskConflict):
            self.move(a, "approved", actor="mac")
        b = self.move(a, "approved", actor="owner")
        with self.assertRaises(TaskConflict):
            self.move(a, "cancelled", actor="owner")
        b = self.move(b, "running")
        b = self.move(b, "completed", result="Dry-run complete")
        self.assertEqual(b["state"], "completed")
        self.assertEqual([e["state"] for e in self.inbox.history(b["id"])],
                         ["queued", "waiting_approval", "approved", "running", "completed"])
        with self.assertRaises(TaskConflict):
            self.move(b, "running")

    def test_owner_rejects_approval(self):
        a = self.move(self.task(), "waiting_approval")
        with self.assertRaises(TaskConflict):
            self.move(a, "cancelled", actor="mac")
        self.assertEqual(self.move(a, "cancelled", actor="owner")["state"], "cancelled")

    def test_crash_recovery_never_reexecutes(self):
        running = self.move(self.task(), "running")
        self.inbox.close()
        self.inbox = TaskInbox(self.path)
        self.assertEqual(self.inbox.recover_interrupted(), 1)
        self.assertEqual(self.inbox.recover_interrupted(), 0)
        recovered = self.inbox.get(running["id"])
        self.assertEqual(recovered["state"], "uncertain")
        self.assertEqual(recovered["revision"], running["revision"] + 1)
        with self.assertRaises(TaskConflict):
            self.move(recovered, "running")

    def test_no_result_before_terminal(self):
        a = self.task()
        with self.assertRaises(ValueError):
            self.move(a, "running", result="fake completion")
        a = self.move(a, "running")
        with self.assertRaises(ValueError):
            self.move(a, "completed")
        self.assertEqual(self.move(a, "uncertain", result="Provider state unknown")["state"],
                         "uncertain")

    def test_isolation_by_device(self):
        self.task()
        other = self.inbox.submit(device_id="phone-B", request_id="abc",
                                  intent="Read my shop inventory")
        self.assertEqual(len(self.inbox.list(device_id="phone-A")), 1)
        self.assertEqual(self.inbox.list(device_id="phone-B")[0]["id"], other["id"])

    def test_input_bounds_and_state_validation(self):
        for request in ("", "x" * 129):
            with self.assertRaises(ValueError):
                self.inbox.submit(device_id="phone-A", request_id=request, intent="read")
        a = self.task()
        with self.assertRaises(ValueError):
            self.move(a, "run_shell")
        with self.assertRaises(ValueError):
            self.inbox.transition(a["id"], expected_revision=True,
                                  new_state="running", actor="mac")
        self.assertEqual(self.inbox.get(a["id"])["revision"], 0)

    def test_persistence(self):
        a = self.task()
        self.inbox.close()
        self.inbox = TaskInbox(self.path)
        self.assertEqual(self.inbox.get(a["id"])["state"], "queued")
        self.assertEqual(len(self.inbox.history(a["id"])), 1)


if __name__ == "__main__":
    unittest.main()
