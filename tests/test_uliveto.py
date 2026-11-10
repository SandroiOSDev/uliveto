import re
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, build_opener, HTTPRedirectHandler
from http.server import ThreadingHTTPServer

from uliveto import db
from uliveto.app import AppHandler


TREE = {"code": "A-01", "cultivar": "Leccino", "parcel": "Terrazza nord", "latitude": "40.12", "longitude": "18.44", "planted_year": "2010", "notes": "Vicino al muretto"}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "db.sqlite3"

    def tearDown(self):
        self.temp.cleanup()

    def test_tree_observation_activity_and_latest_health(self):
        with db.connect(self.path) as conn:
            tree_id = db.save_tree(conn, TREE)
            db.add_observation(conn, tree_id, {"observed_on": "2026-01-02", "health": "critico", "symptoms": "Foglie secche", "notes": "Controllare"})
            db.add_observation(conn, tree_id, {"observed_on": "2026-02-02", "health": "sano", "symptoms": "", "notes": "Ripreso"})
            db.add_activity(conn, tree_id, {"done_on": "2026-01-10", "kind": "potatura", "notes": "Rimossi rami secchi"})
            self.assertEqual(db.list_trees(conn)[0]["latest_health"], "sano")
            self.assertEqual(db.summary(conn)["sano"], 1)
            self.assertEqual([e["event_type"] for e in db.timeline(conn, tree_id)], ["observation", "activity", "observation"])
            self.assertEqual(len(db.list_trees(conn, "Leccino", "sano")), 1)
            self.assertEqual(len(db.list_trees(conn, "Leccino", "critico")), 0)

    def test_validation_and_duplicate_code(self):
        with db.connect(self.path) as conn:
            db.save_tree(conn, TREE)
            with self.assertRaisesRegex(db.ValidationError, "già assegnato"):
                db.save_tree(conn, {**TREE, "code": "a-01"})
            with self.assertRaisesRegex(db.ValidationError, "entrambe"):
                db.save_tree(conn, {**TREE, "code": "A-02", "longitude": ""})
            with self.assertRaisesRegex(db.ValidationError, "futura"):
                db.add_observation(conn, 1, {"observed_on": "2999-01-01", "health": "sano"})
            with self.assertRaisesRegex(db.ValidationError, "Descrizione"):
                db.add_activity(conn, 1, {"done_on": "2026-01-10", "kind": "potatura", "notes": ""})


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        handler = type("TestHandler", (AppHandler,), {"database": Path(self.temp.name) / "app.sqlite3", "csrf_token": "test-token"})
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self.opener = build_opener(NoRedirect)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def get(self, path):
        with self.opener.open(self.base + path) as result:
            return result.read().decode("utf-8")

    def post(self, path, values):
        request = Request(self.base + path, data=urlencode(values).encode(), method="POST")
        try:
            return self.opener.open(request)
        except HTTPError as exc:
            return exc

    def test_full_user_flow_and_csv(self):
        self.assertIn("Nessun ulivo trovato", self.get("/"))
        self.assertIn("Registra un ulivo", self.get("/trees/new"))
        response = self.post("/trees/new", {**TREE, "csrf": "test-token"})
        self.assertEqual(response.code, 303)
        self.assertEqual(response.headers["Location"], "/trees/1?saved=1")
        response.close()
        self.assertIn("A-01", self.get("/trees/1"))
        response = self.post("/trees/1/observations", {"csrf": "test-token", "observed_on": "2026-01-02", "health": "attenzione", "symptoms": "Macchie", "notes": "Rivedere"})
        self.assertEqual(response.code, 303)
        response.close()
        response = self.post("/trees/1/activities", {"csrf": "test-token", "done_on": "2026-01-03", "kind": "potatura", "notes": "Ramo secco"})
        self.assertEqual(response.code, 303)
        response.close()
        detail = self.get("/trees/1")
        self.assertIn("Macchie", detail)
        self.assertIn("Ramo secco", detail)
        self.assertIn("Da osservare", self.get("/?health=attenzione"))
        self.assertIn("observation,A-01,Leccino", self.get("/export"))

    def test_rejected_csrf_and_escaped_html(self):
        response = self.post("/trees/new", {**TREE, "csrf": "bad"})
        self.assertEqual(response.code, 403)
        response.close()
        response = self.post("/trees/new", {**TREE, "code": "<script>alert(1)</script>", "csrf": "test-token"})
        self.assertEqual(response.code, 303)
        response.close()
        listing = self.get("/")
        self.assertNotIn("<script>", listing)
        self.assertIn("&lt;script&gt;", listing)


if __name__ == "__main__":
    unittest.main()
