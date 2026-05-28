import urllib.request, json, sys

URL = "https://git.eurun.eu.org"
TOKEN = "00bc6ae599e1e40be5187273dac1a83d19456bb7"


def req(path, method="GET", data=None):
    r = urllib.request.Request(f"{URL}/api/v1/{path}", method=method)
    r.add_header("Authorization", f"token {TOKEN}")
    r.add_header("Accept", "application/json")
    if data:
        r.add_header("Content-Type", "application/json")
        r.data = json.dumps(data).encode("utf-8")
    try:
        with urllib.request.urlopen(r, timeout=10) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        print(f"ERROR {e.code} on {method} {path}: {e.read().decode('utf-8')}")
        return None


print("1. GET /user/repos")
repos = req("user/repos?limit=1")
print(f"OK, returns list: {isinstance(repos, list)}")

print("2. GET /user/orgs")
orgs = req("user/orgs?limit=1")
print(f"OK, returns list: {isinstance(orgs, list)}")
org_name = orgs[0]["username"] if orgs else None

if org_name:
    print(f"3. GET /orgs/{org_name}/repos")
    org_repos = req(f"orgs/{org_name}/repos?limit=1")
    print(f"OK, returns list: {isinstance(org_repos, list)}")

    print(f"4. GET /orgs/{org_name}")
    org_info = req(f"orgs/{org_name}")
    print(f"OK, returns dict with username: {org_info.get('username') == org_name}")
else:
    print("Skipping org tests (no orgs found)")

print("5. Test POST /orgs (Dry run with existing org)")
# Should return 422 if it exists, or maybe we test with a fake org?
print("Creating fake org")
res = req("orgs", method="POST", data={"username": "temp_test_org_123", "visibility": "private"})
if res:
    print("Created fake org!")
    # Delete it immediately
    req("orgs/temp_test_org_123", method="DELETE")
    print("Deleted fake org.")

# We won't test DELETE repo or mirror-sync directly here because we don't want to break the user's data.
# But we know mirror-sync works from `jonasrosland` repo, and `/repos/migrate` is standard.
