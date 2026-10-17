"""Smoke-check the running local server without private data or model credentials."""
import argparse
from http.cookiejar import CookieJar
import json
import re
import urllib.error
import urllib.parse
import urllib.request


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url",default="http://127.0.0.1:8000")
    parser.add_argument("--expect-frontend",action="store_true")
    args=parser.parse_args()
    base=args.base_url.rstrip("/")
    url=urllib.parse.urlsplit(base)
    if url.scheme!="http" or url.hostname not in {"127.0.0.1","localhost"} or url.path or url.query or url.fragment or url.username:
        parser.error("Only a loopback HTTP origin is accepted")
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPCookieProcessor(CookieJar()))
    checks=[]

    def request(path,method="GET",headers=None,data=None):
        req=urllib.request.Request(base+path,data=data,headers=headers or {},method=method)
        try:
            response=opener.open(req,timeout=8)
        except urllib.error.HTTPError as exc:
            response=exc
        with response:
            return response.status,response.headers,response.read().decode("utf-8")

    def check(name,predicate):
        if not predicate:
            raise SystemExit("SMOKE FAILED: "+name)
        checks.append(name)

    status,headers,body=request("/api/v1/health")
    check("health_without_model",status==200 and json.loads(body)["status"]=="ok")
    check("request_trace_and_no_cache",bool(headers.get("X-Request-ID")) and headers.get("Cache-Control")=="no-store")
    status,headers,body=request("/api/v1/bootstrap")
    bootstrap=json.loads(body)
    check("six_regions_295_seed_destinations",status==200 and len(bootstrap["regions"])==6 and sum(r["destination_count"] for r in bootstrap["regions"])==295)
    write_headers={"Origin":base,"X-CSRF-Token":bootstrap["csrf_token"],"Content-Type":"application/json"}
    status,_,body=request("/api/v1/session/verify","POST",write_headers,b"{}")
    check("same_origin_session_verified",status==200 and json.loads(body)["status"]=="VALID")
    status,_,body=request("/api/v1/session/verify","POST",{**write_headers,"Origin":"https://example.invalid"},b"{}")
    check("foreign_origin_blocked",status==403 and json.loads(body)["error"]["code"]=="FORBIDDEN")
    status,_,body=request("/api/v1/session/verify","POST",{"Origin":base},b"{}")
    check("missing_csrf_blocked",status==403)
    status,headers,body=request("/api/v1/unknown")
    check("unknown_api_not_spa",status==404 and json.loads(body)["error"]["code"]=="NOT_FOUND")
    for path in ("/.env","/data/app.sqlite3","/tests/fixtures/private/manifest.json"):
        status,_,_=request(path)
        check("private_path_not_served:"+path,status in (403,404))
    if args.expect_frontend:
        status,_,html=request("/")
        check("built_frontend_served",status==200 and 'id="root"' in html)
        assets=re.findall(r'(?:src|href)="(/assets/[^\"]+)"',html)
        check("built_assets_present",len(assets)>=2)
        for path in assets:
            status,_,_=request(path)
            check("built_asset_200:"+path,status==200)
    print(json.dumps({"status":"passed","base_url":base,"checks_passed":len(checks),"checks":checks},ensure_ascii=False))


if __name__=="__main__":
    main()
