import urllib.request, json
url = "https://git.eurun.eu.org"
token = "00bc6ae599e1e40be5187273dac1a83d19456bb7"

req = urllib.request.Request(f"{url}/api/v1/user/repos?limit=50")
req.add_header("Authorization", f"token {token}")
with urllib.request.urlopen(req) as resp:
    data = json.loads(resp.read().decode())
    print("User repos:", len(data))

req = urllib.request.Request(f"{url}/api/v1/user/orgs")
req.add_header("Authorization", f"token {token}")
with urllib.request.urlopen(req) as resp:
    orgs = json.loads(resp.read().decode())
    print("Orgs:", [o["username"] for o in orgs])
    for org in orgs:
        req = urllib.request.Request(f"{url}/api/v1/orgs/{org['username']}/repos?limit=50")
        req.add_header("Authorization", f"token {token}")
        with urllib.request.urlopen(req) as resp:
            org_repos = json.loads(resp.read().decode())
            print(f"Org {org['username']} repos:", len(org_repos))
