"""T04 real ASGI requests, local-browser protection and secret redaction."""
from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.app.core.boundary import COOKIE_NAME
from backend.app.core.settings import ROOT, Settings
from backend.app.domain.contracts import PatchRequest
from backend.app.main import create_app

BASE="http://127.0.0.1:8000"
ORIGIN="http://127.0.0.1:5173"


def settings(**kwargs):
    return Settings(_env_file=None,app_port=8000,frontend_port=5173,**kwargs)


@contextmanager
def client_for(**kwargs):
    with TestClient(create_app(settings(**kwargs)),base_url=BASE) as client:
        yield client


def headers(client):
    token=client.get("/api/v1/bootstrap").json()["csrf_token"]
    return {"Origin":ORIGIN,"X-CSRF-Token":token}


class ConfigurationTests(unittest.TestCase):
    def test_loopback_only(self):
        for host in ("0.0.0.0","192.168.1.1","example.com"):
            with self.subTest(host=host), self.assertRaises(ValidationError):
                settings(app_host=host)

    def test_distinct_valid_ports(self):
        with self.assertRaises(ValidationError):
            Settings(_env_file=None,app_port=5173,frontend_port=5173)
        with self.assertRaises(ValidationError):
            Settings(_env_file=None,app_port=80)

    def test_custom_ports_change_origin_allowlist(self):
        s=Settings(_env_file=None,app_port=8100,frontend_port=5180)
        self.assertIn("http://127.0.0.1:5180",s.allowed_origins)
        self.assertNotIn(ORIGIN,s.allowed_origins)

    def test_unconfigured_model_allowed(self):
        self.assertEqual(settings().model_status,"NOT_CONFIGURED")

    def test_filled_config_is_not_a_working_model(self):
        self.assertEqual(settings(model_provider="synthetic",model_name="synthetic",model_api_key="synthetic-test-value").model_status,"ADAPTER_NOT_IMPLEMENTED")

    def test_storage_root_is_project_relative(self):
        self.assertEqual(settings(storage_root="data").storage_root,ROOT/"data")


class SystemAPITests(unittest.TestCase):
    def test_health_is_live_but_database_uninitialized(self):
        with client_for() as client:
            response=client.get("/api/v1/health")
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.json()["status"],"ok")
            self.assertEqual(response.json()["database_status"],"NOT_INITIALIZED")
            self.assertEqual(response.json()["model_status"],"NOT_CONFIGURED")

    def test_bootstrap_has_real_seed_counts(self):
        with client_for() as client:
            body=client.get("/api/v1/bootstrap").json()
            self.assertEqual(body["origin_name"],"青岛港")
            self.assertEqual([r["destination_count"] for r in body["regions"]],[69,61,27,68,49,21])
            self.assertEqual(sum(r["route_group_count"] for r in body["regions"]),34)
            self.assertEqual(body["quotation_status"],"NOT_INITIALIZED")
            self.assertEqual(body["regions"][0]["preview_destinations"][0]["name_en"],"ORANJESTAD")

    def test_no_secret_or_server_paths_in_public_responses(self):
        secret="synthetic-do-not-return-this-value"
        with client_for(model_provider="synthetic",model_name="synthetic",model_api_key=secret,model_base_url="https://example.invalid/private-model") as client:
            for path in ("/api/v1/health","/api/v1/bootstrap","/api/v1/openapi.json"):
                response=client.get(path)
                self.assertNotIn(secret,response.text)
                self.assertNotIn("private-model",response.text)
                self.assertNotIn(str(ROOT),response.text)
            self.assertEqual(client.get("/api/v1/health").json()["model_status"],"ADAPTER_NOT_IMPLEMENTED")

    def test_session_cookie_flags_and_csrf_rotation(self):
        with client_for() as client:
            first=client.get("/api/v1/bootstrap")
            cookie=first.headers["set-cookie"]
            self.assertIn("HttpOnly",cookie)
            self.assertIn("SameSite=strict",cookie)
            self.assertIn("Path=/",cookie)
            second=client.get("/api/v1/bootstrap")
            self.assertEqual(first.json()["csrf_token"],second.json()["csrf_token"])
            self.assertNotIn("set-cookie",second.headers)

    def test_valid_session_verify(self):
        with client_for() as client:
            response=client.post("/api/v1/session/verify",headers=headers(client))
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.json(),{"status":"VALID"})

    def test_readonly_request_ids_and_headers(self):
        with client_for() as client:
            response=client.get("/api/v1/health",headers={"X-Request-ID":"synthetic.request-001"})
            self.assertEqual(response.headers["x-request-id"],"synthetic.request-001")
            self.assertEqual(response.headers["cache-control"],"no-store")
            self.assertEqual(response.headers["x-content-type-options"],"nosniff")

    def test_invalid_request_id_not_reflected(self):
        with client_for() as client:
            response=client.get("/api/v1/health",headers={"X-Request-ID":"x"*90})
            self.assertNotEqual(response.headers["x-request-id"],"x"*90)

    def test_unknown_api_uses_error_contract(self):
        with client_for() as client:
            response=client.get("/api/v1/not-implemented")
            self.assertEqual(response.status_code,404)
            self.assertEqual(response.json()["error"]["code"],"NOT_FOUND")
            self.assertEqual(response.json()["error"]["request_id"],response.headers["x-request-id"])

    def test_runtime_openapi_only_lists_implemented_routes(self):
        with client_for() as client:
            document=client.get("/api/v1/openapi.json").json()
            expected={"/api/v1/health","/api/v1/bootstrap","/api/v1/session/verify"}
            self.assertEqual(set(document["paths"]),expected)
            contract=json.loads((ROOT/"contracts/openapi.json").read_text(encoding="utf-8"))
            declared={"/api/v1"+path for path,methods in contract["paths"].items() if any(o.get("x-implemented") for o in methods.values())}
            self.assertEqual(expected,declared)
            verify=document["paths"]["/api/v1/session/verify"]["post"]
            self.assertEqual({p["name"] for p in verify["parameters"]},{"Origin","X-CSRF-Token"})
            self.assertEqual(verify["security"],[{"LocalSessionCookie":[]}])

    def test_validation_does_not_echo_input(self):
        app=create_app(settings())
        @app.post("/api/v1/test/validate",include_in_schema=False)
        def validate(payload: PatchRequest):
            return {"ok":True}
        with TestClient(app,base_url=BASE) as client:
            response=client.post("/api/v1/test/validate",headers=headers(client),json={"expected_version":"synthetic-secret-input","changes":{}})
            self.assertEqual(response.status_code,422)
            self.assertEqual(response.json()["error"]["code"],"VALIDATION_ERROR")
            self.assertNotIn("synthetic-secret-input",response.text)

    def test_internal_error_does_not_echo_exception(self):
        app=create_app(settings())
        @app.get("/api/v1/test/fail",include_in_schema=False)
        def fail():
            raise RuntimeError("synthetic-private-exception")
        with TestClient(app,base_url=BASE) as client:
            response=client.get("/api/v1/test/fail")
            self.assertEqual(response.status_code,500)
            self.assertEqual(response.json()["error"]["code"],"INTERNAL_ERROR")
            self.assertNotIn("synthetic-private-exception",response.text)


class LocalBoundaryTests(unittest.TestCase):
    def test_untrusted_host_rejected(self):
        with client_for() as client:
            response=client.get("/api/v1/bootstrap",headers={"Host":"evil.example"})
            self.assertEqual(response.status_code,400)
            self.assertEqual(response.json()["error"]["code"],"BAD_REQUEST")

    def test_loopback_spoof_subdomain_rejected(self):
        with client_for() as client:
            self.assertEqual(client.get("/api/v1/health",headers={"Host":"127.0.0.1.evil.example:8000"}).status_code,400)

    def test_unknown_loopback_port_rejected(self):
        with client_for() as client:
            self.assertEqual(client.get("/api/v1/health",headers={"Host":"127.0.0.1:9999"}).status_code,400)

    def test_vite_proxy_host_allowed(self):
        with client_for() as client:
            self.assertEqual(client.get("/api/v1/health",headers={"Host":"127.0.0.1:5173"}).status_code,200)

    def test_foreign_origin_cannot_read_bootstrap(self):
        with client_for() as client:
            response=client.get("/api/v1/bootstrap",headers={"Origin":"https://evil.example"})
            self.assertEqual(response.status_code,403)
            self.assertNotIn("access-control-allow-origin",response.headers)

    def test_cross_site_fetch_metadata_rejected(self):
        with client_for() as client:
            self.assertEqual(client.get("/api/v1/bootstrap",headers={"Sec-Fetch-Site":"cross-site"}).status_code,403)

    def test_write_without_origin_rejected(self):
        with client_for() as client:
            token=headers(client)["X-CSRF-Token"]
            self.assertEqual(client.post("/api/v1/session/verify",headers={"X-CSRF-Token":token}).status_code,403)

    def test_write_without_cookie_rejected(self):
        with client_for() as client:
            self.assertEqual(client.post("/api/v1/session/verify",headers={"Origin":ORIGIN,"X-CSRF-Token":"0"*64}).status_code,403)

    def test_write_without_csrf_rejected(self):
        with client_for() as client:
            headers(client)
            self.assertEqual(client.post("/api/v1/session/verify",headers={"Origin":ORIGIN}).status_code,403)

    def test_wrong_csrf_rejected(self):
        with client_for() as client:
            request_headers=headers(client)
            request_headers["X-CSRF-Token"]="0"*64
            self.assertEqual(client.post("/api/v1/session/verify",headers=request_headers).status_code,403)

    def test_token_not_valid_for_different_session(self):
        with client_for() as client:
            request_headers=headers(client)
            client.cookies.clear()
            headers(client)
            self.assertEqual(client.post("/api/v1/session/verify",headers=request_headers).status_code,403)

    def test_tampered_cookie_rejected(self):
        with client_for() as client:
            request_headers=headers(client)
            client.cookies.clear()
            client.cookies.set(COOKIE_NAME,"synthetic-tampered")
            self.assertEqual(client.post("/api/v1/session/verify",headers=request_headers).status_code,403)

    def test_foreign_origin_cannot_post_even_with_valid_csrf(self):
        with client_for() as client:
            request_headers={**headers(client),"Origin":"http://127.0.0.1:9999"}
            self.assertEqual(client.post("/api/v1/session/verify",headers=request_headers).status_code,403)

    def test_cross_site_preflight_does_not_enable_cors(self):
        with client_for() as client:
            response=client.options("/api/v1/session/verify",headers={"Origin":"https://evil.example","Access-Control-Request-Method":"POST"})
            self.assertEqual(response.status_code,403)
            self.assertNotIn("access-control-allow-origin",response.headers)


class BuiltFrontendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary_root=ROOT/"data/test-tmp"
        cls.temporary_root.mkdir(parents=True,exist_ok=True)
        if not cls.temporary_root.resolve().is_relative_to(ROOT.resolve()):
            raise RuntimeError("Temporary test root must remain inside the workspace")

    def test_single_origin_static_and_api(self):
        with tempfile.TemporaryDirectory(prefix="asw-t04-static-",dir=self.temporary_root) as folder:
            dist=Path(folder)
            (dist/"assets").mkdir()
            (dist/"index.html").write_text("<!doctype html><title>ASW synthetic frontend</title>",encoding="utf-8")
            (dist/"assets/app.js").write_text("console.log('synthetic');",encoding="utf-8")
            with TestClient(create_app(settings(app_env="local"),frontend_dist=dist),base_url=BASE) as client:
                self.assertEqual(client.get("/").status_code,200)
                self.assertIn("ASW synthetic frontend",client.get("/").text)
                self.assertEqual(client.get("/assets/app.js").status_code,200)
                self.assertEqual(client.get("/api/v1/health").status_code,200)
                for path in ("/api/v1/unknown","/.env","/data/app.sqlite3","/tests/fixtures/private","/contracts/openapi.json"):
                    self.assertEqual(client.get(path).status_code,404)

    def test_local_mode_does_not_trust_dev_port(self):
        self.assertNotIn(ORIGIN,settings(app_env="local").allowed_origins)

    def test_missing_frontend_build_fails_startup(self):
        with tempfile.TemporaryDirectory(prefix="asw-t04-missing-",dir=self.temporary_root) as folder:
            with self.assertRaisesRegex(RuntimeError,"Frontend build missing"):
                with TestClient(create_app(settings(app_env="local"),frontend_dist=Path(folder)),base_url=BASE):
                    pass


if __name__=="__main__":
    unittest.main()
