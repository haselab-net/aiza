"""Late answers in the parts outside app.js and chat.js (the deployment notes):
the user moved on before the answer came, and the answer must not write
into where they went. Same probe and stand-in backend as
test_page_failures.py; the cases of app.js and chat.js are there.

    python3 -m unittest discover -s tests -v
"""
import unittest

import test_page_failures as F   # (not its class itself: unittest would run it here again)
from test_page_failures import CHROME, OPENED_S1, S0, S1

FAULTS = "fetch('/agents/api/__faults', {method: 'POST', body: JSON.stringify(%s)})"

# name: (faults, [(js, wait ms)])
CASES = {
    # share.js: 🧑‍🤝‍🧑 共有する on s0, answered once s1 is open.
    "late: a share answered after moving to another session": ({f"POST /sessions/{S0}/share": [
        {"after": OPENED_S1, "body": {"shared_with": ["bob"], "shared_read": []}}]}, [
        ("document.getElementById('share-btn').click()", 300),
        ("const p = document.getElementById('share-pane'); p.querySelector('#share-target').value = 'user';"
         " p.querySelector('#share-target').dispatchEvent(new Event('change'));"
         " p.querySelector('#share-username').value = 'bob'; p.querySelector('#share-add-btn').click();"
         f" window.aizaExt.app.openSessionById('{S1}')", 2500),
        ("document.getElementById('share-btn').click()", 300),
        ("out.at = window.__aizaSession();"
         " out.rows = [...document.querySelectorAll('#share-pane .share-row')].map((e) => e.dataset.user)", 100),
    ]),
    # list.js: ‹ 前 in the patrol bar on s0, its list answered once s1 is open
    # (s1 opened from the list the page has, so that only the patrol asks for one;
    # the fault is added here so that the page's own first list does not take it).
    "late: a patrol step answered after moving to another session": ({}, [
        (FAULTS % "{'GET /sessions': [{after: '%s'}]}" % OPENED_S1, 300),
        ("document.getElementById('patrol-prev').click();"
         f" const a = window.aizaExt.app; a.openSession(a.findSession('{S1}'))", 2500),
        ("out.at = window.__aizaSession()", 100),
    ]),
}


@unittest.skipUnless(CHROME, "headless Chrome is needed for the page tests")
class PageLateTest(unittest.TestCase):
    run_case = staticmethod(F.PageFailureTest.run_case)
    got = F.PageFailureTest.got

    @classmethod
    def setUpClass(cls):
        cls.results = {name: cls.run_case(*case) for name, case in CASES.items()}

    def test_a_late_share_does_not_show_on_the_session_moved_to(self):
        out = self.got("late: a share answered after moving to another session")
        self.assertEqual(out["at"], S1)
        self.assertEqual(out["rows"], [])

    def test_a_late_patrol_step_does_not_move_away_from_where_the_user_went(self):
        out = self.got("late: a patrol step answered after moving to another session")
        self.assertEqual(out["at"], S1)


if __name__ == "__main__":
    unittest.main()
