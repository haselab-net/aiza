"""Every place app.js moves between pages is listed here (the deployment notes):
either the row of tests/test_page_flow.py that goes through it, or why it is
not run there yet. A new way to move between pages -- a new call of a
page-moving function (tests/page_entries.py) -- fails this test until it is
put in the table, so it gets a flow row or at least a stated reason.

    python3 -m unittest discover -s tests -v
"""
import unittest

from page_entries import entries
from test_page_flow import FLOWS

NOT_RUN = "not run: "
ENTRIES = {
    # by link (#) and Back
    "applyHash -> openAuthView": "reload on settings",
    "applyHash -> showPage": "settings, then this host's list by link",
    "applyHash -> selectMachine": "another machine's list by link, then a session here",
    "applyHash -> openSession": "list, a session, back",
    "on window popstate -> closeSession": "list, a session, back",
    # the tabs (the deployment notes)
    "top: ui.pages.settings = () => openAuthView() -> openAuthView": "tabs: 設定, 仕事, its views",   # (showTab, returnToTab)
    "top: ui.pages.showTodo = (view) => showTodoVi -> showTodoView": "tabs: 設定, 仕事, its views",
    "top: ui.pages.hideTodo = () => hideTodoView() -> hideTodoView": "tabs: 設定, 仕事, its views",
    "showTab -> showPage": "tabs: 設定, 仕事, its views",
    "returnToTab -> showPage": "list, a session, back",
    # the machine menu and settings
    "applyMachineFilter -> openAuthView": "settings and back by the menu",
    "applyMachineFilter -> showPage": "settings and back by the menu",
    "openAuthView -> showPage": "reload on settings",
    "openSessionFromAuth -> openSession": "設定's ログイン, back to 設定",   # (authLogin, by openSessionFromAuth)
    # sessions
    "openSession -> showPage": "list, a session, back",
    "openSession -> selectMachine": "another machine's list by link, then a session here",
    "openSession -> hideTodoView": "an extension opens a session over the to-do list",
    "openSession -> openSession": "an extension opens a session over the to-do list",
    "makeSessionRow -> openSession": "list: tap a session row, ← back",
    "on backLinkEl click -> closeSession": "list: tap a session row, ← back",
    "on viewChat click -> closeSession": "設定's ログイン ended, a tap goes back to 設定",
    "on viewChat touchend -> closeSession": "a swipe right goes back",
    "on createBtn click -> openSession": "start a new session",
    "on placeEl change -> selectMachine": "start screen: an ssh machine in どこで",
    "openStart -> selectMachine": "start screen opened for a machine",
    "adoptSession -> openSession": "attach a tmux session",
    "openLockedSession -> openSession": "a row locked behind the passkey",
    "openSearchHit -> openSession": "search, open a hit",
    "fillArchivedList -> openSession": "the archived list",
    "renderSharedSection -> openSession": "a session shared with me",
    "renderSharePane -> openSession": "share pane: → a linked session",
    "renderSharePane -> closeSession": "share pane: 🔗 add another goes to the list",
    "renderSharePaneBody -> openSession": "share pane: move to the Email box",
    "resumeEndedSession -> openSession": "resume an ended session from its chat",
    "resumeToSend -> openSession": "send to a stopped session: resumed first, then sent",
    "showTakeButtons -> openSession": "take over a session shared with me read-only",
    "startIssueSession -> openSession": "a GitHub issue link",
    "connectSessionEvents -> openSession": "a session whose history asks for the passkey again after the unlock",
    "stopSessionConfirmed -> closeSession": "stop a session from its chat",
    "patrolGo -> openSession": "patrol: next",
    "patrolAct -> openSession": "patrol: archive goes to the next",
    "patrolAct -> closeSession": "patrol: delete the last one goes to the list",
    "app.openSession -> openSession": "an extension opens a session over the to-do list",
    "app.openSessionById -> openSession": "an extension opens a session by id",
    # the to-do list
    "showTodoView -> closeSession": "to-do list from a session",
    "openSessionOverTodo -> openSession": "to-do list: open a session from it, back returns to it",   # (its links, and the tree's ▶ 🤛 ✍: test_page_tree)
    "top: if (TODO_PAGE) { -> showTodoView": "/todo opened directly",
    "treeMenuItems -> setTodo": "⛓ from a node's ⋯, ← back to the tree",
    "renderChain -> setTodo": "⛓ from a node's ⋯, ← back to the tree",
    "jumpToTreeNode -> closeSession": "share pane: 🌳 to its branch",
    "TodoTree -> setTodo": NOT_RUN + "an old 見方 (木 / 人と AI) kept in this browser: 番ごと (the deployment notes 段5)",
    # the blackboard and voice
    "on machineBtnEl click -> openBoard": "the blackboard: open, close",
    "on boardModalEl click -> closeBoard": "the blackboard: open, close",
    "openBoardMachine -> closeBoard": "blackboard: no 設定 in its list",
    "renderBoard -> closeBoard": "blackboard: open a session using a machine",
    "renderBoard -> openBoardMachine": "blackboard: no 設定 in its list",
    "renderBoard -> openSession": "blackboard: open a session using a machine",
    "openBoardMachine -> applyMachineFilter": "blackboard: no 設定 in its list",
    "openBoardMachine -> closeSession": "blackboard: this host from a session",
    "voiceOpen -> openSession": "voice: a session by its name, 戻って",
    "openAudioMenu -> closeSession": NOT_RUN + "the 🔊 menu's ⚙ 設定 from a chat: 設定's card (test_page_speak, the settings)",
    "voiceBack -> closeSession": "voice: a session by its name, 戻って",
    "voiceBack -> hideTodoView": "voice: やること, 戻って",
    "voiceAct -> closeSession": "voice: close the session (the server's answer)",
    "voiceStopSession -> closeSession": "voice: 停止, はい",
    "voiceShowTodo -> showTodoView": "voice: やること, 戻って",
}


class PageEntriesTest(unittest.TestCase):
    def test_every_entry_is_classified(self):
        found = set(entries())
        self.assertEqual(sorted(found - set(ENTRIES)), [],
                         "new ways to move between pages: add a row to test_page_flow.FLOWS or a reason here")
        self.assertEqual(sorted(set(ENTRIES) - found), [], "gone from app.js: take them out of ENTRIES")

    def test_rows_exist(self):
        for k, v in ENTRIES.items():
            if not v.startswith(NOT_RUN):
                self.assertIn(v, FLOWS, k)

    def test_report(self):
        run = sum(1 for v in ENTRIES.values() if not v.startswith(NOT_RUN))
        print(f"\npage entries: {run} of {len(ENTRIES)} run in test_page_flow")


if __name__ == "__main__":
    unittest.main()
